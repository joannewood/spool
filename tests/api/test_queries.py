import pytest

from spool_api import queries


# ---- _structured_metadata_clauses (pure, no DB) ----------------------------

def test_structured_metadata_clauses_matches_nozzle_phrasing():
    clauses, params = queries._structured_metadata_clauses("0.2mm nozzle")
    assert len(clauses) == 1
    assert params == pytest.approx([0.195, 0.205])


def test_structured_metadata_clauses_matches_reversed_phrasing():
    clauses, params = queries._structured_metadata_clauses("nozzle 0.2mm")
    assert len(clauses) == 1
    assert params == pytest.approx([0.195, 0.205])


def test_structured_metadata_clauses_matches_infill_percent():
    clauses, params = queries._structured_metadata_clauses("20% infill")
    assert len(clauses) == 1
    assert params == [19.5, 20.5]


def test_structured_metadata_clauses_no_keyword_no_match():
    clauses, params = queries._structured_metadata_clauses("just a plain search")
    assert clauses == []
    assert params == []


def test_structured_metadata_clauses_keyword_without_number_no_match():
    clauses, params = queries._structured_metadata_clauses("nozzle problems")
    assert clauses == []
    assert params == []


# ---- files ------------------------------------------------------------------

def test_get_file_returns_none_for_missing_id(db_conn):
    assert queries.get_file(999999999) is None


def test_get_file_returns_the_row(make_file):
    file_id = make_file(filename="widget.stl")
    file = queries.get_file(file_id)
    assert file["filename"] == "widget.stl"
    assert file["display_name"] is None


def test_set_display_name_then_get_file(make_file):
    file_id = make_file()
    queries.set_display_name(file_id, "My Widget")
    assert queries.get_file(file_id)["display_name"] == "My Widget"


def test_set_display_name_empty_string_clears_it(make_file):
    file_id = make_file()
    queries.set_display_name(file_id, "My Widget")
    queries.set_display_name(file_id, "")
    assert queries.get_file(file_id)["display_name"] is None


# ---- tags ---------------------------------------------------------------

def test_add_and_remove_tag(make_file):
    file_id = make_file()
    queries.add_tag_to_file(file_id, "Miniature")

    tags = queries.get_file_tags(file_id)
    assert [t["name"] for t in tags] == ["miniature"]  # normalized to lowercase

    queries.remove_tag_from_file(file_id, tags[0]["id"])
    assert queries.get_file_tags(file_id) == []


def test_add_tag_reuses_existing_tag_row(make_file):
    file_a = make_file()
    file_b = make_file()
    queries.add_tag_to_file(file_a, "shared")
    queries.add_tag_to_file(file_b, "shared")

    tag_a = queries.get_file_tags(file_a)[0]
    tag_b = queries.get_file_tags(file_b)[0]
    assert tag_a["id"] == tag_b["id"]  # same tag row, not duplicated


# ---- projects -----------------------------------------------------------

def test_create_and_rename_project(db_conn):
    project_id = queries.create_project("Original Name", "", None)
    try:
        assert queries.get_project(project_id)["name"] == "Original Name"
        queries.set_project_name(project_id, "Renamed")
        assert queries.get_project(project_id)["name"] == "Renamed"
    finally:
        with db_conn.cursor() as cur:
            cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))


def test_add_file_to_project_and_back(make_file, db_conn):
    file_id = make_file()
    project_id = queries.create_project("Test Project", "", None)
    try:
        queries.add_file_to_project(file_id, project_id)
        projects = queries.get_file_projects(file_id)
        assert [p["id"] for p in projects] == [project_id]

        queries.remove_file_from_project(file_id, project_id)
        assert queries.get_file_projects(file_id) == []
    finally:
        with db_conn.cursor() as cur:
            cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))


# ---- print metadata (regression coverage for the None-literal bug) --------

def test_print_metadata_partial_fields_stay_none_not_string(make_file, db_conn):
    file_id = make_file()
    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO print_metadata (file_id, material, source) VALUES (%s, %s, 'manual')",
            (file_id, "PLA"),
        )
    metadata = queries.get_print_metadata(file_id)
    assert metadata["material"] == "PLA"
    assert metadata["notes"] is None  # real None, not the string "None"
    assert metadata["printer_profile"] is None


# ---- search relevance ranking ---------------------------------------------

def test_search_ranks_prefix_match_above_substring_match(make_file):
    # Neither is "newest" in a way that would otherwise explain the order —
    # the substring match is inserted first, so a plain sort-by-recency
    # would put it ahead were relevance not doing the real ordering.
    substring_id = make_file(filename="dessicantcontainer-top.stl")
    prefix_id = make_file(filename="Top.stl")

    rows, _ = queries.search_files(q="top", extensions=None, tags=None, page=1)
    ids = [r["id"] for r in rows]
    assert ids.index(prefix_id) < ids.index(substring_id)


