import os

import pytest

from app.backfill import _walk_project_folders, run_backfill


def _touch(path, content=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)
    return path


# ---- _walk_project_folders ---------------------------------------------------

def test_walk_project_folders_classifies_model_sidecar_zip(tmp_path):
    folder = tmp_path / "Kit"
    _touch(folder / "widget.stl")
    _touch(folder / "README.txt")
    _touch(folder / "archive.zip")
    _touch(folder / ".DS_Store")  # junk — excluded entirely, not even a sidecar
    _touch(folder / "._widget.stl")  # AppleDouble shadow — junk despite the model extension

    results = {dirpath: (m, s, z) for dirpath, m, s, z in _walk_project_folders(str(tmp_path))}
    model_paths, sidecar_paths, zip_paths = results[str(folder)]

    assert model_paths == [str(folder / "widget.stl")]
    assert sidecar_paths == [str(folder / "README.txt")]
    assert zip_paths == [str(folder / "archive.zip")]


def test_walk_project_folders_yields_empty_model_paths_for_non_model_folder(tmp_path):
    folder = tmp_path / "Photos"
    _touch(folder / "a.jpg")

    results = {dirpath: (m, s, z) for dirpath, m, s, z in _walk_project_folders(str(tmp_path))}
    model_paths, sidecar_paths, zip_paths = results[str(folder)]

    assert model_paths == []
    assert sidecar_paths == [str(folder / "a.jpg")]  # still classified — caller decides whether to index it


# ---- run_backfill ------------------------------------------------------------

def test_run_backfill_requires_a_dropfolder_root(conn, make_root):
    make_root(kind="existing_library")  # no drop_folder root at all
    with pytest.raises(RuntimeError):
        run_backfill(conn)


def test_run_backfill_indexes_new_files_in_index_in_place_root(conn, make_root):
    dropfolder = make_root(kind="drop_folder")
    library = make_root(kind="existing_library", ingest_mode="index_in_place")
    _touch(os.path.join(library.container_path, "widget.stl"), b"geometry")

    run_backfill(conn)

    with conn.cursor() as cur:
        cur.execute("SELECT filename, content_hash FROM files WHERE watched_root_id = %s", (library.id,))
        rows = cur.fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "widget.stl"
    assert rows[0][1] is not None  # hashed inline, unlike the live-watcher stub path


def test_run_backfill_indexes_sidecar_only_for_folder_with_model_file(conn, make_root):
    dropfolder = make_root(kind="drop_folder")
    library = make_root(kind="existing_library", ingest_mode="index_in_place")
    _touch(os.path.join(library.container_path, "ProjectA", "widget.stl"))
    _touch(os.path.join(library.container_path, "ProjectA", "README.txt"))
    _touch(os.path.join(library.container_path, "JustPhotos", "photo.jpg"))

    run_backfill(conn)

    with conn.cursor() as cur:
        cur.execute("SELECT filename FROM sidecar_files")
        sidecar_filenames = {row[0] for row in cur.fetchall()}
    assert sidecar_filenames == {"README.txt"}  # JustPhotos has no model file, so photo.jpg is never indexed


def test_run_backfill_relocates_whole_folder_for_relocate_to_dropfolder_root(conn, make_root):
    """The whole Kit/ folder moves as a unit on the very first file
    processed in it (os.walk's directory entry order isn't guaranteed to
    match creation order, so which of part_a/part_b goes first varies) —
    but within that SAME backfill pass, only that first file actually gets
    staged: its sibling's original path is gone by the time the loop
    reaches it (already carried away by the folder move), so
    ingest.relocate correctly reports "nothing to do" for it (see
    test_ingest.py's race-guard test) rather than erroring. This is
    deliberate eventual consistency — a second pass (next backfill/rescan
    cycle, exercised below) picks up the straggler once it's already
    sitting in the drop folder."""
    dropfolder = make_root(kind="drop_folder")
    downloads = make_root(kind="existing_library", ingest_mode="relocate_to_dropfolder")
    _touch(os.path.join(downloads.container_path, "Kit", "part_a.stl"))
    _touch(os.path.join(downloads.container_path, "Kit", "part_b.stl"))
    _touch(os.path.join(downloads.container_path, "Kit", "README.txt"))

    run_backfill(conn)

    # the whole folder (siblings + sidecar) already physically relocated...
    assert os.path.isdir(os.path.join(dropfolder.container_path, "Kit"))
    assert os.path.exists(os.path.join(dropfolder.container_path, "Kit", "part_a.stl"))
    assert os.path.exists(os.path.join(dropfolder.container_path, "Kit", "part_b.stl"))
    assert os.path.exists(os.path.join(dropfolder.container_path, "Kit", "README.txt"))
    assert not os.path.isdir(os.path.join(downloads.container_path, "Kit"))  # moved, not copied

    # ...but only ONE of the two siblings got indexed in this same pass —
    # whichever os.walk happened to process first
    with conn.cursor() as cur:
        cur.execute("SELECT filename, watched_root_id FROM files ORDER BY filename")
        files = cur.fetchall()
    assert [f[0] for f in files] in (["part_a.stl"], ["part_b.stl"])
    assert files[0][1] == dropfolder.id  # landed under the drop folder's root_id

    # a second pass (simulating the next backfill/rescan cycle) catches the
    # straggler + its sidecar, since they're now just sitting in the
    # already-index_in_place drop folder
    run_backfill(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT filename FROM files ORDER BY filename")
        filenames = [row[0] for row in cur.fetchall()]
        cur.execute("SELECT filename FROM sidecar_files")
        sidecar_filenames = [row[0] for row in cur.fetchall()]
    assert filenames == ["part_a.stl", "part_b.stl"]
    assert sidecar_filenames == ["README.txt"]


def test_run_backfill_creates_suggested_project_for_single_file_folder(conn, make_root):
    dropfolder = make_root(kind="drop_folder")
    library = make_root(kind="existing_library", ingest_mode="index_in_place")
    _touch(os.path.join(library.container_path, "SoloWidget", "widget.stl"))

    run_backfill(conn)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT p.name, pf.status FROM projects p
            JOIN project_files pf ON pf.project_id = p.id
            JOIN files f ON f.id = pf.file_id
            WHERE f.filename = 'widget.stl'
            """
        )
        row = cur.fetchone()
    assert row == ("SoloWidget", "suggested")
