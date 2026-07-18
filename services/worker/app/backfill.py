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
                new_path = ingest.relocate(root, dropfolder_root, container_path)
                if ingest.stage_and_hash(conn, dropfolder_root, new_path) is not None:
                    new_count += 1
            else:
                if ingest.stage_and_hash(conn, root, container_path) is not None:
                    new_count += 1
        print(f"[worker] backfill — {root.label}: {new_count} new file(s)", flush=True)
