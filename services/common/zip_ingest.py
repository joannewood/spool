import os
import zipfile

from .config import MODEL_EXTENSIONS
from .hashing import sha256_file
from .paths import to_host_path


def zip_contains_model_files(container_path):
    """Peeks the zip's central directory (fast — no decompression) to
    decide if it's worth surfacing for review at all."""
    try:
        with zipfile.ZipFile(container_path) as zf:
            return any(os.path.splitext(n)[1].lower() in MODEL_EXTENSIONS for n in zf.namelist())
    except zipfile.BadZipFile:
        return False


def stage_zip_if_relevant(conn, root, container_path):
    """Records a .zip for review only if it contains at least one
    recognized model file. A zip with no model content inside is never
    inserted — never tracked, never asked about, left completely alone.

    Uniqueness is on (path, content_hash), not path alone — a rejected
    zip only stays rejected for that exact content. A common filename
    like "Archive.zip" gets reused for genuinely different downloads over
    time (old one deleted, new one dropped in with the same name); hashing
    only happens here, after the cheap namelist-peek already confirmed the
    zip is worth tracking at all, so an irrelevant zip never pays this cost.

    Returns the new zip_files id, or None if not relevant or already known.
    """
    if not zip_contains_model_files(container_path):
        return None

    host_path = to_host_path(root, container_path)
    filename = os.path.basename(container_path)
    size_bytes = os.path.getsize(container_path)
    content_hash = sha256_file(container_path)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO zip_files (watched_root_id, path, filename, size_bytes, content_hash, status)
            VALUES (%s, %s, %s, %s, %s, 'suggested')
            ON CONFLICT (path, content_hash) DO NOTHING
            RETURNING id
            """,
            (root.id, host_path, filename, size_bytes, content_hash),
        )
        row = cur.fetchone()
    return row[0] if row else None
