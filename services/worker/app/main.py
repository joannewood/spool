import os
import time

from common.db import get_connection
from common.hashing import sha256_file
from common.paths import to_container_path
from common.roots import fetch_root_by_id

from .backfill import run_backfill

POLL_INTERVAL_SECONDS = 1.0


def claim_next_ingest_job(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE jobs SET status = 'running'
            WHERE id = (
                SELECT id FROM jobs
                WHERE status = 'queued' AND job_type = 'ingest'
                ORDER BY created_at
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            RETURNING id, file_id
            """
        )
        return cur.fetchone()


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

    with conn.cursor() as cur:
        cur.execute(
            "UPDATE files SET content_hash = %s, size_bytes = %s, last_seen_at = now() WHERE id = %s",
            (content_hash, size_bytes, file_id),
        )


def mark_job_done(conn, job_id):
    with conn.cursor() as cur:
        cur.execute("UPDATE jobs SET status = 'done', completed_at = now() WHERE id = %s", (job_id,))


def mark_job_failed(conn, job_id, error):
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE jobs SET status = 'failed', error = %s, completed_at = now() WHERE id = %s",
            (error, job_id),
        )


def main():
    conn = get_connection()

    print("[worker] running backfill...", flush=True)
    run_backfill(conn)
    print("[worker] backfill complete, entering job loop", flush=True)

    while True:
        job = claim_next_ingest_job(conn)
        if job is None:
            time.sleep(POLL_INTERVAL_SECONDS)
            continue
        job_id, file_id = job
        try:
            process_ingest_job(conn, file_id)
            mark_job_done(conn, job_id)
            print(f"[worker] ingested file {file_id}", flush=True)
        except Exception as exc:
            mark_job_failed(conn, job_id, str(exc))
            print(f"[worker] job {job_id} failed: {exc}", flush=True)


if __name__ == "__main__":
    main()
