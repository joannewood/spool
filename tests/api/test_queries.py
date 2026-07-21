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


# ---- processing status dashboard (/admin/status) --------------------------
# Session-scoped test DB means other tests' job rows may already be present,
# so these check deltas/presence of specifically-inserted rows rather than
# exact whole-table counts.

def test_get_job_queue_summary_reflects_a_new_job(make_file, db_conn):
    file_id = make_file(filename="status-summary.stl")

    def count_for(job_type, status):
        return next(
            (row["n"] for row in queries.get_job_queue_summary() if row["job_type"] == job_type and row["status"] == status),
            0,
        )

    before = count_for("ingest", "done")
    with db_conn.cursor() as cur:
        cur.execute("INSERT INTO jobs (file_id, job_type, status) VALUES (%s, 'ingest', 'done')", (file_id,))
    assert count_for("ingest", "done") == before + 1


def test_get_running_jobs_includes_a_running_job_with_target_name(make_file, db_conn):
    file_id = make_file(filename="status-running-unique.stl")
    with db_conn.cursor() as cur:
        cur.execute("INSERT INTO jobs (file_id, job_type, status) VALUES (%s, 'render', 'running')", (file_id,))

    running = queries.get_running_jobs()
    assert any(j["target_name"] == "status-running-unique.stl" for j in running)


def test_get_recent_job_activity_includes_a_finished_job_with_error(make_file, db_conn):
    file_id = make_file(filename="status-activity-unique.stl")
    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO jobs (file_id, job_type, status, error, completed_at) "
            "VALUES (%s, 'render', 'failed', %s, now())",
            (file_id, "status dashboard test error"),
        )

    recent = queries.get_recent_job_activity(limit=200)
    match = next((j for j in recent if j["target_name"] == "status-activity-unique.stl"), None)
    assert match is not None
    assert match["error"] == "status dashboard test error"


def test_get_recent_job_activity_filters_by_q(make_file, db_conn):
    match_id = make_file(filename="query-filter-unique.stl")
    other_id = make_file(filename="query-filter-nomatch.stl")
    with db_conn.cursor() as cur:
        cur.execute("INSERT INTO jobs (file_id, job_type, status) VALUES (%s, 'render', 'done')", (match_id,))
        cur.execute("INSERT INTO jobs (file_id, job_type, status) VALUES (%s, 'render', 'done')", (other_id,))

    recent = queries.get_recent_job_activity(limit=200, q="query-filter-unique")
    target_names = {j["target_name"] for j in recent}
    assert target_names == {"query-filter-unique.stl"}


def test_get_recent_job_activity_filters_by_status(make_file, db_conn):
    file_id = make_file(filename="query-filter-status.stl")
    with db_conn.cursor() as cur:
        cur.execute("INSERT INTO jobs (file_id, job_type, status) VALUES (%s, 'render', 'done')", (file_id,))
        cur.execute(
            "INSERT INTO jobs (file_id, job_type, status, error) VALUES (%s, 'ingest', 'failed', 'x')",
            (file_id,),
        )

    recent = queries.get_recent_job_activity(limit=200, q="query-filter-status", status="failed")
    assert len(recent) == 1
    assert recent[0]["job_type"] == "ingest"
    assert recent[0]["status"] == "failed"


def test_get_recent_job_activity_filters_by_job_type(make_file, db_conn):
    file_id = make_file(filename="query-filter-jobtype.stl")
    with db_conn.cursor() as cur:
        cur.execute("INSERT INTO jobs (file_id, job_type, status) VALUES (%s, 'render', 'done')", (file_id,))
        cur.execute("INSERT INTO jobs (file_id, job_type, status) VALUES (%s, 'ingest', 'done')", (file_id,))

    recent = queries.get_recent_job_activity(limit=200, q="query-filter-jobtype", job_type="render")
    assert len(recent) == 1
    assert recent[0]["job_type"] == "render"


def test_get_ingestion_totals_reflects_an_unhashed_file(make_file):
    before = queries.get_ingestion_totals()
    make_file(filename="status-totals-unique.stl", content_hash=None)
    after = queries.get_ingestion_totals()
    assert after["total_files"] == before["total_files"] + 1
    assert after["unhashed"] == before["unhashed"] + 1


# ---- bulk-review pagination + batched confirm ------------------------------
# Session-scoped test DB may already hold other tests' suggested rows, so
# these use a small explicit page_size rather than the 100-row default, and
# check deltas/specific-row-presence rather than exact whole-table counts.

def test_list_suggested_project_assignments_paginates(make_file, db_conn):
    project_id = queries.create_project("Pagination Test Project", "", None)
    try:
        file_ids = [make_file(filename=f"pagination-test-{i}.stl") for i in range(5)]
        with db_conn.cursor() as cur:
            for file_id in file_ids:
                cur.execute(
                    "INSERT INTO project_files (project_id, file_id, status) VALUES (%s, %s, 'suggested')",
                    (project_id, file_id),
                )

        page1, total = queries.list_suggested_project_assignments(page=1, page_size=2)
        assert total >= 5
        assert len(page1) == 2

        page3, total_again = queries.list_suggested_project_assignments(page=3, page_size=2)
        assert total_again == total
        assert len(page3) >= 1  # at least the 5th of our own rows lands here
    finally:
        with db_conn.cursor() as cur:
            cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))


