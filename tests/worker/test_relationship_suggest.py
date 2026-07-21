import os

from psycopg.rows import dict_row

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


def test_folder_project_uses_parent_name_when_immediate_folder_is_generic(conn, make_root):
    root = make_root()
    file_id, path = _insert_file(conn, root, "widget.stl", ".stl", "hash", subdir="Widget/files")

    suggest_folder_project(conn, file_id, path, root)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT p.name FROM projects p JOIN project_files pf ON pf.project_id = p.id WHERE pf.file_id = %s",
            (file_id,),
        )
        assert cur.fetchone()[0] == "Widget"  # not "files"


def test_folder_project_generic_named_folders_dont_collide_across_parents(conn, make_root):
    root = make_root()
    id_a, path_a = _insert_file(conn, root, "a.stl", ".stl", "hash-a", subdir="Widget/files")
    id_b, path_b = _insert_file(conn, root, "b.stl", ".stl", "hash-b", subdir="Gadget/files")

    suggest_folder_project(conn, id_a, path_a, root)
    suggest_folder_project(conn, id_b, path_b, root)

    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM projects WHERE name = 'files'")
        assert cur.fetchone()[0] == 0  # never grouped under a shared "files" project
        cur.execute("SELECT count(*) FROM projects WHERE name IN ('Widget', 'Gadget')")
        assert cur.fetchone()[0] == 2


def test_folder_project_decodes_plus_for_space_in_name(conn, make_root):
    root = make_root()
    file_id, path = _insert_file(conn, root, "widget.stl", ".stl", "hash", subdir="4th+of+July+Hat")

    suggest_folder_project(conn, file_id, path, root)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT p.name FROM projects p JOIN project_files pf ON pf.project_id = p.id WHERE pf.file_id = %s",
            (file_id,),
        )
        assert cur.fetchone()[0] == "4th of July Hat"


def test_folder_project_leaves_real_spaces_and_plusses_alone(conn, make_root):
    root = make_root()
    file_id, path = _insert_file(conn, root, "widget.stl", ".stl", "hash", subdir="C++ Project")

    suggest_folder_project(conn, file_id, path, root)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT p.name FROM projects p JOIN project_files pf ON pf.project_id = p.id WHERE pf.file_id = %s",
            (file_id,),
        )
        assert cur.fetchone()[0] == "C++ Project"  # already has real spaces — left untouched


def test_folder_project_uses_parent_name_for_format_named_export_folders(conn, make_root):
    # "STL"/"3MF Files"/etc. (a per-format export subfolder) is exactly the
    # same collision risk as a literal "files" folder — confirmed live: 36
    # real projects named nothing but a bare format, each a genuinely
    # different kit but all sharing the same unhelpful name.
    root = make_root()
    id_a, path_a = _insert_file(conn, root, "a.stl", ".stl", "hash-a", subdir="Widget/STL")
    id_b, path_b = _insert_file(conn, root, "b.3mf", ".3mf", "hash-b", subdir="Gadget/3MF Files")

    suggest_folder_project(conn, id_a, path_a, root)
    suggest_folder_project(conn, id_b, path_b, root)

    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM projects WHERE lower(name) IN ('stl', '3mf files')")
        assert cur.fetchone()[0] == 0  # never grouped/named under the bare format
        cur.execute("SELECT count(*) FROM projects WHERE name IN ('Widget', 'Gadget')")
        assert cur.fetchone()[0] == 2


def test_folder_project_uses_parent_name_for_cad_files_export_folder(conn, make_root):
    # "cad"/"cad_files" isn't a file extension but is the same bare
    # descriptor pattern — confirmed live with two unrelated real kits.
    root = make_root()
    file_id, path = _insert_file(conn, root, "widget.step", ".step", "hash", subdir="Thingamajig/cad_files")

    suggest_folder_project(conn, file_id, path, root)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT p.name FROM projects p JOIN project_files pf ON pf.project_id = p.id WHERE pf.file_id = %s",
            (file_id,),
        )
        assert cur.fetchone()[0] == "Thingamajig"  # not "cad_files"


def test_folder_project_treats_singular_and_plural_format_folder_as_equivalent(conn, make_root):
    # "3MF", "3mf file", "3mf files" must all be recognized as the same
    # generic container — a folder with just one file inside is exactly
    # as generic as one with several.
    root = make_root()
    id_a, path_a = _insert_file(conn, root, "a.3mf", ".3mf", "hash-a", subdir="Widget/3mf file")
    id_b, path_b = _insert_file(conn, root, "b.3mf", ".3mf", "hash-b", subdir="Gadget/3MF File")

    suggest_folder_project(conn, id_a, path_a, root)
    suggest_folder_project(conn, id_b, path_b, root)

    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM projects WHERE lower(name) IN ('3mf file', '3mf files', '3mf')")
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT count(*) FROM projects WHERE name IN ('Widget', 'Gadget')")
        assert cur.fetchone()[0] == 2


