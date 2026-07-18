import os
import zipfile

from common.zip_ingest import stage_zip_if_relevant, zip_contains_model_files


def _make_zip(path, entries):
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return str(path)


def test_zip_contains_model_files_true_when_stl_inside(tmp_path):
    zip_path = _make_zip(tmp_path / "kit.zip", {"widget.stl": "geometry", "readme.txt": "hi"})
    assert zip_contains_model_files(zip_path)


def test_zip_contains_model_files_false_when_no_model_inside(tmp_path):
    zip_path = _make_zip(tmp_path / "photos.zip", {"a.jpg": "x", "notes.txt": "y"})
    assert not zip_contains_model_files(zip_path)


def test_zip_contains_model_files_false_for_bad_zip(tmp_path):
    bad = tmp_path / "not-a-zip.zip"
    bad.write_bytes(b"this is not a real zip file")
    assert not zip_contains_model_files(str(bad))


def test_stage_zip_if_relevant_skips_zip_with_no_model_files(conn, make_root):
    root = make_root()
    zip_path = _make_zip(os.path.join(root.container_path, "photos.zip"), {"a.jpg": "x"})

    result = stage_zip_if_relevant(conn, root, zip_path)

    assert result is None
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM zip_files")
        assert cur.fetchone()[0] == 0


def test_stage_zip_if_relevant_records_zip_with_model_files(conn, make_root):
    root = make_root()
    zip_path = _make_zip(os.path.join(root.container_path, "kit.zip"), {"widget.stl": "geometry"})

    zip_id = stage_zip_if_relevant(conn, root, zip_path)

    assert zip_id is not None
    with conn.cursor() as cur:
        cur.execute("SELECT filename, status FROM zip_files WHERE id = %s", (zip_id,))
        filename, status = cur.fetchone()
    assert filename == "kit.zip"
    assert status == "suggested"


def test_stage_zip_if_relevant_does_not_resurrect_a_rejected_zip(conn, make_root):
    root = make_root()
    zip_path = _make_zip(os.path.join(root.container_path, "kit.zip"), {"widget.stl": "geometry"})

    zip_id = stage_zip_if_relevant(conn, root, zip_path)
    with conn.cursor() as cur:
        cur.execute("UPDATE zip_files SET status = 'rejected' WHERE id = %s", (zip_id,))

    # simulate the same zip being seen again on a later scan
    result = stage_zip_if_relevant(conn, root, zip_path)

    assert result is None  # ON CONFLICT (path) DO NOTHING — never re-suggested
    with conn.cursor() as cur:
        cur.execute("SELECT status FROM zip_files WHERE id = %s", (zip_id,))
        assert cur.fetchone()[0] == "rejected"
