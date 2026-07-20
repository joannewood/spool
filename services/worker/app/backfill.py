import os

from common import ingest
from common.paths import is_ignorable_junk, is_model_file, is_zip_file, to_host_path
from common.roots import fetch_active_roots
from common.zip_ingest import stage_zip_if_relevant

from .relationship_suggest import suggest_folder_project, suggest_for_file


def _walk_project_folders(container_root_path):
    """Yields (dirpath, model_paths, sidecar_paths, zip_paths) per
    directory — lets callers see a folder's full contents at once, so
    sidecars can be indexed alongside whatever model files justify
    treating that folder as a project."""
    for dirpath, _dirnames, filenames in os.walk(container_root_path):
        full_paths = [os.path.join(dirpath, f) for f in filenames if not is_ignorable_junk(f)]
        model_paths = [p for p in full_paths if is_model_file(p)]
        zip_paths = [p for p in full_paths if is_zip_file(p)]
        sidecar_paths = [p for p in full_paths if p not in model_paths and p not in zip_paths]
        yield dirpath, model_paths, sidecar_paths, zip_paths


def _ingest_new_path(conn, root, dropfolder_root, container_path):
    """Stage+hash a path discovered on disk that isn't in the DB yet —
    shared by the one-shot startup backfill and the periodic rescan so
    "how a brand-new file gets indexed" is defined in exactly one place.
    Returns whether it was genuinely new (False if already known, or if a
    concurrent relocate already claimed this path)."""
    if root.ingest_mode == "relocate_to_dropfolder":
        target_root = dropfolder_root
        target_path = ingest.relocate(root, dropfolder_root, container_path)
        if target_path is None:
            return False
    else:
        target_root = root
        target_path = container_path

    file_id = ingest.stage_and_hash(conn, target_root, target_path)
    if file_id is None:
        return False

    ext = os.path.splitext(target_path)[1].lower()
    filename = os.path.basename(target_path)
    host_path = to_host_path(target_root, target_path)
    suggest_for_file(conn, file_id, filename, ext)
    suggest_folder_project(conn, file_id, host_path, target_root)
    ingest.maybe_enqueue_render(conn, file_id, ext)
    return True


def run_backfill(conn):
    roots = fetch_active_roots(conn)
    dropfolder_root = next((r for r in roots if r.kind == "drop_folder"), None)
    if dropfolder_root is None:
        raise RuntimeError("no active drop_folder root configured")

    for root in roots:
        new_count = 0
        # Materialized into a list before any relocation happens — moving a
        # whole leaf folder mid-walk (see ingest.relocate) could otherwise
        # disrupt os.walk's still-in-progress traversal of that same tree.
        for dirpath, model_paths, sidecar_paths, zip_paths in list(_walk_project_folders(root.container_path)):
            for zip_path in zip_paths:
                # Per-item try/except (here and below) so a single
                # unreadable file — confirmed live during a ~2800-file
                # bulk move out of iCloud Drive, where a handful of files
                # transiently raised OSError: [Errno 35] Resource deadlock
                # avoided on a full read (stat-only calls like getsize/
                # getmtime succeeded fine; only actual file content reads
                # failed) — never crashes the whole backfill walk. Before
                # this, one bad file mid-walk raised out of run_backfill
                # entirely, which has no caller-side try/except at startup
                # (unlike run_rescan, which main() already wraps), so the
                # whole worker process crashed and, under `restart:
                # unless-stopped`, immediately retried the *entire* backfill
                # from scratch — reliably hitting the same file again. A
                # skipped file here just isn't staged yet; it's picked up
                # by the next backfill/rescan pass once it becomes readable,
                # no special retry bookkeeping needed.
                try:
                    stage_zip_if_relevant(conn, root, zip_path)
                except Exception as exc:
                    print(f"[worker] backfill: skipping zip {zip_path} due to error: {exc}", flush=True)

            if not model_paths:
                continue

            for container_path in model_paths:
                try:
                    if _ingest_new_path(conn, root, dropfolder_root, container_path):
                        new_count += 1
                except Exception as exc:
                    print(f"[worker] backfill: skipping {container_path} due to error: {exc}", flush=True)

            # Sidecars ride along with whatever root/target the model files
            # in this folder actually landed at — but relocation is already
            # handled per-file above (and a whole-folder relocate moves
            # sidecars for free); index sidecars only for index_in_place
            # roots here, since a relocate_to_dropfolder root's sidecars
            # either already moved with their folder or will be discovered
            # at their new home once that folder shows up in the drop
            # folder's own walk.
            if root.ingest_mode != "relocate_to_dropfolder":
                for sidecar_path in sidecar_paths:
                    try:
                        ingest.stage_sidecar(conn, root, sidecar_path)
                    except Exception as exc:
                        print(f"[worker] backfill: skipping sidecar {sidecar_path} due to error: {exc}", flush=True)

        print(f"[worker] backfill — {root.label}: {new_count} new file(s)", flush=True)