def test_folder_project_keeps_generic_name_with_no_meaningful_parent(conn, make_root):
    root = make_root()
    file_id, path = _insert_file(conn, root, "widget.stl", ".stl", "hash", subdir="files")

    suggest_folder_project(conn, file_id, path, root)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT p.name FROM projects p JOIN project_files pf ON pf.project_id = p.id WHERE pf.file_id = %s",
            (file_id,),
        )
        assert cur.fetchone()[0] == "files"  # rare edge case: no better name available


def test_folder_project_same_name_different_paths_dont_collide(conn, make_root):
    # Two unrelated roots, each with a leaf folder named "misc" — same name,
    # genuinely different real folders. Matching by path (not name) means
    # these must NOT be merged into one shared "misc" project — and now
    # that project names are disambiguated on collision, the second one
    # doesn't even keep the literal name "misc" (see
    # test_folder_project_disambiguates_colliding_name_with_parent_folder
    # for the disambiguation itself).
    root_a = make_root()
    root_b = make_root()
    id_a, path_a = _insert_file(conn, root_a, "a.stl", ".stl", "hash-a", subdir="misc")
    id_b, path_b = _insert_file(conn, root_b, "b.stl", ".stl", "hash-b", subdir="misc")

    suggest_folder_project(conn, id_a, path_a, root_a)
    suggest_folder_project(conn, id_b, path_b, root_b)

    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM projects WHERE name = 'misc'")
        assert cur.fetchone()[0] == 1  # exactly one keeps the plain name
        cur.execute(
            "SELECT count(DISTINCT project_id) FROM project_files WHERE file_id IN (%s, %s)",
            (id_a, id_b),
        )
        assert cur.fetchone()[0] == 2  # still two distinct projects, not merged


def test_folder_project_disambiguates_colliding_name_with_parent_folder(conn, make_root):
    root_a = make_root()
    root_b = make_root()
    id_a, path_a = _insert_file(conn, root_a, "a.stl", ".stl", "hash-a", subdir="Kit One/Bed")
    id_b, path_b = _insert_file(conn, root_b, "b.stl", ".stl", "hash-b", subdir="Kit Two/Bed")

    suggest_folder_project(conn, id_a, path_a, root_a)
    suggest_folder_project(conn, id_b, path_b, root_b)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT p.name FROM projects p JOIN project_files pf ON pf.project_id = p.id WHERE pf.file_id = %s",
            (id_a,),
        )
        assert cur.fetchone()[0] == "Bed"  # first one is unaffected
        cur.execute(
            "SELECT p.name FROM projects p JOIN project_files pf ON pf.project_id = p.id WHERE pf.file_id = %s",
            (id_b,),
        )
        assert cur.fetchone()[0] == "Bed (Kit Two)"  # second is disambiguated with its parent


def test_folder_project_disambiguates_against_a_manually_created_project(conn, make_root):
    # A manually-created project with the same name is just as real a
    # collision as one this function created itself.
    root = make_root()
    with conn.cursor() as cur:
        cur.execute("INSERT INTO projects (name) VALUES ('Widget')")

    file_id, path = _insert_file(conn, root, "a.stl", ".stl", "hash-a", subdir="Kit/Widget")
    suggest_folder_project(conn, file_id, path, root)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT p.name FROM projects p JOIN project_files pf ON pf.project_id = p.id WHERE pf.file_id = %s",
            (file_id,),
        )
        assert cur.fetchone()[0] == "Widget (Kit)"


def test_folder_project_renaming_still_matches_by_path(conn, make_root):
    # Renaming an auto-created project (the pencil-edit UI) must not break
    # future matching for that same folder — the lookup key is the path,
    # not whatever the name currently is.
    root = make_root()
    id_a, path_a = _insert_file(conn, root, "a.stl", ".stl", "hash-a", subdir="Kit")
    suggest_folder_project(conn, id_a, path_a, root)

    with conn.cursor() as cur:
        cur.execute("UPDATE projects SET name = 'Renamed Kit' WHERE name = 'Kit' RETURNING id")
        project_id = cur.fetchone()[0]

    id_b, path_b = _insert_file(conn, root, "b.stl", ".stl", "hash-b", subdir="Kit")
    suggest_folder_project(conn, id_b, path_b, root)

    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM projects WHERE source_folder_path IS NOT NULL")
        assert cur.fetchone()[0] == 1  # still just the one project, not a new duplicate
        cur.execute("SELECT project_id FROM project_files WHERE file_id = %s", (id_b,))
        assert cur.fetchone()[0] == project_id  # new sibling joined the renamed project


