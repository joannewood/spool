import os
import shutil
import zipfile

from common.ingest import _unique_path
from common.paths import to_container_path
from common.roots import fetch_dropfolder_root, fetch_root_by_id


def _is_safe_zip(zf):
    """Guards against zip-slip (a malicious entry like '../../etc/passwd'
    escaping the extraction directory) before we ever call extractall."""
    for name in zf.namelist():
        if os.path.isabs(name) or ".." in os.path.normpath(name).split(os.sep):
            return False
    return True


def process_extract_zip_job(conn, zip_file_id):
    with conn.cursor() as cur:
        cur.execute("SELECT path, watched_root_id, filename FROM zip_files WHERE id = %s", (zip_file_id,))
        row = cur.fetchone()
    if row is None:
        return
    host_path, watched_root_id, filename = row

    try:
        root = fetch_root_by_id(conn, watched_root_id)
        container_path = to_container_path(root, host_path)

        stem = os.path.splitext(filename)[0]
        extract_dir = _unique_path(os.path.join(os.path.dirname(container_path), stem))

        with zipfile.ZipFile(container_path) as zf:
            if not _is_safe_zip(zf):
                raise ValueError("zip contains unsafe paths (zip-slip), refusing to extract")
            os.makedirs(extract_dir)
            zf.extractall(extract_dir)

        os.remove(container_path)

        # Same "carry the whole folder into the drop folder" behavior as
        # ingest.relocate's whole-folder path — the extracted folder just
        # got created above, so there's no per-file flatten case to worry
        # about here, only the collision-suffix rename.
        if root.ingest_mode == "relocate_to_dropfolder":
            dropfolder_root = fetch_dropfolder_root(conn)
            dest = _unique_path(os.path.join(dropfolder_root.container_path, os.path.basename(extract_dir)))
            shutil.move(extract_dir, dest)

    except Exception as exc:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE zip_files SET status = 'suggested', error = %s WHERE id = %s",
                (str(exc), zip_file_id),
            )
        return

    with conn.cursor() as cur:
        cur.execute("DELETE FROM zip_files WHERE id = %s", (zip_file_id,))
