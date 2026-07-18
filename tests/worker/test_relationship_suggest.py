import os

from app.relationship_suggest import suggest_folder_project, suggest_for_file


def _insert_file(conn, root, filename, ext, content_hash, subdir=None):
    directory = os.path.join(root.host_path, subdir) if subdir else root.host_path
    path = os.path.join(directory, filename)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO files (watched_root_id, path, filename, ext, size_bytes, content_hash, status)
            VALUES (%s, %s, %s, %s, 1, %s, 'active')
            RETURNING id
            """,
            (root.id, path, filename, ext, content_hash),
        )
        return cur.fetchone()[0], path


def _relationships(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT f1.filename, r.type, r.status, f2.filename
            FROM relationships r
            JOIN files f1 ON f1.id = r.from_file_id
            JOIN files f2 ON f2.id = r.to_file_id
            """
        )
        return cur.fetchall()


# ---- duplicate_of -----------------------------------------------------------

def test_duplicate_of_suggested_for_identical_hash(conn, make_root):
    root = make_root()
    old_id, _ = _insert_file(conn, root, "widget.stl", ".stl", "samehash")
    new_id, _ = _insert_file(conn, root, "widget_copy.stl", ".stl", "samehash")

    suggest_for_file(conn, new_id, "widget_copy.stl", ".stl")

    rels = _relationships(conn)
    assert len(rels) == 1
    _, rel_type, status, _ = rels[0]
    assert rel_type == "duplicate_of"
    assert status == "suggested"


def test_duplicate_of_not_suggested_for_different_hash(conn, make_root):
    root = make_root()
    _insert_file(conn, root, "widget.stl", ".stl", "hash-a")
    new_id, _ = _insert_file(conn, root, "other.stl", ".stl", "hash-b")

    suggest_for_file(conn, new_id, "other.stl", ".stl")

    assert _relationships(conn) == []


def test_duplicate_of_not_resuggested_after_reject(conn, make_root):
    root = make_root()
    _insert_file(conn, root, "widget.stl", ".stl", "samehash")
    new_id, _ = _insert_file(conn, root, "widget_copy.stl", ".stl", "samehash")
    suggest_for_file(conn, new_id, "widget_copy.stl", ".stl")

    with conn.cursor() as cur:
        cur.execute("UPDATE relationships SET status = 'rejected'")

    # re-running the heuristic for the same file (e.g. a later rescan) must
    # not resurrect the rejected suggestion
    suggest_for_file(conn, new_id, "widget_copy.stl", ".stl")

    rels = _relationships(conn)
    assert len(rels) == 1
    assert rels[0][2] == "rejected"


# ---- new_version_of ----------------------------------------------------------

def test_new_version_of_suggested_for_versioned_pair_same_ext(conn, make_root):
    root = make_root()
    _insert_file(conn, root, "bracket_v1.stl", ".stl", "hash-v1")
    v2_id, _ = _insert_file(conn, root, "bracket_v2.stl", ".stl", "hash-v2")

    suggest_for_file(conn, v2_id, "bracket_v2.stl", ".stl")

    rels = _relationships(conn)
    assert len(rels) == 1
    from_name, rel_type, status, to_name = rels[0]
    assert rel_type == "new_version_of"
    assert from_name == "bracket_v2.stl"  # newer -> older
    assert to_name == "bracket_v1.stl"


def test_new_version_of_not_suggested_across_different_extensions(conn, make_root):
    root = make_root()
    _insert_file(conn, root, "bracket_v1.stl", ".stl", "hash-v1")
    v2_id, _ = _insert_file(conn, root, "bracket_v2.step", ".step", "hash-v2")

    suggest_for_file(conn, v2_id, "bracket_v2.step", ".step")

    types = [r[1] for r in _relationships(conn)]
    assert "new_version_of" not in types


# ---- derived_from -------------------------------------------------------------

def test_derived_from_suggested_for_step_and_mesh_same_stem(conn, make_root):
    root = make_root()
    _insert_file(conn, root, "bracket.step", ".step", "hash-step")
    mesh_id, _ = _insert_file(conn, root, "bracket.stl", ".stl", "hash-stl")

    suggest_for_file(conn, mesh_id, "bracket.stl", ".stl")

    rels = _relationships(conn)
    assert len(rels) == 1
    from_name, rel_type, status, to_name = rels[0]
    assert rel_type == "derived_from"
    assert from_name == "bracket.stl"  # mesh derived from...
    assert to_name == "bracket.step"  # ...the CAD source


def test_derived_from_not_suggested_for_different_stems(conn, make_root):
    root = make_root()
    _insert_file(conn, root, "bracket.step", ".step", "hash-step")
    mesh_id, _ = _insert_file(conn, root, "widget.stl", ".stl", "hash-stl")

    suggest_for_file(conn, mesh_id, "widget.stl", ".stl")

    assert _relationships(conn) == []


# ---- suggest_folder_project ---------------------------------------------------

def test_folder_project_suggested_for_single_file(conn, make_root):
    root = make_root()
    file_id, path = _insert_file(conn, root, "widget.stl", ".stl", "hash", subdir="SoloWidget")

    suggest_folder_project(conn, file_id, path, root)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT p.name, pf.status FROM projects p
            JOIN project_files pf ON pf.project_id = p.id
            WHERE pf.file_id = %s
            """,
            (file_id,),
        )
        row = cur.fetchone()
    assert row == ("SoloWidget", "suggested")


def test_folder_project_skipped_when_file_sits_directly_in_root(conn, make_root):
    root = make_root()
    file_id, path = _insert_file(conn, root, "widget.stl", ".stl", "hash")  # no subdir

    suggest_folder_project(conn, file_id, path, root)

    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM projects")
        assert cur.fetchone()[0] == 0


def test_folder_project_reuses_existing_project_by_name(conn, make_root):
    root = make_root()
    id_a, path_a = _insert_file(conn, root, "part_a.stl", ".stl", "hash-a", subdir="Kit")
    id_b, path_b = _insert_file(conn, root, "part_b.stl", ".stl", "hash-b", subdir="Kit")

    suggest_folder_project(conn, id_a, path_a, root)
    suggest_folder_project(conn, id_b, path_b, root)

    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM projects WHERE name = 'Kit'")
        assert cur.fetchone()[0] == 1  # one project, not two
        cur.execute("SELECT count(*) FROM project_files pf JOIN projects p ON p.id = pf.project_id WHERE p.name = 'Kit'")
        assert cur.fetchone()[0] == 2
