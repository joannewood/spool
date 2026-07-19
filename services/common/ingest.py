import os
import shutil
from datetime import datetime, timezone

from .config import MESH_EXTENSIONS, SCAD_EXTENSIONS, SIDECAR_IMAGE_EXTENSIONS, STEP_EXTENSIONS, SVG_EXTENSIONS
from .hashing import sha256_file
from .paths import to_host_path

THUMBNAILS_DIR = os.environ.get("THUMBNAILS_DIR", "/data/thumbnails")


def repoint_file(conn, file_id, new_root, new_container_path):
    """Re-points an existing file row to a new location — a rename/move
    keeps the same DB row (and therefore all its tags/relationships/
    project membership/print_metadata, all keyed by file id, not path)
    instead of marking the old path missing and creating an unrelated new
    row for the new path. Content is unchanged by a pure move, so no
    re-hash/re-render is triggered — only path/filename/ext (and
    watched_root_id, in case a move somehow crosses roots) change.

    Deliberately does not re-run the folder-grouping/relationship
    heuristics on the file's new location, same reasoning as rescan's
    existing "don't re-suggest on a content change" rule — re-suggesting
    a project on every move would be exactly the kind of suggestion-noise
    that rule was written to avoid.
    """
    new_host_path = to_host_path(new_root, new_container_path)
    filename = os.path.basename(new_container_path)
    ext = os.path.splitext(filename)[1].lower()
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE files SET path = %s, filename = %s, ext = %s,
                             watched_root_id = %s, status = 'active', last_seen_at = now()
            WHERE id = %s
            """,
            (new_host_path, filename, ext, new_root.id, file_id),
        )


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
    mtime = datetime.fromtimestamp(os.path.getmtime(container_path), tz=timezone.utc)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO files (watched_root_id, path, filename, ext, size_bytes, content_hash, mtime, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'active')
            ON CONFLICT (path) DO NOTHING
            RETURNING id
            """,
            (root.id, host_path, filename, ext, size_bytes, content_hash, mtime),
        )
        row = cur.fetchone()
    return row[0] if row else None


def stage_sidecar(conn, root, container_path):
    """Records a non-model file that lives alongside model files in a
    project folder — no hash, no render job, just presence (filename/size)
    for that folder's project page "Files in this folder" list. An image
    sidecar (a kit's preview photo, etc.) gets a thumbnail the same
    lightweight way SVG model files do — a plain copy, no rasterization
    needed since it's already a raster image.

    Returns the new sidecar_files id, or None if this path was already known.
    """
    host_path = to_host_path(root, container_path)
    filename = os.path.basename(container_path)
    ext = os.path.splitext(filename)[1].lower()
    size_bytes = os.path.getsize(container_path)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO sidecar_files (watched_root_id, path, filename, ext, size_bytes)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (path) DO NOTHING
            RETURNING id
            """,
            (root.id, host_path, filename, ext, size_bytes),
        )
        row = cur.fetchone()
        if row is None:
            return None
        sidecar_id = row[0]

        if ext in SIDECAR_IMAGE_EXTENSIONS:
            os.makedirs(THUMBNAILS_DIR, exist_ok=True)
            thumbnail_filename = f"sidecar-{sidecar_id}{ext}"
            shutil.copyfile(container_path, os.path.join(THUMBNAILS_DIR, thumbnail_filename))
            cur.execute(
                "UPDATE sidecar_files SET thumbnail_path = %s WHERE id = %s",
                (thumbnail_filename, sidecar_id),
            )
    return sidecar_id


def maybe_enqueue_render(conn, file_id, ext):
    """Queue a render job for a renderable extension — 'render' for mesh
    formats (also handles SVG/SCAD, both fast/lightweight — see config.py),
    'render_step' for CAD formats (its own queue lane, since CAD
    tessellation is much slower than reading a mesh file directly)."""
    ext = ext.lower()
    if ext in MESH_EXTENSIONS or ext in SVG_EXTENSIONS or ext in SCAD_EXTENSIONS:
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


def _unique_path(dest):
    """Appends a numeric suffix (Widget -> Widget (2)) until dest doesn't
    collide with something already there — used for whole-folder relocates,
    where a content hash (the per-file collision strategy below) doesn't
    make sense for a directory."""
    if not os.path.exists(dest):
        return dest
    n = 2
    while True:
        candidate = f"{dest} ({n})"
        if not os.path.exists(candidate):
            return candidate
        n += 1


def _relocate_single_file(container_path, dropfolder_root):
    if not os.path.exists(container_path):
        return None  # a concurrent handler already dealt with this
    filename = os.path.basename(container_path)
    dest = os.path.join(dropfolder_root.container_path, filename)
    if os.path.exists(dest):
        stem, ext = os.path.splitext(filename)
        suffix = sha256_file(container_path)[:6]
        filename = f"{stem} ({suffix}){ext}"
        dest = os.path.join(dropfolder_root.container_path, filename)
    try:
        shutil.move(container_path, dest)
    except FileNotFoundError:
        return None
    return dest


def _relocate_whole_folder(parent_dir, container_path, dropfolder_root):
    folder_name = os.path.basename(parent_dir)
    dest_dir = _unique_path(os.path.join(dropfolder_root.container_path, folder_name))
    try:
        shutil.move(parent_dir, dest_dir)
    except FileNotFoundError:
        return None  # lost the race to a concurrent handler for a sibling file
    filename = os.path.basename(container_path)
    return os.path.join(dest_dir, filename)


def relocate(root, dropfolder_root, container_path):
    """Move a file from a relocate_to_dropfolder root into the drop folder.

    A file sitting directly in the watched root (no meaningful parent
    folder), or whose parent folder itself contains subdirectories
    (deliberate scope limit — nested multi-level kits don't get full
    structure preservation, consistent with the "flat per leaf folder" rule
    used everywhere else in the app), is relocated alone: on a filename
    collision, renamed with a short hash suffix rather than overwriting
    whatever's already there.

    Otherwise the file's parent is a leaf folder, and the WHOLE folder is
    moved as a unit instead — carrying sidecars along and preserving
    whatever grouping the folder arrived with. A same-named folder already
    at the destination gets a numeric suffix, never a silent merge. Model
    files and sidecars that land this way get discovered normally once
    they're sitting inside the (actively watched) drop folder.

    Returns the new container path of the originally-requested file, or
    None if a concurrent event (a sibling file in the same folder) already
    relocated it — there is nothing left for this call to do.
    """
    parent_dir = os.path.dirname(container_path)
    is_root_level = os.path.normpath(parent_dir) == os.path.normpath(root.container_path)

    if not is_root_level and os.path.isdir(parent_dir):
        has_subdirs = any(entry.is_dir() for entry in os.scandir(parent_dir))
        if not has_subdirs:
            return _relocate_whole_folder(parent_dir, container_path, dropfolder_root)

    return _relocate_single_file(container_path, dropfolder_root)
