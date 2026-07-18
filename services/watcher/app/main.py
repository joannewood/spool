import os
import time

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from common import ingest
from common.db import get_connection
from common.paths import is_model_file
from common.roots import fetch_active_roots, fetch_dropfolder_root


def wait_until_stable(path, checks=3, interval=0.4, timeout=30):
    """A download or copy in progress keeps growing; only act once the file
    size has held steady for a few checks in a row, so we never hash a
    partial file."""
    last_size = -1
    stable_count = 0
    elapsed = 0.0
    while elapsed < timeout:
        try:
            size = os.path.getsize(path)
        except FileNotFoundError:
            return False
        if size == last_size:
            stable_count += 1
            if stable_count >= checks:
                return True
        else:
            stable_count = 0
        last_size = size
        time.sleep(interval)
        elapsed += interval
    return False


class RootEventHandler(FileSystemEventHandler):
    def __init__(self, root, dropfolder_root):
        self.root = root
        self.dropfolder_root = dropfolder_root

    def _handle(self, path):
        if not is_model_file(path):
            return
        if not wait_until_stable(path):
            print(f"[watcher] gave up waiting for {path} to settle", flush=True)
            return

        if self.root.ingest_mode == "relocate_to_dropfolder":
            new_path = ingest.relocate(self.root, self.dropfolder_root, path)
            print(f"[watcher] relocated {path} -> {new_path}", flush=True)
            # landing in the drop folder fires its own create event, which
            # that root's watch picks up and ingests normally.
        else:
            with get_connection() as conn:
                file_id = ingest.stage_stub(conn, self.root, path)
            if file_id is not None:
                print(f"[watcher] staged file {file_id}: {path}", flush=True)

    def on_created(self, event):
        if not event.is_directory:
            self._handle(event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            self._handle(event.dest_path)


def main():
    conn = get_connection()
    roots = fetch_active_roots(conn)
    dropfolder_root = fetch_dropfolder_root(conn)
    conn.close()

    observer = Observer()
    for root in roots:
        handler = RootEventHandler(root, dropfolder_root)
        observer.schedule(handler, root.container_path, recursive=True)
        print(f"[watcher] watching {root.label} at {root.container_path}", flush=True)

    observer.start()
    print("[watcher] ready", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == "__main__":
    main()
