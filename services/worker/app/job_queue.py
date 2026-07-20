"""Job-queue primitives (claim/mark-done/mark-failed/requeue-orphaned) —
pure Postgres mechanics with no rendering involved, deliberately kept
separate from main.py so importing this doesn't drag in render.py's
heavy deps (numpy/trimesh/pyrender) for anything that just wants to
touch the job queue (same lightweight-module precedent as
gcode_thumbnail.py/gcode_metadata.py/bambu_metadata.py).
"""
import os

# Which job_types this worker instance consumes — lets the slow STEP lane
# run in a separate container (worker-step) from the fast ingest/mesh lane
# (worker), so a backlog of CAD renders never blocks quick mesh renders.
JOB_TYPES = tuple(t.strip() for t in os.environ.get("JOB_TYPES", "ingest,render").split(","))


def requeue_orphaned_jobs(conn):
    """A job left in 'running' status at our own startup means the
    previous instance of this same lane died mid-job (crash/OOM-kill —
    see docker-compose.yml's restart: unless-stopped comment for why
    that happens at all) — this project runs exactly one process per
    job_type lane, no horizontal scaling, so a 'running' row matching
    JOB_TYPES right as we start up can only be orphaned, never actually
    in progress somewhere else. Reset it to 'queued' so the fresh
    (near-zero-memory) process retries it instead of it sitting stuck
    forever — confirmed live during a bulk import: two separate crashes
    each left exactly one file's render permanently stuck at 'running'
    until this existed."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE jobs SET status = 'queued' WHERE status = 'running' AND job_type = ANY(%s) RETURNING id, file_id, job_type",
            (list(JOB_TYPES),),
        )
        orphaned = cur.fetchall()
    for job_id, file_id, job_type in orphaned:
        print(
            f"[worker] requeued orphaned {job_type} job {job_id} (file {file_id}) — previous run likely crashed mid-job",
            flush=True,
        )


def claim_next_job(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE jobs SET status = 'running'
            WHERE id = (
                SELECT id FROM jobs
                WHERE status = 'queued' AND job_type = ANY(%s)
                ORDER BY created_at
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            RETURNING id, file_id, zip_file_id, job_type
            """,
            (list(JOB_TYPES),),
        )
        return cur.fetchone()


def mark_job_done(conn, job_id):
    with conn.cursor() as cur:
        cur.execute("UPDATE jobs SET status = 'done', completed_at = now() WHERE id = %s", (job_id,))


def mark_job_failed(conn, job_id, file_id, job_type, error):
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE jobs SET status = 'failed', error = %s, completed_at = now() WHERE id = %s",
            (error, job_id),
        )
        if job_type in ("render", "render_step"):
            cur.execute("UPDATE files SET render_status = 'failed' WHERE id = %s", (file_id,))
