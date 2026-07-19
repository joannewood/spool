import os
import time

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from common import ingest
from common.db import get_connection
from common.paths import is_ignorable_junk, is_model_file, is_zip_file, to_host_path
from common.roots import fetch_active_roots, fetch_dropfolder_root
from common.zip_ingest import stage_zip_if_relevant


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
        if is_ignorable_junk(path):
            return

        if is_zip_file(path):
            if not wait_until_stable(path):
                print(f"[watcher] gave up waiting for {path} to settle", flush=True)
                return
            with get_connection() as conn:
                zip_id = stage_zip_if_relevant(conn, self.root, path)
            if zip_id is not None:
                print(f"[watcher] found reviewable zip {zip_id}: {path}", flush=True)
            return

        if not is_model_file(path):
            return
        if not wait_until_stable(path):
            print(f"[watcher] gave up waiting for {path} to settle", flush=True)
            return

        if self.root.ingest_mode == "relocate_to_dropfolder":
            new_path = ingest.relocate(self.root, self.dropfolder_root, path)
            if new_path is None:
                # a sibling file's event already relocated the whole folder
                # this one lived in — nothing left for us to do
                return
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
        if event.is_directory:
            return
        # A real rename/move within this same watched tree — try to find
        # the tracked row for the OLD path and just repoint it, so tags/
        # relationships/project membership survive the move instead of
        # the old path going 'missing' and the new path becoming an
        # unrelated brand-new file. Not attempted for relocate_to_
        # dropfolder roots (Downloads) — files there are never meant to
        # stay tracked at their Downloads path anyway (relocate moves them
        # away immediately), so there's nothing meaningful to repoint;
        # falls through to the normal new-file handling below regardless
        # (harmless — a browser's .crdownload-style rename also falls
        # through here since the temp name was never tracked).
        if self.root.ingest_mode != "relocate_to_dropfolder" and is_model_file(event.src_path):
            host_src = to_host_path(self.root, event.src_path)
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT id FROM files WHERE path = %s AND status = 'active'", (host_src,))
                    row = cur.fetchone()
                if row is not None:
                    if not wait_until_stable(event.dest_path):
                        print(f"[watcher] gave up waiting for {event.dest_path} to settle", flush=True)
                        return
                    ingest.repoint_file(conn, row[0], self.root, event.dest_path)
                    print(f"[watcher] tracked move: file {row[0]} {event.src_path} -> {event.dest_path}", flush=True)
                    return
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
