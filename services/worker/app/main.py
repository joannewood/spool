import os
import resource
import time
from datetime import datetime, timezone

from common import ingest
from common.config import GCODE_EXTENSIONS, SCAD_EXTENSIONS, SVG_EXTENSIONS
from common.db import get_connection
from common.hashing import sha256_file
from common.paths import to_container_path
from common.roots import fetch_root_by_id

from .backfill import run_backfill
from .bambu_metadata import extract_bambu_metadata, upsert_extracted_metadata
from .gcode_metadata import extract_gcode_metadata
from .gcode_thumbnail import extract_gcode_thumbnail
from .job_queue import JOB_TYPES, claim_next_job, mark_job_done, mark_job_failed, requeue_orphaned_jobs
from .relationship_suggest import suggest_folder_project, suggest_for_file
from .render import render_svg_thumbnail, render_thumbnail
from .rescan import RESCAN_INTERVAL_SECONDS, run_rescan
from .zip_extract import process_extract_zip_job

POLL_INTERVAL_SECONDS = 1.0

RUN_BACKFILL = os.environ.get("RUN_BACKFILL", "true").lower() == "true"

# pyrender's OffscreenRenderer (EGL/llvmpipe software rendering) grows this
# process's memory over many render calls — confirmed live during a bulk
# import: fine for hours under normal trickle-load, but a large backlog
# processed back-to-back gives the OS no gap to reclaim anything between
# jobs, and this process got OOM-killed within minutes under that load
# (twice). Rather than wait for the kernel to kill us mid-job (losing that
# job to requeue_orphaned_jobs's recovery instead of finishing cleanly),
# self-exit once our own peak RSS crosses a safe threshold — `restart:
# unless-stopped` (docker-compose.yml) brings up a fresh, near-zero-memory
# process immediately. ru_maxrss is the process's all-time peak, in KB on
# Linux (this always runs in a Linux container) — checked after every
# completed job, never mid-job.
MAX_RSS_KB = int(os.environ.get("MAX_RSS_KB", 1_500_000))  # ~1.5GB


def process_ingest_job(conn, file_id):
    with conn.cursor() as cur:
        cur.execute("SELECT path, watched_root_id FROM files WHERE id = %s", (file_id,))
        row = cur.fetchone()
    if row is None:
        raise RuntimeError(f"file {file_id} not found")
    host_path, watched_root_id = row

    root = fetch_root_by_id(conn, watched_root_id)
    container_path = to_container_path(root, host_path)
    content_hash = sha256_file(container_path)
    size_bytes = os.path.getsize(container_path)
    mtime = datetime.fromtimestamp(os.path.getmtime(container_path), tz=timezone.utc)
    ext = os.path.splitext(host_path)[1].lower()

    with conn.cursor() as cur:
        cur.execute(
            "UPDATE files SET content_hash = %s, size_bytes = %s, mtime = %s, last_seen_at = now() WHERE id = %s",
            (content_hash, size_bytes, mtime, file_id),
        )
    filename = os.path.basename(host_path)
    suggest_for_file(conn, file_id, filename, ext)
    suggest_folder_project(conn, file_id, host_path, root)
    ingest.maybe_enqueue_render(conn, file_id, ext)


