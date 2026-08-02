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

    make_root(kind="library")
    with pytest.raises(RuntimeError):
        run_rescan(conn)


def test_run_rescan_discovers_new_file(conn, make_root):
    make_root(kind="drop_folder")
    library = make_root(kind="library")
    _touch(os.path.join(library.container_path, "widget.stl"), b"geometry")

    run_rescan(conn)

    row = _get_file(conn, "widget.stl")
    assert row is not None
    assert row["status"] == "active"
    assert row["content_hash"] is not None
    assert row["mtime"] is not None


def test_run_rescan_marks_removed_file_missing(conn, make_root):
    make_root(kind="drop_folder")
    library = make_root(kind="library")
    path = _touch(os.path.join(library.container_path, "widget.stl"))
    run_rescan(conn)  # first pass: discover it

    os.remove(path)
    run_rescan(conn)  # second pass: notice it's gone

    row = _get_file(conn, "widget.stl")
    assert row["status"] == "missing"


def test_run_rescan_revives_missing_file_with_unchanged_content(conn, make_root):
    make_root(kind="drop_folder")
    library = make_root(kind="library")
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
    library = make_root(kind="library")
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
    library = make_root(kind="library")
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


def test_run_rescan_detects_moved_file_and_preserves_relationships(conn, make_root):
    make_root(kind="drop_folder")
    library = make_root(kind="library")
    path = _touch(os.path.join(library.container_path, "widget.stl"), b"geometry")
    run_rescan(conn)
    before = _get_file(conn, "widget.stl")

    with conn.cursor() as cur:
        cur.execute("INSERT INTO tags (name) VALUES ('kept') RETURNING id")
        tag_id = cur.fetchone()[0]
        cur.execute("INSERT INTO file_tags (file_id, tag_id) VALUES (%s, %s)", (before["id"], tag_id))

    new_path = os.path.join(library.container_path, "renamed_subfolder", "widget-renamed.stl")
    os.makedirs(os.path.dirname(new_path))
    os.rename(path, new_path)
    run_rescan(conn)

    # the old filename is gone, no longer resolvable by that name
    assert _get_file(conn, "widget.stl") is None

    with conn.cursor() as cur:
        cur.execute("SELECT id, path, status, content_hash FROM files WHERE filename = %s", ("widget-renamed.stl",))
        row = cur.fetchone()
    assert row is not None
    file_id, new_db_path, status, content_hash = row
    assert file_id == before["id"]  # same row, not a new one
    assert new_db_path == new_path
    assert status == "active"
    assert content_hash == before["content_hash"]  # unchanged content, no re-hash needed

    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM files WHERE watched_root_id = %s", (library.id,))
        assert cur.fetchone()[0] == 1  # no duplicate row left behind
        cur.execute("SELECT count(*) FROM file_tags WHERE file_id = %s AND tag_id = %s", (file_id, tag_id))
        assert cur.fetchone()[0] == 1  # tag survived the move


def test_run_rescan_does_not_treat_a_missing_files_old_hash_as_a_move_source(conn, make_root):
    # A file already marked 'missing' by a *prior* rescan is presumed
    # really gone — a brand new file that happens to share its content
    # (e.g. re-downloading the exact same model) should get its own new
    # row, not silently resurrect the old one at the new path.
    make_root(kind="drop_folder")
    library = make_root(kind="library")
    path = _touch(os.path.join(library.container_path, "widget.stl"), b"geometry")
    run_rescan(conn)
    before = _get_file(conn, "widget.stl")

    os.remove(path)
    run_rescan(conn)
    assert _get_file(conn, "widget.stl")["status"] == "missing"

    _touch(os.path.join(library.container_path, "widget-again.stl"), b"geometry")
    run_rescan(conn)

    again = _get_file(conn, "widget-again.stl")
    assert again is not None
    assert again["id"] != before["id"]  # a genuinely new row, not a repoint
    assert _get_file(conn, "widget.stl")["status"] == "missing"  # old row still missing


def _get_sidecar(conn, filename):
    with conn.cursor() as cur:
        cur.execute("SELECT id, status FROM sidecar_files WHERE filename = %s", (filename,))
        row = cur.fetchone()
    return None if row is None else {"id": row[0], "status": row[1]}


def test_run_rescan_marks_removed_sidecar_missing(conn, make_root):
    make_root(kind="drop_folder")
    library = make_root(kind="library")
    folder = os.path.join(library.container_path, "Kit")
    _touch(os.path.join(folder, "widget.stl"))
    sidecar_path = _touch(os.path.join(folder, "README.txt"))
    run_rescan(conn)
    assert _get_sidecar(conn, "README.txt")["status"] == "active"

    os.remove(sidecar_path)
    run_rescan(conn)

    assert _get_sidecar(conn, "README.txt")["status"] == "missing"


def test_run_rescan_revives_missing_sidecar_that_reappears(conn, make_root):
    make_root(kind="drop_folder")
    library = make_root(kind="library")
    folder = os.path.join(library.container_path, "Kit")
    _touch(os.path.join(folder, "widget.stl"))
    sidecar_path = _touch(os.path.join(folder, "README.txt"))
    run_rescan(conn)
    before_id = _get_sidecar(conn, "README.txt")["id"]

    os.remove(sidecar_path)
    run_rescan(conn)
    assert _get_sidecar(conn, "README.txt")["status"] == "missing"

    _touch(sidecar_path)
    run_rescan(conn)

    sidecar = _get_sidecar(conn, "README.txt")
    assert sidecar["status"] == "active"
    assert sidecar["id"] == before_id  # same row revived, not a new one

    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM sidecar_files WHERE filename = 'README.txt'")
        assert cur.fetchone()[0] == 1  # no duplicate row


def test_run_rescan_updates_last_scanned_at(conn, make_root):
    dropfolder = make_root(kind="drop_folder")

    run_rescan(conn)

    with conn.cursor() as cur:
        cur.execute("SELECT last_scanned_at FROM watched_roots WHERE id = %s", (dropfolder.id,))
        assert cur.fetchone()[0] is not None


def test_run_rescan_skips_unreadable_file_without_aborting_the_pass(conn, make_root, monkeypatch):
    # Same regression class as backfill's equivalent fix: run_rescan has no
    # per-file try/except of its own (only main()'s try/except around the
    # *whole* run_rescan call, which just skips the entire pass on the
    # first error) — so one unreadable file early in the walk order used
    # to silently block every other file's new-file ingestion/drift-check
    # for that entire cycle. A bad file must be skipped, logged, and the
    # rest of the walk (including brand-new files discovered the same
    # pass) must still be processed.
    import common.ingest as ingest_module

    dropfolder = make_root(kind="drop_folder")
    library = make_root(kind="library", ingest_mode="index_in_place")
    bad_path = _touch(os.path.join(library.container_path, "corrupted.stl"))
    _touch(os.path.join(library.container_path, "good.stl"))

    real_sha256_file = ingest_module.sha256_file

    def flaky_sha256_file(path):
        if path == bad_path:
            raise OSError(35, "Resource deadlock avoided")
        return real_sha256_file(path)

    monkeypatch.setattr(ingest_module, "sha256_file", flaky_sha256_file)

    run_rescan(conn)  # must not raise

    assert _get_file(conn, "good.stl") is not None
    assert _get_file(conn, "corrupted.stl") is None  # skipped, retried next pass
