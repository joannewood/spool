import os
from datetime import datetime, timezone

from psycopg.rows import dict_row

from common import ingest
from common.hashing import sha256_file
from common.paths import to_host_path
from common.roots import fetch_active_roots
from common.zip_ingest import stage_zip_if_relevant

from .backfill import _ingest_new_path, _walk_project_folders

_RESET_GEOMETRY = """
    thumbnail_path = NULL,
    bbox_x = NULL, bbox_y = NULL, bbox_z = NULL,
    volume_mm3 = NULL, tri_count = NULL, is_manifold = NULL
"""


def _reconcile_known_file(conn, row, container_path):
    """`row` (id/path/size_bytes/content_hash/mtime/status) is a file the DB
    already knows about that's still present on disk at container_path —
    decide whether it drifted since it was last recorded. A cheap stat
    (size + mtime) gates the expensive re-hash, per the mtime column's
    whole reason for existing (see migration 006)."""
    stat = os.stat(container_path)
    disk_size = stat.st_size
    disk_mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)

    was_missing = row["status"] == "missing"
    size_changed = disk_size != row["size_bytes"]
    mtime_changed = row["mtime"] is None or abs((disk_mtime - row["mtime"]).total_seconds()) >= 1

    if not was_missing and not size_changed and not mtime_changed:
        with conn.cursor() as cur:
            cur.execute("UPDATE files SET last_seen_at = now() WHERE id = %s", (row["id"],))
        return "unchanged"

    new_hash = sha256_file(container_path) if (size_changed or mtime_changed) else row["content_hash"]

    with conn.cursor() as cur:
        if new_hash != row["content_hash"]:
            # Real content change — geometry/thumbnail are now stale, and a
            # fresh render is needed. Deliberately does not re-run Phase 06's
            # relationship/folder-grouping heuristics (scope boundary — see
            # CLAUDE.md) so an in-place slicer re-save doesn't re-trigger
            # suggestion noise every rescan.
            cur.execute(
                f"""
                UPDATE files SET
                    content_hash = %s, size_bytes = %s, mtime = %s,
                    status = 'active', last_seen_at = now(), render_status = 'pending',
                    {_RESET_GEOMETRY}
                WHERE id = %s
                """,
                (new_hash, disk_size, disk_mtime, row["id"]),
            )
            ext = os.path.splitext(row["path"])[1].lower()
            ingest.maybe_enqueue_render(conn, row["id"], ext)
            return "rehashed"

        # Same content — either just a `touch`, or a revival with nothing
        # actually different about the bytes. Either way, no re-render needed.
        cur.execute(
            "UPDATE files SET size_bytes = %s, mtime = %s, status = 'active', last_seen_at = now() WHERE id = %s",
            (disk_size, disk_mtime, row["id"]),
        )
        return "revived" if was_missing else "touched"


def _find_move_source(container_path, active_by_hash, seen_paths):
    """A newly-discovered path with no DB row of its own — before treating
    it as genuinely new, check whether its content matches a still-active
    row from this same root that this pass hasn't found at its recorded
    path yet (a real move candidate). Only 'active' rows are candidates —
    a row already 'missing' from a *prior* rescan is presumed gone for
    real, not silently still-there-somewhere, so this doesn't resurrect
    arbitrarily old missing rows on a coincidental hash match. Returns
    None (and the caller falls through to normal new-file ingestion) if
    no such candidate exists — including the ordinary case where the hash
    doesn't match anything at all."""
    new_hash = sha256_file(container_path)
    for candidate in active_by_hash.get(new_hash, []):
        if candidate["path"] not in seen_paths:
            return candidate
    return None


