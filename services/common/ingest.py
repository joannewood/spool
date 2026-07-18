import os
import shutil

from .config import MESH_EXTENSIONS, STEP_EXTENSIONS
from .hashing import sha256_file
from .paths import to_host_path


def stage_stub(conn, root, container_path):
    """Record a newly discovered index_in_place file with no hash yet, and
    enqueue an ingest job to hash it. Used by the live watcher, which stays
    lightweight and hands the actual hashing off to the worker.

    Returns the new file id, or None if this path was already known.
    """
    host_path = to_host_path(root, container_path)
    filename = os.path.basename(container_path)
    ext = os.path.splitext(filename)[1].lower()
    size_bytes = os.path.getsize(container_path)
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO files (watched_root_id, path, filename, ext, size_bytes, status)
                VALUES (%s, %s, %s, %s, %s, 'active')
                ON CONFLICT (path) DO NOTHING
                RETURNING id
                """,
                (root.id, host_path, filename, ext, size_bytes),
            )
            row = cur.fetchone()
            if row is None:
                return None
            file_id = row[0]
            cur.execute(
                "INSERT INTO jobs (file_id, job_type, status) VALUES (%s, 'ingest', 'queued')",
                (file_id,),
            )
    return file_id


def stage_and_hash(conn, root, container_path):
    """Record a file with its hash computed inline. Used by backfill, which
    already runs inside the worker — no point handing itself a job.

    Returns the new file id, or None if this path was already known.
    """
    host_path = to_host_path(root, container_path)
    filename = os.path.basename(container_path)
    ext = os.path.splitext(filename)[1].lower()
    size_bytes = os.path.getsize(container_path)
    content_hash = sha256_file(container_path)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO files (watched_root_id, path, filename, ext, size_bytes, content_hash, status)
            VALUES (%s, %s, %s, %s, %s, %s, 'active')
            ON CONFLICT (path) DO NOTHING
            RETURNING id
            """,
            (root.id, host_path, filename, ext, size_bytes, content_hash),
        )
        row = cur.fetchone()
    return row[0] if row else None


def maybe_enqueue_render(conn, file_id, ext):
    """Queue a render job for a renderable extension — 'render' for mesh
    formats, 'render_step' for CAD formats (its own queue lane, since CAD
    tessellation is much slower than reading a mesh file directly)."""
    ext = ext.lower()
    if ext in MESH_EXTENSIONS:
        job_type = "render"
    elif ext in STEP_EXTENSIONS:
        job_type = "render_step"
    else:
        return
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO jobs (file_id, job_type, status) VALUES (%s, %s, 'queued')",
            (file_id, job_type),
        )


def relocate(root, dropfolder_root, container_path):
    """Move a file from a relocate_to_dropfolder root into the drop folder.
    On a filename collision, the incoming file is renamed with a short hash
    suffix rather than overwriting whatever's already there.

    Returns the file's new container path.
    """
    filename = os.path.basename(container_path)
    dest = os.path.join(dropfolder_root.container_path, filename)
    if os.path.exists(dest):
        stem, ext = os.path.splitext(filename)
        suffix = sha256_file(container_path)[:6]
        filename = f"{stem} ({suffix}){ext}"
        dest = os.path.join(dropfolder_root.container_path, filename)
    shutil.move(container_path, dest)
    return dest
