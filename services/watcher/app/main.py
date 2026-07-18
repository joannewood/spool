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


ROOT_POLL_INTERVAL_SECONDS = 10


def sync_watches(observer, conn, scheduled):
    """Reconcile the observer's live watches against the current
    watched_roots table — add/remove/reschedule without a container
    restart. Only ever touches roots whose container_path is already
    bind-mounted (adding a brand-new root still needs one, since Docker
    can't attach a new bind mount to a running container)."""
    roots = fetch_active_roots(conn)
    dropfolder_root = fetch_dropfolder_root(conn)
    current_ids = {root.id for root in roots}

    for root in roots:
        existing = scheduled.get(root.id)
        if existing is not None:
            watch, snapshot = existing
            if snapshot.ingest_mode == root.ingest_mode and snapshot.container_path == root.container_path:
                continue  # nothing relevant changed, leave the watch alone
            observer.unschedule(watch)
            del scheduled[root.id]
            print(f"[watcher] re-scheduling {root.label} (settings changed)", flush=True)

        if not os.path.isdir(root.container_path):
            print(f"[watcher] skipping {root.label}: {root.container_path} isn't mounted "
                  f"(new roots need docker compose up -d --build to attach the bind mount)", flush=True)
            continue

        handler = RootEventHandler(root, dropfolder_root)
        watch = observer.schedule(handler, root.container_path, recursive=True)
        scheduled[root.id] = (watch, root)
        print(f"[watcher] watching {root.label} at {root.container_path} (ingest_mode={root.ingest_mode})", flush=True)

    for root_id in list(scheduled):
        if root_id not in current_ids:
            watch, snapshot = scheduled.pop(root_id)
            observer.unschedule(watch)
            print(f"[watcher] stopped watching {snapshot.label} (paused or deactivated)", flush=True)

    return scheduled


def main():
    observer = Observer()
    observer.start()

    scheduled = {}
    with get_connection() as conn:
        scheduled = sync_watches(observer, conn, scheduled)
    print("[watcher] ready", flush=True)

    try:
        while True:
            time.sleep(ROOT_POLL_INTERVAL_SECONDS)
            with get_connection() as conn:
                scheduled = sync_watches(observer, conn, scheduled)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == "__main__":
    main()