def test_search_ranks_name_match_above_metadata_only_match(make_file, db_conn):
    metadata_only_id = make_file(filename="widgetA.stl")
    name_match_id = make_file(filename="findme-in-name.stl")
    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO print_metadata (file_id, material, source) VALUES (%s, %s, 'manual')",
            (metadata_only_id, "findme material"),
        )

    rows, _ = queries.search_files(q="findme", extensions=None, tags=None, page=1)
    ids = [r["id"] for r in rows]
    assert ids.index(name_match_id) < ids.index(metadata_only_id)


def test_search_without_query_does_not_apply_relevance_ranking(make_file):
    # No q means no relevance CASE at all — just confirm the plain sort
    # clause still runs without error and returns both rows.
    a = make_file(filename="alpha.stl")
    b = make_file(filename="beta.stl")
    rows, total = queries.search_files(q="", extensions=None, tags=None, page=1, sort="name_asc")
    ids = {r["id"] for r in rows}
    assert {a, b} <= ids


# ---- project associations surfaced on search/browse results ---------------

def test_search_attaches_project_membership_to_each_row(make_file, db_conn):
    grouped_a = make_file(filename="groupwidget-shared-project-a.stl")
    grouped_b = make_file(filename="groupwidget-shared-project-b.stl")
    ungrouped = make_file(filename="groupwidget-lonesome.stl")
    project_id = queries.create_project("Shared Test Project", "", None)
    try:
        queries.add_file_to_project(grouped_a, project_id)
        queries.add_file_to_project(grouped_b, project_id)

        rows, _ = queries.search_files(q="groupwidget", extensions=None, tags=None, page=1)
        by_id = {r["id"]: r for r in rows}

        assert [p["name"] for p in by_id[grouped_a]["projects"]] == ["Shared Test Project"]
        assert [p["name"] for p in by_id[grouped_b]["projects"]] == ["Shared Test Project"]
        assert by_id[ungrouped]["projects"] == []
    finally:
        with db_conn.cursor() as cur:
            cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))


def test_search_only_shows_confirmed_project_membership(make_file, db_conn):
    file_id = make_file(filename="suggestedwidget.stl")
    project_id = queries.create_project("Suggested-Only Project", "", None)
    try:
        with db_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO project_files (project_id, file_id, status) VALUES (%s, %s, 'suggested')",
                (project_id, file_id),
            )
        rows, _ = queries.search_files(q="suggestedwidget", extensions=None, tags=None, page=1)
        assert rows[0]["projects"] == []
    finally:
        with db_conn.cursor() as cur:
            cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))


def test_get_project_files_attaches_project_memberships(make_file, db_conn):
    # Same file-card component as the library grid (get_project_files uses
    # the same _attach_project_memberships helper as search_files) — a
    # file can belong to more than one project, and this page needs to
    # know about all of them, not just the one it's currently showing.
    project_a = queries.create_project("Project A", "", None)
    project_b = queries.create_project("Project B", "", None)
    file_id = make_file(filename="multiproject.stl")
    try:
        queries.add_file_to_project(file_id, project_a)
        queries.add_file_to_project(file_id, project_b)

        rows = queries.get_project_files(project_a)
        names = {p["name"] for p in rows[0]["projects"]}
        assert names == {"Project A", "Project B"}
    finally:
        with db_conn.cursor() as cur:
            cur.execute("DELETE FROM projects WHERE id IN (%s, %s)", (project_a, project_b))


# ---- render error surfacing -------------------------------------------------

def test_get_latest_render_error_returns_none_when_no_failed_job(make_file):
    file_id = make_file()
    assert queries.get_latest_render_error(file_id) is None


def test_get_latest_render_error_returns_most_recent(make_file, db_conn):
    file_id = make_file(render_status="failed")
    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO jobs (file_id, job_type, status, error, completed_at) "
            "VALUES (%s, 'render', 'failed', %s, now() - interval '1 hour')",
            (file_id, "first, older failure"),
        )
        cur.execute(
            "INSERT INTO jobs (file_id, job_type, status, error, completed_at) "
            "VALUES (%s, 'render', 'failed', %s, now())",
            (file_id, "second, newer failure"),
        )
    assert queries.get_latest_render_error(file_id) == "second, newer failure"


def test_search_files_attaches_render_error_only_for_failed(make_file, db_conn):
    failed_id = make_file(filename="broken.3mf", render_status="failed")
    ok_id = make_file(filename="fine.stl", render_status="done")
    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO jobs (file_id, job_type, status, error) VALUES (%s, 'render', 'failed', %s)",
            (failed_id, "3MF's inner mesh data is 99,000,000 bytes uncompressed, over the 12,000,000-byte safety limit"),
        )
    rows, _ = queries.search_files(q="broken", extensions=None, tags=None, page=1)
    assert rows[0]["render_error"].startswith("3MF's inner mesh data")

    rows, _ = queries.search_files(q="fine", extensions=None, tags=None, page=1)
    assert rows[0]["render_error"] is None
