import os

from common import ingest


def _touch(root, filename, content=b"x"):
    path = os.path.join(root.container_path, filename)
    with open(path, "wb") as f:
        f.write(content)
    return path


# ---- stage_and_hash / stage_stub -------------------------------------------

def test_stage_and_hash_inserts_row_with_hash(conn, make_root):
    root = make_root()
    file_path = _touch(root, "widget.stl", b"geometry-bytes")

    file_id = ingest.stage_and_hash(conn, root, file_path)
    assert file_id is not None

    with conn.cursor() as cur:
        cur.execute("SELECT filename, ext, content_hash, status FROM files WHERE id = %s", (file_id,))
        filename, ext, content_hash, status = cur.fetchone()
    assert filename == "widget.stl"
    assert ext == ".stl"
    assert content_hash is not None
    assert status == "active"


def test_stage_and_hash_is_idempotent_on_same_path(conn, make_root):
    root = make_root()
    file_path = os.path.join(root.container_path, "widget.stl")
    with open(file_path, "wb") as f:
        f.write(b"geometry-bytes")

    first_id = ingest.stage_and_hash(conn, root, file_path)
    second_id = ingest.stage_and_hash(conn, root, file_path)
    assert first_id is not None
    assert second_id is None  # already known — ON CONFLICT (path) DO NOTHING


def test_stage_stub_enqueues_ingest_job(conn, make_root):
    root = make_root()
    file_path = os.path.join(root.container_path, "widget.stl")
    with open(file_path, "wb") as f:
        f.write(b"geometry-bytes")

    file_id = ingest.stage_stub(conn, root, file_path)
    assert file_id is not None

    with conn.cursor() as cur:
        cur.execute("SELECT content_hash FROM files WHERE id = %s", (file_id,))
        assert cur.fetchone()[0] is None  # no hash yet — that's the ingest job's job

        cur.execute("SELECT job_type, status FROM jobs WHERE file_id = %s", (file_id,))
        job_type, status = cur.fetchone()
    assert job_type == "ingest"
    assert status == "queued"


def test_stage_stub_is_idempotent_on_same_path(conn, make_root):
    root = make_root()
    file_path = os.path.join(root.container_path, "widget.stl")
    with open(file_path, "wb") as f:
        f.write(b"geometry-bytes")

    assert ingest.stage_stub(conn, root, file_path) is not None
    assert ingest.stage_stub(conn, root, file_path) is None


# ---- repoint_file -------------------------------------------------------

def test_repoint_file_updates_path_filename_ext(conn, make_root):
    root = make_root()
    file_id = ingest.stage_and_hash(conn, root, _touch(root, "widget.stl"))

    new_dir = os.path.join(root.container_path, "subdir")
    os.makedirs(new_dir)
    new_path = os.path.join(new_dir, "renamed.stl")
    os.rename(os.path.join(root.container_path, "widget.stl"), new_path)

    ingest.repoint_file(conn, file_id, root, new_path)

    with conn.cursor() as cur:
        cur.execute("SELECT path, filename, ext, status FROM files WHERE id = %s", (file_id,))
        path, filename, ext, status = cur.fetchone()
    assert path == new_path
    assert filename == "renamed.stl"
    assert ext == ".stl"
    assert status == "active"


def test_repoint_file_preserves_id_and_related_rows(conn, make_root):
    root = make_root()
    file_id = ingest.stage_and_hash(conn, root, _touch(root, "widget.stl"))
    with conn.cursor() as cur:
        cur.execute("INSERT INTO tags (name) VALUES ('kept') RETURNING id")
        tag_id = cur.fetchone()[0]
        cur.execute("INSERT INTO file_tags (file_id, tag_id) VALUES (%s, %s)", (file_id, tag_id))

    new_path = os.path.join(root.container_path, "renamed.stl")
    os.rename(os.path.join(root.container_path, "widget.stl"), new_path)
    ingest.repoint_file(conn, file_id, root, new_path)

    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM files WHERE id = %s", (file_id,))
        assert cur.fetchone()[0] == 1  # same row, not a new one
        cur.execute("SELECT count(*) FROM file_tags WHERE file_id = %s AND tag_id = %s", (file_id, tag_id))
        assert cur.fetchone()[0] == 1  # tag survived the move


# ---- maybe_enqueue_render ---------------------------------------------------

def _job_types_for(conn, file_id):
    with conn.cursor() as cur:
        cur.execute("SELECT job_type FROM jobs WHERE file_id = %s", (file_id,))
        return [row[0] for row in cur.fetchall()]


