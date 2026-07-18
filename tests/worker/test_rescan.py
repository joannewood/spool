import os
import time

from app.rescan import run_rescan


def _touch(path, content=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)
    return path


def _get_file(conn, filename):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, status, content_hash, size_bytes, mtime, render_status, thumbnail_path "
            "FROM files WHERE filename = %s",
            (filename,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    cols = ("id", "status", "content_hash", "size_bytes", "mtime", "render_status", "thumbnail_path")
    return dict(zip(cols, row))


def test_run_rescan_requires_a_dropfolder_root(conn, make_root):
    import pytest

    make_root(kind="existing_library")
    with pytest.raises(RuntimeError):
        run_rescan(conn)


def test_run_rescan_discovers_new_file(conn, make_root):
    make_root(kind="drop_folder")
    library = make_root(kind="existing_library")
    _touch(os.path.join(library.container_path, "widget.stl"), b"geometry")

    run_rescan(conn)

    row = _get_file(conn, "widget.stl")
    assert row is not None
    assert row["status"] == "active"
    assert row["content_hash"] is not None
    assert row["mtime"] is not None


def test_run_rescan_marks_removed_file_missing(conn, make_root):
    make_root(kind="drop_folder")
    library = make_root(kind="existing_library")
    path = _touch(os.path.join(library.container_path, "widget.stl"))
    run_rescan(conn)  # first pass: discover it

    os.remove(path)
    run_rescan(conn)  # second pass: notice it's gone

    row = _get_file(conn, "widget.stl")
    assert row["status"] == "missing"


def test_run_rescan_revives_missing_file_with_unchanged_content(conn, make_root):
    make_root(kind="drop_folder")
    library = make_root(kind="existing_library")
    path = _touch(os.path.join(library.container_path, "widget.stl"), b"geometry")
    run_rescan(conn)
    original_hash = _get_file(conn, "widget.stl")["content_hash"]

    os.remove(path)
    run_rescan(conn)
    assert _get_file(conn, "widget.stl")["status"] == "missing"

    _touch(path, b"geometry")  # same bytes, reappears at the same path
    run_rescan(conn)

    row = _get_file(conn, "widget.stl")
    assert row["status"] == "active"
    assert row["content_hash"] == original_hash


def test_run_rescan_rehashes_on_real_content_change(conn, make_root):
    make_root(kind="drop_folder")
    library = make_root(kind="existing_library")
    path = _touch(os.path.join(library.container_path, "widget.stl"), b"geometry-v1")
    run_rescan(conn)
    before = _get_file(conn, "widget.stl")

    # simulate a render having already completed, so we can prove it gets reset
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE files SET render_status = 'done', thumbnail_path = %s, bbox_x = 1, is_manifold = true WHERE id = %s",
            ("42.png", before["id"]),
        )

    time.sleep(1.1)  # comfortably clear the mtime fixture's 1-second threshold
    _touch(path, b"geometry-v2-different-content")
    run_rescan(conn)

    after = _get_file(conn, "widget.stl")
    assert after["content_hash"] != before["content_hash"]
    assert after["render_status"] == "pending"
    assert after["thumbnail_path"] is None

    with conn.cursor() as cur:
        cur.execute("SELECT bbox_x, is_manifold FROM files WHERE id = %s", (before["id"],))
        bbox_x, is_manifold = cur.fetchone()
    assert bbox_x is None
    assert is_manifold is None

    with conn.cursor() as cur:
        cur.execute("SELECT job_type FROM jobs WHERE file_id = %s", (before["id"],))
        job_types = [row[0] for row in cur.fetchall()]
    assert "render" in job_types  # fresh render was enqueued


def test_run_rescan_touch_only_does_not_trigger_rerender(conn, make_root):
    make_root(kind="drop_folder")
    library = make_root(kind="existing_library")
    path = _touch(os.path.join(library.container_path, "widget.stl"), b"geometry")
    run_rescan(conn)
    before = _get_file(conn, "widget.stl")

    with conn.cursor() as cur:
        cur.execute(
            "UPDATE files SET render_status = 'done', thumbnail_path = %s WHERE id = %s",
            ("42.png", before["id"]),
        )
        # one 'render' job already exists from the initial discovery above —
        # that's correct and expected; what we're checking is that the
        # touch-only rescan below doesn't add a second one
        cur.execute("SELECT count(*) FROM jobs WHERE file_id = %s AND job_type = 'render'", (before["id"],))
        render_jobs_before = cur.fetchone()[0]
    assert render_jobs_before == 1

    # bump mtime only, content identical
    future = time.time() + 5
    os.utime(path, (future, future))
    run_rescan(conn)

    after = _get_file(conn, "widget.stl")
    assert after["content_hash"] == before["content_hash"]
    assert after["render_status"] == "done"
    assert after["thumbnail_path"] == "42.png"

    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM jobs WHERE file_id = %s AND job_type = 'render'", (before["id"],))
        assert cur.fetchone()[0] == render_jobs_before  # no spurious re-render job


def test_run_rescan_updates_last_scanned_at(conn, make_root):
    dropfolder = make_root(kind="drop_folder")

    run_rescan(conn)

    with conn.cursor() as cur:
        cur.execute("SELECT last_scanned_at FROM watched_roots WHERE id = %s", (dropfolder.id,))
        assert cur.fetchone()[0] is not None
