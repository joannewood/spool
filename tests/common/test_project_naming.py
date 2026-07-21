from common.project_naming import unique_project_name


def _make_project(conn, name, source_folder_path=None):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO projects (name, source_folder_path) VALUES (%s, %s) RETURNING id",
            (name, source_folder_path),
        )
        return cur.fetchone()[0]


def test_unique_project_name_returns_name_unchanged_when_available(conn):
    with conn.cursor() as cur:
        assert unique_project_name(cur, "Brand New Name") == "Brand New Name"


def test_unique_project_name_disambiguates_with_parent_folder(conn):
    _make_project(conn, "Widget")
    with conn.cursor() as cur:
        result = unique_project_name(cur, "Widget", directory="/root/Some Kit/Widget")
    assert result == "Widget (Some Kit)"


def test_unique_project_name_falls_back_to_numeric_suffix_without_a_directory(conn):
    _make_project(conn, "Widget")
    with conn.cursor() as cur:
        result = unique_project_name(cur, "Widget")
    assert result == "Widget (2)"


def test_unique_project_name_falls_back_to_numeric_suffix_when_parent_qualified_name_also_collides(conn):
    _make_project(conn, "Widget")
    _make_project(conn, "Widget (Some Kit)")
    with conn.cursor() as cur:
        result = unique_project_name(cur, "Widget", directory="/root/Some Kit/Widget")
    assert result == "Widget (Some Kit) (2)"


def test_unique_project_name_exclude_id_lets_a_project_keep_its_own_name(conn):
    project_id = _make_project(conn, "Widget")
    with conn.cursor() as cur:
        result = unique_project_name(cur, "Widget", exclude_id=project_id)
    assert result == "Widget"  # not treated as colliding with itself


def test_unique_project_name_exclude_id_still_disambiguates_against_others(conn):
    other_id = _make_project(conn, "Widget")
    renaming_id = _make_project(conn, "Something Else")
    with conn.cursor() as cur:
        result = unique_project_name(cur, "Widget", exclude_id=renaming_id)
    assert result == "Widget (2)"
    assert other_id != renaming_id