def test_maybe_enqueue_render_mesh_gets_render_job(conn, make_root):
    root = make_root()
    file_id = ingest.stage_and_hash(conn, root, _touch(root, "widget.stl"))
    ingest.maybe_enqueue_render(conn, file_id, ".stl")
    assert _job_types_for(conn, file_id) == ["render"]


def test_maybe_enqueue_render_obj_gets_render_job(conn, make_root):
    # .obj is just another MESH_EXTENSIONS entry — no CAD tessellation,
    # same fast lane as .stl/.3mf.
    root = make_root()
    file_id = ingest.stage_and_hash(conn, root, _touch(root, "widget.obj"))
    ingest.maybe_enqueue_render(conn, file_id, ".obj")
    assert _job_types_for(conn, file_id) == ["render"]


def test_maybe_enqueue_render_step_gets_render_step_job(conn, make_root):
    root = make_root()
    file_id = ingest.stage_and_hash(conn, root, _touch(root, "part.step"))
    ingest.maybe_enqueue_render(conn, file_id, ".step")
    assert _job_types_for(conn, file_id) == ["render_step"]


def test_maybe_enqueue_render_svg_and_scad_get_render_job(conn, make_root):
    root = make_root()
    svg_id = ingest.stage_and_hash(conn, root, _touch(root, "logo.svg"))
    ingest.maybe_enqueue_render(conn, svg_id, ".svg")
    assert _job_types_for(conn, svg_id) == ["render"]

    scad_id = ingest.stage_and_hash(conn, root, _touch(root, "bracket.scad"))
    ingest.maybe_enqueue_render(conn, scad_id, ".scad")
    assert _job_types_for(conn, scad_id) == ["render"]


def test_maybe_enqueue_render_gcode_gets_render_job(conn, make_root):
    # Fast lane, not render_step — extracting an embedded thumbnail from
    # gcode comments is cheap text scanning, not CAD tessellation.
    root = make_root()
    file_id = ingest.stage_and_hash(conn, root, _touch(root, "part.gcode"))
    ingest.maybe_enqueue_render(conn, file_id, ".gcode")
    assert _job_types_for(conn, file_id) == ["render"]


def test_maybe_enqueue_render_unrecognized_ext_gets_no_job(conn, make_root):
    root = make_root()
    file_id = ingest.stage_and_hash(conn, root, _touch(root, "readme.txt"))
    ingest.maybe_enqueue_render(conn, file_id, ".txt")
    assert _job_types_for(conn, file_id) == []


# ---- stage_sidecar -----------------------------------------------------------

def _sidecar_row(conn, sidecar_id):
    with conn.cursor() as cur:
        cur.execute("SELECT filename, ext, thumbnail_path FROM sidecar_files WHERE id = %s", (sidecar_id,))
        return cur.fetchone()


def test_stage_sidecar_non_image_gets_no_thumbnail(conn, make_root):
    root = make_root()
    sidecar_id = ingest.stage_sidecar(conn, root, _touch(root, "README.txt"))
    assert sidecar_id is not None
    filename, ext, thumbnail_path = _sidecar_row(conn, sidecar_id)
    assert filename == "README.txt"
    assert ext == ".txt"
    assert thumbnail_path is None


def test_stage_sidecar_image_gets_copied_as_thumbnail(conn, make_root, tmp_path, monkeypatch):
    monkeypatch.setattr(ingest, "THUMBNAILS_DIR", str(tmp_path))
    root = make_root()
    sidecar_id = ingest.stage_sidecar(conn, root, _touch(root, "preview.jpg", b"fake-jpeg-bytes"))
    assert sidecar_id is not None
    filename, ext, thumbnail_path = _sidecar_row(conn, sidecar_id)
    assert filename == "preview.jpg"
    assert thumbnail_path == f"sidecar-{sidecar_id}.jpg"
    with open(tmp_path / thumbnail_path, "rb") as f:
        assert f.read() == b"fake-jpeg-bytes"


def test_stage_sidecar_is_idempotent_on_same_path(conn, make_root):
    root = make_root()
    file_path = _touch(root, "README.txt")
    assert ingest.stage_sidecar(conn, root, file_path) is not None
    assert ingest.stage_sidecar(conn, root, file_path) is None


# ---- relocate ---------------------------------------------------------------

def test_relocate_root_level_file_flattens_into_dropfolder(make_root):
    downloads = make_root(kind="existing_library", ingest_mode="relocate_to_dropfolder")
    dropfolder = make_root(kind="drop_folder")

    src = _touch(downloads, "widget.stl")
    dest = ingest.relocate(downloads, dropfolder, src)

    assert dest == os.path.join(dropfolder.container_path, "widget.stl")
    assert os.path.exists(dest)
    assert not os.path.exists(src)


