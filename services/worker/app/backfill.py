import os

from common import ingest
from common.paths import is_model_file
from common.roots import fetch_active_roots


def _walk_matching(container_root_path):
    for dirpath, _dirnames, filenames in os.walk(container_root_path):
        for name in filenames:
            path = os.path.join(dirpath, name)
            if is_model_file(path):
                yield path


def run_backfill(conn):
    roots = fetch_active_roots(conn)
    dropfolder_root = next((r for r in roots if r.kind == "drop_folder"), None)
    if dropfolder_root is None:
        raise RuntimeError("no active drop_folder root configured")

    for root in roots:
        new_count = 0
        for container_path in _walk_matching(root.container_path):
            if root.ingest_mode == "relocate_to_dropfolder":
                target_root = dropfolder_root
                target_path = ingest.relocate(root, dropfolder_root, container_path)
            else:
                target_root = root
                target_path = container_path

            file_id = ingest.stage_and_hash(conn, target_root, target_path)
            if file_id is not None:
                new_count += 1
                ext = os.path.splitext(target_path)[1].lower()
                ingest.maybe_enqueue_render(conn, file_id, ext)
        print(f"[worker] backfill — {root.label}: {new_count} new file(s)", flush=True)