def process_render_job(conn, file_id):
    with conn.cursor() as cur:
        cur.execute("SELECT path, watched_root_id FROM files WHERE id = %s", (file_id,))
        row = cur.fetchone()
    if row is None:
        raise RuntimeError(f"file {file_id} not found")
    host_path, watched_root_id = row

    root = fetch_root_by_id(conn, watched_root_id)
    container_path = to_container_path(root, host_path)
    ext = os.path.splitext(container_path)[1].lower()

    if ext in SVG_EXTENSIONS:
        thumbnail_filename = render_svg_thumbnail(container_path, file_id)
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE files SET thumbnail_path = %s, render_status = 'done' WHERE id = %s",
                (thumbnail_filename, file_id),
            )
        return

    if ext in SCAD_EXTENSIONS:
        # Deliberately no preview — see config.py's SCAD_EXTENSIONS comment.
        with conn.cursor() as cur:
            cur.execute("UPDATE files SET render_status = 'done' WHERE id = %s", (file_id,))
        return

    if ext in GCODE_EXTENSIONS:
        # No mesh geometry to render — just pull out the slicer's own
        # embedded preview PNG, if it wrote one (see gcode_thumbnail.py).
        thumbnail_filename = extract_gcode_thumbnail(container_path, file_id)
        with conn.cursor() as cur:
            if thumbnail_filename:
                cur.execute(
                    "UPDATE files SET thumbnail_path = %s, render_status = 'done' WHERE id = %s",
                    (thumbnail_filename, file_id),
                )
            else:
                cur.execute("UPDATE files SET render_status = 'done' WHERE id = %s", (file_id,))
        gcode_metadata = extract_gcode_metadata(container_path)
        if gcode_metadata is not None:
            upsert_extracted_metadata(conn, file_id, gcode_metadata, source="auto_extracted_gcode")
        return

    thumbnail_filename, mesh = render_thumbnail(container_path, file_id)

    is_manifold = bool(mesh.is_watertight)
    volume_mm3 = float(mesh.volume) if is_manifold else None
    extents = mesh.bounds[1] - mesh.bounds[0]

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE files SET
                thumbnail_path = %s,
                render_status = 'done',
                is_manifold = %s,
                volume_mm3 = %s,
                tri_count = %s,
                bbox_x = %s, bbox_y = %s, bbox_z = %s,
                units = 'mm'
            WHERE id = %s
            """,
            (
                thumbnail_filename,
                is_manifold,
                volume_mm3,
                len(mesh.faces),
                float(extents[0]),
                float(extents[1]),
                float(extents[2]),
                file_id,
            ),
        )

    if os.path.splitext(container_path)[1].lower() == ".3mf":
        bambu_metadata = extract_bambu_metadata(container_path)
        if bambu_metadata is not None:
            upsert_extracted_metadata(conn, file_id, bambu_metadata)


def main():
    conn = get_connection()
    print(f"[worker] consuming job types: {JOB_TYPES}", flush=True)
    requeue_orphaned_jobs(conn)

    if RUN_BACKFILL:
        print("[worker] running backfill...", flush=True)
        run_backfill(conn)
        print("[worker] backfill complete, entering job loop", flush=True)
    else:
        print("[worker] backfill skipped (RUN_BACKFILL=false), entering job loop", flush=True)

    # Periodic rescan owns the same "keep the index in sync with disk"
    # responsibility as backfill, so it's gated on the same flag — only the
    # fast lane (worker) runs it, not worker-step, so the two lanes never
    # double-hash/race on the same files.
    next_rescan_at = time.monotonic() + RESCAN_INTERVAL_SECONDS if RUN_BACKFILL else None

    while True:
        if next_rescan_at is not None and time.monotonic() >= next_rescan_at:
            try:
                print("[worker] running periodic rescan...", flush=True)
                run_rescan(conn)
            except Exception as exc:
                print(f"[worker] rescan failed: {exc}", flush=True)
            next_rescan_at = time.monotonic() + RESCAN_INTERVAL_SECONDS

        job = claim_next_job(conn)
        if job is None:
            time.sleep(POLL_INTERVAL_SECONDS)
            continue
        job_id, file_id, zip_file_id, job_type = job
        try:
            if job_type == "ingest":
                process_ingest_job(conn, file_id)
            elif job_type in ("render", "render_step"):
                process_render_job(conn, file_id)
            elif job_type == "extract_zip":
                process_extract_zip_job(conn, zip_file_id)
            mark_job_done(conn, job_id)
            print(f"[worker] {job_type} done for file {file_id}", flush=True)
        except Exception as exc:
            mark_job_failed(conn, job_id, file_id, job_type, str(exc))
            print(f"[worker] {job_type} job {job_id} (file {file_id}) failed: {exc}", flush=True)

        rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if rss_kb > MAX_RSS_KB:
            print(
                f"[worker] peak memory {rss_kb}KB exceeds MAX_RSS_KB={MAX_RSS_KB} — "
                "exiting cleanly for a fresh restart rather than waiting for an OOM kill",
                flush=True,
            )
            return


if __name__ == "__main__":
    main()