def test_confirm_file_projects_bulk_confirms_every_pair_in_one_call(make_file, db_conn):
    project_a = queries.create_project("Bulk Confirm A", "", None)
    project_b = queries.create_project("Bulk Confirm B", "", None)
    file_a = make_file(filename="bulk-confirm-a.stl")
    file_b = make_file(filename="bulk-confirm-b.stl")
    try:
        with db_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO project_files (project_id, file_id, status) VALUES (%s, %s, 'suggested')",
                (project_a, file_a),
            )
            cur.execute(
                "INSERT INTO project_files (project_id, file_id, status) VALUES (%s, %s, 'suggested')",
                (project_b, file_b),
            )

        queries.confirm_file_projects_bulk([(file_a, project_a), (file_b, project_b)])

        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT status FROM project_files WHERE (file_id, project_id) IN ((%s, %s), (%s, %s))",
                (file_a, project_a, file_b, project_b),
            )
            statuses = {row[0] for row in cur.fetchall()}
        assert statuses == {"confirmed"}
    finally:
        with db_conn.cursor() as cur:
            cur.execute("DELETE FROM projects WHERE id IN (%s, %s)", (project_a, project_b))


def test_confirm_relationships_bulk_confirms_every_id_in_one_call(make_file, db_conn):
    file_a = make_file()
    file_b = make_file()
    file_c = make_file()
    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO relationships (from_file_id, to_file_id, type, status) VALUES (%s, %s, 'variant_of', 'suggested') RETURNING id",
            (file_a, file_b),
        )
        rel_1 = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO relationships (from_file_id, to_file_id, type, status) VALUES (%s, %s, 'variant_of', 'suggested') RETURNING id",
            (file_b, file_c),
        )
        rel_2 = cur.fetchone()[0]

    queries.confirm_relationships_bulk([rel_1, rel_2])

    with db_conn.cursor() as cur:
        cur.execute("SELECT status FROM relationships WHERE id IN (%s, %s)", (rel_1, rel_2))
        statuses = {row[0] for row in cur.fetchall()}
    assert statuses == {"confirmed"}


def test_list_duplicate_groups_paginates_by_group(make_file):
    make_file(filename="dup-page-a1.stl", content_hash="duppage-hash-1")
    make_file(filename="dup-page-a2.stl", content_hash="duppage-hash-1")
    make_file(filename="dup-page-b1.stl", content_hash="duppage-hash-2")
    make_file(filename="dup-page-b2.stl", content_hash="duppage-hash-2")

    page1, total = queries.list_duplicate_groups(page=1, page_size=1)
    assert total >= 2
    assert len(page1) == 1


def test_list_pending_zips_paginates(db_conn, test_root_id):
    zip_ids = []
    try:
        with db_conn.cursor() as cur:
            for i in range(3):
                cur.execute(
                    "INSERT INTO zip_files (watched_root_id, path, filename, size_bytes) VALUES (%s, %s, %s, 100) RETURNING id",
                    (test_root_id, f"/tmp/api-test-root/PagingZip{i}.zip", f"PagingZip{i}.zip"),
                )
                zip_ids.append(cur.fetchone()[0])

        page1, total = queries.list_pending_zips(page=1, page_size=2)
        assert total >= 3
        assert len(page1) == 2
    finally:
        with db_conn.cursor() as cur:
            cur.execute("DELETE FROM zip_files WHERE id = ANY(%s)", (zip_ids,))


def test_enqueue_zip_extractions_bulk_queues_every_zip_in_one_call(db_conn, test_root_id):
    zip_ids = []
    try:
        with db_conn.cursor() as cur:
            for i in range(2):
                cur.execute(
                    "INSERT INTO zip_files (watched_root_id, path, filename, size_bytes) VALUES (%s, %s, %s, 100) RETURNING id",
                    (test_root_id, f"/tmp/api-test-root/BulkExtract{i}.zip", f"BulkExtract{i}.zip"),
                )
                zip_ids.append(cur.fetchone()[0])

        queries.enqueue_zip_extractions_bulk(zip_ids)

        with db_conn.cursor() as cur:
            cur.execute("SELECT status FROM zip_files WHERE id = ANY(%s)", (zip_ids,))
            statuses = {row[0] for row in cur.fetchall()}
            assert statuses == {"confirmed"}
            cur.execute("SELECT count(*) FROM jobs WHERE zip_file_id = ANY(%s) AND job_type = 'extract_zip'", (zip_ids,))
            assert cur.fetchone()[0] == 2
    finally:
        with db_conn.cursor() as cur:
            cur.execute("DELETE FROM zip_files WHERE id = ANY(%s)", (zip_ids,))


# ---- "all" page size (no LIMIT/OFFSET) --------------------------------------

def test_list_suggested_project_assignments_page_size_all_returns_everything(make_file, db_conn):
    project_id = queries.create_project("All Page Size Project", "", None)
    try:
        file_ids = [make_file(filename=f"all-page-size-{i}.stl") for i in range(3)]
        with db_conn.cursor() as cur:
            for file_id in file_ids:
                cur.execute(
                    "INSERT INTO project_files (project_id, file_id, status) VALUES (%s, %s, 'suggested')",
                    (project_id, file_id),
                )

        rows, total = queries.list_suggested_project_assignments(page=1, page_size="all")
        assert len(rows) == total  # every suggested row in the library, not just a page
        assert total >= 3
    finally:
        with db_conn.cursor() as cur:
            cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))


def test_list_duplicate_groups_page_size_all_returns_every_group(make_file):
    make_file(filename="all-dup-a1.stl", content_hash="all-dup-hash-1")
    make_file(filename="all-dup-a2.stl", content_hash="all-dup-hash-1")

    groups, total = queries.list_duplicate_groups(page=1, page_size="all")
    assert len(groups) == total