def test_relocate_root_level_collision_gets_hash_suffix(make_root):
    downloads = make_root(kind="existing_library", ingest_mode="relocate_to_dropfolder")
    dropfolder = make_root(kind="drop_folder")

    _touch(dropfolder, "widget.stl", content=b"already-here")
    src = _touch(downloads, "widget.stl", content=b"incoming-different-bytes")

    dest = ingest.relocate(downloads, dropfolder, src)

    assert dest != os.path.join(dropfolder.container_path, "widget.stl")
    assert os.path.basename(dest).startswith("widget (")
    assert os.path.exists(dest)
    # the pre-existing file at the plain destination name is untouched
    with open(os.path.join(dropfolder.container_path, "widget.stl"), "rb") as f:
        assert f.read() == b"already-here"


def test_relocate_leaf_folder_moves_whole_folder(make_root):
    downloads = make_root(kind="existing_library", ingest_mode="relocate_to_dropfolder")
    dropfolder = make_root(kind="drop_folder")

    kit_dir = os.path.join(downloads.container_path, "Kit")
    os.makedirs(kit_dir)
    part_a = os.path.join(kit_dir, "part_a.stl")
    part_b = os.path.join(kit_dir, "part_b.stl")
    readme = os.path.join(kit_dir, "README.txt")
    for p in (part_a, part_b, readme):
        with open(p, "wb") as f:
            f.write(b"x")

    dest = ingest.relocate(downloads, dropfolder, part_a)

    assert dest == os.path.join(dropfolder.container_path, "Kit", "part_a.stl")
    assert not os.path.exists(kit_dir)  # whole source folder moved, not copied
    moved_dir = os.path.join(dropfolder.container_path, "Kit")
    assert os.path.exists(os.path.join(moved_dir, "part_a.stl"))
    assert os.path.exists(os.path.join(moved_dir, "part_b.stl"))
    assert os.path.exists(os.path.join(moved_dir, "README.txt"))  # sidecar carried along


def test_relocate_leaf_folder_collision_gets_numeric_suffix(make_root):
    downloads = make_root(kind="existing_library", ingest_mode="relocate_to_dropfolder")
    dropfolder = make_root(kind="drop_folder")

    os.makedirs(os.path.join(dropfolder.container_path, "Kit"))
    with open(os.path.join(dropfolder.container_path, "Kit", "existing.stl"), "wb") as f:
        f.write(b"x")

    kit_dir = os.path.join(downloads.container_path, "Kit")
    os.makedirs(kit_dir)
    part_a = os.path.join(kit_dir, "part_a.stl")
    with open(part_a, "wb") as f:
        f.write(b"x")

    dest = ingest.relocate(downloads, dropfolder, part_a)

    assert dest == os.path.join(dropfolder.container_path, "Kit (2)", "part_a.stl")
    # the pre-existing "Kit" folder at the destination is untouched, not merged into
    assert os.path.exists(os.path.join(dropfolder.container_path, "Kit", "existing.stl"))
    assert not os.path.exists(os.path.join(dropfolder.container_path, "Kit", "part_a.stl"))


def test_relocate_parent_with_subdirectories_falls_back_to_flatten(make_root):
    downloads = make_root(kind="existing_library", ingest_mode="relocate_to_dropfolder")
    dropfolder = make_root(kind="drop_folder")

    kit_dir = os.path.join(downloads.container_path, "Kit")
    nested_dir = os.path.join(kit_dir, "nested")
    os.makedirs(nested_dir)
    part_a = os.path.join(kit_dir, "part_a.stl")
    with open(part_a, "wb") as f:
        f.write(b"x")

    dest = ingest.relocate(downloads, dropfolder, part_a)

    # falls back to flattening just this file — the folder (with its
    # subdirectory) is left in place, not moved as a unit
    assert dest == os.path.join(dropfolder.container_path, "part_a.stl")
    assert os.path.exists(dest)
    assert os.path.isdir(kit_dir)  # source folder untouched
    assert os.path.isdir(nested_dir)


def test_relocate_already_relocated_by_concurrent_handler_returns_none(make_root):
    downloads = make_root(kind="existing_library", ingest_mode="relocate_to_dropfolder")
    dropfolder = make_root(kind="drop_folder")

    kit_dir = os.path.join(downloads.container_path, "Kit")
    os.makedirs(kit_dir)
    part_a = os.path.join(kit_dir, "part_a.stl")
    with open(part_a, "wb") as f:
        f.write(b"x")

    # simulate a sibling file's event having already won the race and moved
    # the whole folder away before this call runs
    import shutil

    shutil.move(kit_dir, os.path.join(dropfolder.container_path, "Kit"))

    assert ingest.relocate(downloads, dropfolder, part_a) is None