def run_rescan(conn):
    roots = fetch_active_roots(conn)
    dropfolder_root = next((r for r in roots if r.kind == "drop_folder"), None)
    if dropfolder_root is None:
        raise RuntimeError("no active drop_folder root configured")

    for root in roots:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT id, path, size_bytes, content_hash, mtime, status FROM files WHERE watched_root_id = %s",
                (root.id,),
            )
            known_by_path = {r["path"]: r for r in cur.fetchall()}

            cur.execute(
                "SELECT id, path, status FROM sidecar_files WHERE watched_root_id = %s",
                (root.id,),
            )
            known_sidecars_by_path = {r["path"]: r for r in cur.fetchall()}

        active_by_hash = {}
        for row in known_by_path.values():
            if row["status"] == "active":
                active_by_hash.setdefault(row["content_hash"], []).append(row)

        seen_paths = set()
        seen_sidecar_paths = set()
        new_count = rehashed_count = revived_count = moved_count = 0
        # Materialized before any relocation happens — same reason as
        # backfill: moving a whole leaf folder mid-walk could otherwise
        # disrupt os.walk's still-in-progress traversal of that same tree.
        for dirpath, model_paths, sidecar_paths, zip_paths in list(_walk_project_folders(root.container_path)):
            for zip_path in zip_paths:
                try:
                    stage_zip_if_relevant(conn, root, zip_path)
                except Exception as exc:
                    print(f"[worker] rescan: skipping zip {zip_path} due to error: {exc}", flush=True)

            for container_path in model_paths:
                host_path = to_host_path(root, container_path)
                seen_paths.add(host_path)
                existing = known_by_path.get(host_path)
                try:
                    if existing is None:
                        moved_from = _find_move_source(container_path, active_by_hash, seen_paths)
                        if moved_from is not None:
                            ingest.repoint_file(conn, moved_from["id"], root, container_path)
                            seen_paths.add(moved_from["path"])
                            moved_count += 1
                            continue
                        if _ingest_new_path(conn, root, dropfolder_root, container_path):
                            new_count += 1
                        continue
                    outcome = _reconcile_known_file(conn, existing, container_path)
                    if outcome == "rehashed":
                        rehashed_count += 1
                    elif outcome == "revived":
                        revived_count += 1
                except Exception as exc:
                    # A single unreadable file (confirmed live: OSError
                    # [Errno 35] Resource deadlock avoided on a subset of
                    # files from a ~2800-file bulk move out of iCloud
                    # Drive) must never abort the rest of this pass — with
                    # no try/except here, one bad file early in the walk
                    # order silently blocked every other file's drift-check/
                    # rehash for that entire 5-minute cycle, every cycle,
                    # since run_rescan itself has no per-file recovery
                    # (only main()'s own try/except around the *whole*
                    # run_rescan call, which just skips the whole pass).
                    # Skipping here just means this file gets retried next
                    # pass, exactly like backfill's equivalent fix.
                    print(f"[worker] rescan: skipping {container_path} due to error: {exc}", flush=True)

            # See backfill.run_backfill for why relocate_to_dropfolder roots
            # skip sidecar staging here — their sidecars either already
            # moved with their folder or will be caught once that folder
            # shows up in the drop folder's own walk.
            if model_paths and root.ingest_mode != "relocate_to_dropfolder":
                for sidecar_path in sidecar_paths:
                    try:
                        host_sidecar_path = to_host_path(root, sidecar_path)
                        seen_sidecar_paths.add(host_sidecar_path)
                        existing_sidecar = known_sidecars_by_path.get(host_sidecar_path)
                        if existing_sidecar is not None and existing_sidecar["status"] == "missing":
                            with conn.cursor() as cur:
                                cur.execute(
                                    "UPDATE sidecar_files SET status = 'active' WHERE id = %s",
                                    (existing_sidecar["id"],),
                                )
                        else:
                            # already-known-and-active sidecars are a no-op
                            # here (ON CONFLICT DO NOTHING) — this only ever
                            # inserts a genuinely new one.
                            ingest.stage_sidecar(conn, root, sidecar_path)
                    except Exception as exc:
                        print(f"[worker] rescan: skipping sidecar {sidecar_path} due to error: {exc}", flush=True)

        missing_count = 0
        sidecar_missing_count = 0
        with conn.cursor() as cur:
            for path, row in known_by_path.items():
                if row["status"] == "active" and path not in seen_paths:
                    cur.execute("UPDATE files SET status = 'missing' WHERE id = %s", (row["id"],))
                    missing_count += 1
            for path, row in known_sidecars_by_path.items():
                if row["status"] == "active" and path not in seen_sidecar_paths:
                    cur.execute("UPDATE sidecar_files SET status = 'missing' WHERE id = %s", (row["id"],))
                    sidecar_missing_count += 1
            cur.execute("UPDATE watched_roots SET last_scanned_at = now() WHERE id = %s", (root.id,))

        print(
            f"[worker] rescan — {root.label}: {new_count} new, {rehashed_count} rehashed, "
            f"{revived_count} revived, {moved_count} moved, {missing_count} newly missing "
            f"({sidecar_missing_count} sidecar(s) newly missing)",
            flush=True,
        )