def test_folder_project_never_matches_a_manually_created_project(conn, make_root):
    # A manually-created project (NULL source_folder_path) that happens to
    # share a name with a real folder must never be treated as a match —
    # only projects this function itself created (a real source_folder_path)
    # are candidates for reuse.
    with conn.cursor() as cur:
        cur.execute("INSERT INTO projects (name) VALUES ('Kit') RETURNING id")
        manual_project_id = cur.fetchone()[0]

    root = make_root()
    file_id, path = _insert_file(conn, root, "widget.stl", ".stl", "hash", subdir="Kit")
    suggest_folder_project(conn, file_id, path, root)

    with conn.cursor() as cur:
        cur.execute("SELECT project_id FROM project_files WHERE file_id = %s", (file_id,))
        assert cur.fetchone()[0] != manual_project_id
        # The manual "Kit" is untouched; the new auto-created one is
        # disambiguated against it (parent folder name is an unpredictable
        # pytest tmp dir, so just check it's a distinct "Kit (...)" name
        # rather than asserting the exact qualifier).
        cur.execute("SELECT count(*) FROM projects WHERE name = 'Kit'")
        assert cur.fetchone()[0] == 1
        cur.execute("SELECT name FROM projects WHERE id != %s AND name LIKE 'Kit (%%'", (manual_project_id,))
        assert cur.fetchone() is not None


# ---- wrapper-project grouping (2+ children get a shared parent) -----------

def test_folder_project_wraps_two_sibling_leaf_projects_under_a_new_parent(conn, make_root):
    root = make_root()
    id_a, path_a = _insert_file(conn, root, "a.stl", ".stl", "hash-a", subdir="World Map/1_Europe")
    id_b, path_b = _insert_file(conn, root, "b.stl", ".stl", "hash-b", subdir="World Map/2_Asia")

    suggest_folder_project(conn, id_a, path_a, root)
    suggest_folder_project(conn, id_b, path_b, root)

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT id, parent_project_id FROM projects WHERE name = '1_Europe'")
        europe = cur.fetchone()
        cur.execute("SELECT id, parent_project_id FROM projects WHERE name = '2_Asia'")
        asia = cur.fetchone()
        assert europe["parent_project_id"] is not None
        assert europe["parent_project_id"] == asia["parent_project_id"]
        cur.execute("SELECT name FROM projects WHERE id = %s", (europe["parent_project_id"],))
        assert cur.fetchone()["name"] == "World Map"


def test_folder_project_does_not_wrap_a_single_leaf_project(conn, make_root):
    root = make_root()
    file_id, path = _insert_file(conn, root, "a.stl", ".stl", "hash-a", subdir="Solo Kit/OnlyPart")

    suggest_folder_project(conn, file_id, path, root)

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT parent_project_id FROM projects WHERE name = 'OnlyPart'")
        assert cur.fetchone()["parent_project_id"] is None
        cur.execute("SELECT count(*) FROM projects WHERE name = 'Solo Kit'")
        assert cur.fetchone()["count"] == 0


def test_folder_project_wraps_a_third_sibling_under_the_same_existing_wrapper(conn, make_root):
    root = make_root()
    id_a, path_a = _insert_file(conn, root, "a.stl", ".stl", "hash-a", subdir="World Map/1_Europe")
    id_b, path_b = _insert_file(conn, root, "b.stl", ".stl", "hash-b", subdir="World Map/2_Asia")
    suggest_folder_project(conn, id_a, path_a, root)
    suggest_folder_project(conn, id_b, path_b, root)

    id_c, path_c = _insert_file(conn, root, "c.stl", ".stl", "hash-c", subdir="World Map/3_Africa")
    suggest_folder_project(conn, id_c, path_c, root)

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT count(*) FROM projects WHERE name = 'World Map'")
        assert cur.fetchone()["count"] == 1  # no duplicate wrapper created
        cur.execute(
            "SELECT p.parent_project_id FROM projects p WHERE p.name IN ('1_Europe', '2_Asia', '3_Africa')"
        )
        parent_ids = {row["parent_project_id"] for row in cur.fetchall()}
        assert len(parent_ids) == 1  # all three share the same parent


