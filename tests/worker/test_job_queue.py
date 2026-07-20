from app.job_queue import JOB_TYPES, requeue_orphaned_jobs


def _make_file(conn, root, filename="widget.stl"):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO files (watched_root_id, path, filename, ext, size_bytes, content_hash)
            VALUES (%s, %s, %s, '.stl', 100, %s)
            RETURNING id
            """,
            (root.id, f"{root.container_path}/{filename}", filename, f"hash-{filename}"),
        )
        return cur.fetchone()[0]


def _insert_job(conn, file_id, job_type, status):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO jobs (file_id, job_type, status) VALUES (%s, %s, %s) RETURNING id",
            (file_id, job_type, status),
        )
        return cur.fetchone()[0]


def _status_of(conn, job_id):
    with conn.cursor() as cur:
        cur.execute("SELECT status FROM jobs WHERE id = %s", (job_id,))
        return cur.fetchone()[0]


def test_requeue_orphaned_jobs_resets_running_jobs_in_our_own_lanes(conn, make_root):
    # A 'running' job at our own startup can only be orphaned (crashed
    # mid-job) — this project runs exactly one process per job_type lane,
    # never two workers racing on the same lane.
    root = make_root()
    file_id = _make_file(conn, root)
    own_job_type = JOB_TYPES[0]
    job_id = _insert_job(conn, file_id, own_job_type, "running")

    requeue_orphaned_jobs(conn)

    assert _status_of(conn, job_id) == "queued"


def test_requeue_orphaned_jobs_leaves_other_lanes_alone(conn, make_root):
    # A 'running' job belonging to a *different* job_type (e.g. this
    # instance is the fast lane, the job is render_step) might genuinely
    # still be in progress in the other lane's own process — must not
    # touch it.
    root = make_root()
    file_id = _make_file(conn, root)
    other_job_type = "render_step"
    assert other_job_type not in JOB_TYPES
    job_id = _insert_job(conn, file_id, other_job_type, "running")

    requeue_orphaned_jobs(conn)

    assert _status_of(conn, job_id) == "running"


def test_requeue_orphaned_jobs_leaves_queued_and_done_jobs_alone(conn, make_root):
    root = make_root()
    file_id = _make_file(conn, root)
    own_job_type = JOB_TYPES[0]
    queued_id = _insert_job(conn, file_id, own_job_type, "queued")
    done_id = _insert_job(conn, file_id, own_job_type, "done")

    requeue_orphaned_jobs(conn)

    assert _status_of(conn, queued_id) == "queued"
    assert _status_of(conn, done_id) == "done"
