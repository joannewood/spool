import os
from datetime import datetime, timezone

from psycopg.rows import dict_row

from common import ingest
from common.hashing import sha256_file
from common.paths import to_host_path
from common.roots import fetch_active_roots
from common.zip_ingest import stage_zip_if_relevant

from .backfill import _ingest_new_path, _walk_project_folders

RESCAN_INTERVAL_SECONDS = int(os.environ.get("RESCAN_INTERVAL_SECONDS", "300"))

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

        seen_paths = set()
        new_count = rehashed_count = revived_count = 0
        # Materialized before any relocation happens — same reason as
        # backfill: moving a whole leaf folder mid-walk could otherwise
        # disrupt os.walk's still-in-progress traversal of that same tree.
        for dirpath, model_paths, sidecar_paths, zip_paths in list(_walk_project_folders(root.container_path)):
            for zip_path in zip_paths:
                stage_zip_if_relevant(conn, root, zip_path)

            for container_path in model_paths:
                host_path = to_host_path(root, container_path)
                seen_paths.add(host_path)
                existing = known_by_path.get(host_path)
                if existing is None:
                    if _ingest_new_path(conn, root, dropfolder_root, container_path):
                        new_count += 1
                    continue
                outcome = _reconcile_known_file(conn, existing, container_path)
                if outcome == "rehashed":
                    rehashed_count += 1
                elif outcome == "revived":
                    revived_count += 1

            # See backfill.run_backfill for why relocate_to_dropfolder roots
            # skip sidecar staging here — their sidecars either already
            # moved with their folder or will be caught once that folder
            # shows up in the drop folder's own walk.
            if model_paths and root.ingest_mode != "relocate_to_dropfolder":
                for sidecar_path in sidecar_paths:
                    ingest.stage_sidecar(conn, root, sidecar_path)

        missing_count = 0
        with conn.cursor() as cur:
            for path, row in known_by_path.items():
                if row["status"] == "active" and path not in seen_paths:
                    cur.execute("UPDATE files SET status = 'missing' WHERE id = %s", (row["id"],))
                    missing_count += 1
            cur.execute("UPDATE watched_roots SET last_scanned_at = now() WHERE id = %s", (root.id,))

        print(
            f"[worker] rescan — {root.label}: {new_count} new, {rehashed_count} rehashed, "
            f"{revived_count} revived, {missing_count} newly missing",
            flush=True,
        )