def test_folder_project_wrapper_uses_grandparent_name_when_immediate_folder_is_generic(conn, make_root):
    # A kit's own export folder can itself be generic (e.g. literally
    # called "files") — confirmed live with a real "Monopoly Board" kit
    # whose 20 per-tile subfolders all live directly inside a "files"
    # folder. The wrapper must be named from the grandparent, not "Files".
    root = make_root()
    id_a, path_a = _insert_file(conn, root, "a.stl", ".stl", "hash-a", subdir="Board Game/files/Tile_1")
    id_b, path_b = _insert_file(conn, root, "b.stl", ".stl", "hash-b", subdir="Board Game/files/Tile_2")

    suggest_folder_project(conn, id_a, path_a, root)
    suggest_folder_project(conn, id_b, path_b, root)

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT id, parent_project_id FROM projects WHERE name = 'Tile_1'")
        tile1 = cur.fetchone()
        cur.execute("SELECT name FROM projects WHERE id = %s", (tile1["parent_project_id"],))
        assert cur.fetchone()["name"] == "Board Game"  # not "Files"


def test_folder_project_skips_archive_folders_when_finding_a_wrapper_parent(conn, make_root):
    # "Archive"/"Archive 2" is just a zip-batch container, not a real kit
    # boundary — two unrelated kits that happen to share an "Archive 2"
    # ancestor must not get wrapped together under it.
    root = make_root()
    id_a, path_a = _insert_file(conn, root, "a.stl", ".stl", "hash-a", subdir="Archive 2/Kit One/Part A")
    id_b, path_b = _insert_file(conn, root, "b.stl", ".stl", "hash-b", subdir="Archive 2/Kit One/Part B")
    id_c, path_c = _insert_file(conn, root, "c.stl", ".stl", "hash-c", subdir="Archive 2/Kit Two/Part A")

    suggest_folder_project(conn, id_a, path_a, root)
    suggest_folder_project(conn, id_b, path_b, root)
    suggest_folder_project(conn, id_c, path_c, root)

    def project_for(file_id):
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT p.id, p.parent_project_id FROM projects p JOIN project_files pf ON pf.project_id = p.id WHERE pf.file_id = %s",
                (file_id,),
            )
            return cur.fetchone()

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT count(*) FROM projects WHERE lower(name) LIKE 'archive%%'")
        assert cur.fetchone()["count"] == 0  # no wrapper named after "Archive 2" itself

    part_a_one = project_for(id_a)
    part_b = project_for(id_b)
    assert part_a_one["parent_project_id"] is not None
    assert part_a_one["parent_project_id"] == part_b["parent_project_id"]  # Kit One's two parts share a wrapper
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT name FROM projects WHERE id = %s", (part_a_one["parent_project_id"],))
        assert cur.fetchone()["name"] == "Kit One"

    part_a_two = project_for(id_c)
    assert part_a_two["parent_project_id"] is None  # Kit Two has only one part — not wrapped


def test_folder_project_wrapper_name_disambiguates_on_collision(conn, make_root):
    root_a = make_root()
    root_b = make_root()
    for root, kit in ((root_a, "Kit"), (root_b, "Kit")):
        id_x, path_x = _insert_file(conn, root, "a.stl", ".stl", f"hash-{root.id}-a", subdir=f"{kit}/PartOne")
        id_y, path_y = _insert_file(conn, root, "b.stl", ".stl", f"hash-{root.id}-b", subdir=f"{kit}/PartTwo")
        suggest_folder_project(conn, id_x, path_x, root)
        suggest_folder_project(conn, id_y, path_y, root)

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT count(*) FROM projects WHERE name = 'Kit'")
        assert cur.fetchone()["count"] == 1  # only the first keeps the plain name
        cur.execute("SELECT count(*) FROM projects WHERE name LIKE 'Kit (%%'")
        assert cur.fetchone()["count"] == 1  # the second is disambiguated


def test_folder_project_never_overrides_a_manually_set_parent(conn, make_root):
    root = make_root()
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("INSERT INTO projects (name) VALUES ('Manually Chosen Parent') RETURNING id")
        manual_parent_id = cur.fetchone()["id"]

    id_a, path_a = _insert_file(conn, root, "a.stl", ".stl", "hash-a", subdir="World Map/1_Europe")
    suggest_folder_project(conn, id_a, path_a, root)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE projects SET parent_project_id = %s WHERE name = '1_Europe'",
            (manual_parent_id,),
        )

    id_b, path_b = _insert_file(conn, root, "b.stl", ".stl", "hash-b", subdir="World Map/2_Asia")
    suggest_folder_project(conn, id_b, path_b, root)

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT parent_project_id FROM projects WHERE name = '1_Europe'")
        assert cur.fetchone()["parent_project_id"] == manual_parent_id  # untouched
