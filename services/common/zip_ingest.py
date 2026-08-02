import os
import zipfile

import py7zr
import rarfile

from .config import MODEL_EXTENSIONS
from .hashing import sha256_file
from .paths import to_host_path
from .settings import get_app_settings


def _archive_namelist(container_path):
    """.7z and .rar have no central-directory equivalent as cheap as
    zipfile's, but both py7zr's and rarfile's header-only parsing are
    still just metadata — no member is decompressed, matching the same
    "peek, don't extract" cost as the zipfile branch. .rar in particular
    never needs the external unpacking tool (bsdtar) for this — rarfile
    parses RAR's own header format in pure Python; the external tool is
    only ever invoked for actual extraction, see zip_extract.py."""
    ext = os.path.splitext(container_path)[1].lower()
    if ext == ".7z":
        with py7zr.SevenZipFile(container_path, mode="r") as zf:
            return zf.getnames()
    if ext == ".rar":
        with rarfile.RarFile(container_path) as rf:
            return rf.namelist()
    with zipfile.ZipFile(container_path) as zf:
        return zf.namelist()


def zip_contains_model_files(container_path):
    """Peeks the archive's directory listing (fast — no decompression) to
    decide if it's worth surfacing for review at all. Handles .zip, .7z,
    and .rar — see _archive_namelist."""
    try:
        names = _archive_namelist(container_path)
    except (zipfile.BadZipFile, py7zr.exceptions.Bad7zFile, rarfile.Error):
        return False
    return any(os.path.splitext(n)[1].lower() in MODEL_EXTENSIONS for n in names)


def stage_zip_if_relevant(conn, root, container_path):
    """Records a .zip, .7z, or .rar for review only if it contains at least one
    recognized model file. An archive with no model content inside is
    never inserted — never tracked, never asked about, left completely
    alone. The zip_files table/naming predates .7z support and stays as
    it is (the extraction/admin-review code that follows genuinely
    doesn't care which archive format it's looking at), rather than
    renaming a table and a job_type enum value for a cosmetic-only
    consistency win.

    Uniqueness is on (path, content_hash), not path alone — a rejected
    archive only stays rejected for that exact content. A common filename
    like "Archive.zip" gets reused for genuinely different downloads over
    time (old one deleted, new one dropped in with the same name); hashing
    only happens here, after the cheap namelist-peek already confirmed the
    archive is worth tracking at all, so an irrelevant one never pays this
    cost.

    If app_settings.auto_accept_archives is on, a newly-discovered archive
    is inserted already 'confirmed' with its extract_zip job enqueued
    immediately — the same end state a human clicking Confirm on
    /admin/pending-archives produces, just skipping the review step for
    people who'd rather SPOOL just extract anything relevant on sight.
    Deliberately checked fresh on every call (not cached) so flipping the
    setting takes effect for the very next archive found, and deliberately
    only affects *new* rows — ON CONFLICT DO NOTHING means an archive
    already sitting at 'suggested' or 'rejected' from before the setting
    was turned on is never silently reclassified out from under a review
    that might already be in progress.

    Returns the new zip_files id, or None if not relevant or already known.
    """
    if not zip_contains_model_files(container_path):
        return None

    host_path = to_host_path(root, container_path)
    filename = os.path.basename(container_path)
    size_bytes = os.path.getsize(container_path)
    content_hash = sha256_file(container_path)
    auto_accept = get_app_settings(conn)["auto_accept_archives"]
    status = "confirmed" if auto_accept else "suggested"
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO zip_files (watched_root_id, path, filename, size_bytes, content_hash, status)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (path, content_hash) DO NOTHING
            RETURNING id
            """,
            (root.id, host_path, filename, size_bytes, content_hash, status),
        )
        row = cur.fetchone()
        zip_id = row[0] if row else None
        if zip_id and auto_accept:
            cur.execute(
                "INSERT INTO jobs (zip_file_id, job_type, status) VALUES (%s, 'extract_zip', 'queued')",
                (zip_id,),
            )
    return zip_id
