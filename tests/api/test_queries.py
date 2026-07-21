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

    before = count_for("ingest", "queued")
    with db_conn.cursor() as cur:
        cur.execute("INSERT INTO jobs (file_id, job_type, status) VALUES (%s, 'ingest', 'queued')", (file_id,))
    assert count_for("ingest", "queued") == before + 1


def test_get_job_queue_summary_excludes_done_and_failed(make_file, db_conn):
    # done/failed jobs are never deleted, so counting them here would be an
    # ever-growing lifetime total, not useful live-queue state — confirmed
    # via direct user feedback that the old done/failed columns "don't make
    # sense" on a live dashboard. Only queued/running should ever appear.
    file_id = make_file(filename="status-summary-lifetime.stl")
    with db_conn.cursor() as cur:
        cur.execute("INSERT INTO jobs (file_id, job_type, status) VALUES (%s, 'render', 'done')", (file_id,))
        cur.execute("INSERT INTO jobs (file_id, job_type, status) VALUES (%s, 'render', 'failed')", (file_id,))
    statuses = {row["status"] for row in queries.get_job_queue_summary()}
    assert "done" not in statuses
    assert "failed" not in statuses


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

    recent, _ = queries.get_recent_job_activity(page_size=200)
    match = next((j for j in recent if j["target_name"] == "status-activity-unique.stl"), None)
    assert match is not None
    assert match["error"] == "status dashboard test error"


def test_get_recent_job_activity_filters_by_q(make_file, db_conn):
    match_id = make_file(filename="query-filter-unique.stl")
    other_id = make_file(filename="query-filter-nomatch.stl")
    with db_conn.cursor() as cur:
        cur.execute("INSERT INTO jobs (file_id, job_type, status) VALUES (%s, 'render', 'done')", (match_id,))
        cur.execute("INSERT INTO jobs (file_id, job_type, status) VALUES (%s, 'render', 'done')", (other_id,))

    recent, _ = queries.get_recent_job_activity(page_size=200, q="query-filter-unique")
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

    recent, _ = queries.get_recent_job_activity(page_size=200, q="query-filter-status", status="failed")
    assert len(recent) == 1
    assert recent[0]["job_type"] == "ingest"
    assert recent[0]["status"] == "failed"


def test_get_recent_job_activity_filters_by_job_type(make_file, db_conn):
    file_id = make_file(filename="query-filter-jobtype.stl")
    with db_conn.cursor() as cur:
        cur.execute("INSERT INTO jobs (file_id, job_type, status) VALUES (%s, 'render', 'done')", (file_id,))
        cur.execute("INSERT INTO jobs (file_id, job_type, status) VALUES (%s, 'ingest', 'done')", (file_id,))

    recent, _ = queries.get_recent_job_activity(page_size=200, q="query-filter-jobtype", job_type="render")
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


# ---- delete_files_bulk also removes thumbnails (orphan-cleanup fix) -------

def test_delete_files_bulk_removes_thumbnails(make_file):
    import os

    os.makedirs(queries.THUMBNAILS_DIR, exist_ok=True)
    thumbnail_filenames = ["delete-bulk-thumb-1.png", "delete-bulk-thumb-2.png"]
    thumbnail_paths = [os.path.join(queries.THUMBNAILS_DIR, name) for name in thumbnail_filenames]
    for path in thumbnail_paths:
        with open(path, "wb") as f:
            f.write(b"fake png bytes")

    file_a = make_file(filename="delete-bulk-a.stl", thumbnail_path=thumbnail_filenames[0])
    file_b = make_file(filename="delete-bulk-b.stl", thumbnail_path=thumbnail_filenames[1])
    assert all(os.path.exists(p) for p in thumbnail_paths)

    queries.delete_files_bulk([file_a, file_b])

    assert queries.get_file(file_a) is None
    assert queries.get_file(file_b) is None
    assert not any(os.path.exists(p) for p in thumbnail_paths)


def test_delete_files_bulk_tolerates_a_missing_thumbnail_file(make_file):
    # thumbnail_path points at a file that was already gone from disk —
    # the delete must still succeed (best-effort cleanup, not required).
    file_id = make_file(filename="delete-bulk-no-thumb.stl", thumbnail_path="does-not-exist-on-disk.png")
    queries.delete_files_bulk([file_id])
    assert queries.get_file(file_id) is None


def test_delete_files_bulk_handles_no_thumbnail_at_all(make_file):
    file_id = make_file(filename="delete-bulk-null-thumb.stl")  # thumbnail_path defaults to NULL
    queries.delete_files_bulk([file_id])
    assert queries.get_file(file_id) is None


def test_delete_files_bulk_handles_empty_list():
    queries.delete_files_bulk([])  # must not raise


# ---- orphaned empty project cleanup ----------------------------------------
# Deleting a file (or manually removing it from a project) can leave an
# auto-created project with zero members — confirmed live as a real,
# accumulating bug (349 orphaned projects), usually from duplicate-file
# cleanup deleting the only file in a project created for what turned out
# to be a duplicate download's own folder.

def _make_auto_project(db_conn, source_folder_path):
    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO projects (name, source_folder_path) VALUES (%s, %s) RETURNING id",
            (source_folder_path, source_folder_path),
        )
        return cur.fetchone()[0]


def test_remove_file_from_project_deletes_now_empty_auto_created_project(make_file, db_conn):
    project_id = _make_auto_project(db_conn, "/tmp/orphan-test/auto-a")
    file_id = make_file(filename="orphan-remove-auto.stl")
    queries.add_file_to_project(file_id, project_id)

    queries.remove_file_from_project(file_id, project_id)

    with db_conn.cursor() as cur:
        cur.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
        assert cur.fetchone() is None


def test_remove_file_from_project_keeps_empty_manually_created_project(make_file, db_conn):
    project_id = queries.create_project("Manually made project", "", None)
    file_id = make_file(filename="orphan-remove-manual.stl")
    queries.add_file_to_project(file_id, project_id)

    queries.remove_file_from_project(file_id, project_id)

    try:
        assert queries.get_project(project_id) is not None
    finally:
        # db_conn is autocommit (no rollback), same as the app's own
        # connection style — this test's whole point is that the project
        # survives, so it has to clean up after itself explicitly rather
        # than relying on transaction rollback, same as make_file's own
        # teardown convention (tests/api/conftest.py).
        with db_conn.cursor() as cur:
            cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))


def test_remove_file_from_project_keeps_auto_created_project_with_remaining_members(make_file, db_conn):
    project_id = _make_auto_project(db_conn, "/tmp/orphan-test/auto-b")
    file_a = make_file(filename="orphan-remove-sibling-a.stl")
    file_b = make_file(filename="orphan-remove-sibling-b.stl")
    queries.add_file_to_project(file_a, project_id)
    queries.add_file_to_project(file_b, project_id)

    queries.remove_file_from_project(file_a, project_id)

    try:
        with db_conn.cursor() as cur:
            cur.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
            assert cur.fetchone() is not None
    finally:
        with db_conn.cursor() as cur:
            cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))


def test_delete_files_bulk_deletes_now_empty_auto_created_project(make_file, db_conn):
    project_id = _make_auto_project(db_conn, "/tmp/orphan-test/auto-c")
    file_id = make_file(filename="orphan-delete-bulk-auto.stl")
    queries.add_file_to_project(file_id, project_id)

    queries.delete_files_bulk([file_id])

    with db_conn.cursor() as cur:
        cur.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
        assert cur.fetchone() is None


def test_delete_files_bulk_deletes_project_whose_only_membership_was_never_confirmed(make_file, db_conn):
    # The exact real-world sequence this guards against: suggest_folder_
    # project creates the project with a 'suggested' (not 'confirmed')
    # project_files row, and the file turns out to be a duplicate that
    # gets deleted before anyone ever reviews/accepts that suggestion —
    # the project must still be cleaned up, not just when the membership
    # was confirmed first.
    project_id = _make_auto_project(db_conn, "/tmp/orphan-test/auto-e")
    file_id = make_file(filename="orphan-delete-bulk-suggested-only.stl")
    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO project_files (project_id, file_id, status) VALUES (%s, %s, 'suggested')",
            (project_id, file_id),
        )

    queries.delete_files_bulk([file_id])

    with db_conn.cursor() as cur:
        cur.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
        assert cur.fetchone() is None


def test_delete_files_bulk_keeps_auto_created_project_with_remaining_members(make_file, db_conn):
    project_id = _make_auto_project(db_conn, "/tmp/orphan-test/auto-d")
    file_a = make_file(filename="orphan-delete-bulk-sibling-a.stl")
    file_b = make_file(filename="orphan-delete-bulk-sibling-b.stl")
    queries.add_file_to_project(file_a, project_id)
    queries.add_file_to_project(file_b, project_id)

    queries.delete_files_bulk([file_a])

    try:
        with db_conn.cursor() as cur:
            cur.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
            assert cur.fetchone() is not None
    finally:
        with db_conn.cursor() as cur:
            cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))


def test_get_files_bulk_returns_dict_keyed_by_id(make_file):
    file_a = make_file(filename="get-bulk-a.stl")
    file_b = make_file(filename="get-bulk-b.stl")

    result = queries.get_files_bulk([file_a, file_b, 999999999])

    assert set(result.keys()) == {file_a, file_b}
    assert result[file_a]["filename"] == "get-bulk-a.stl"


def test_get_files_bulk_handles_empty_list():
    assert queries.get_files_bulk([]) == {}


# ---- bulk project-name cleanup ---------------------------------------------

def test_list_projects_needing_name_cleanup_includes_a_messy_name():
    project_id = queries.create_project("bulk-rename-messy-model_files", "", None)
    try:
        suggestions, total = queries.list_projects_needing_name_cleanup(page_size="all")
        match = next((s for s in suggestions if s["id"] == project_id), None)
        assert match is not None
        assert match["suggested_name"] == "Bulk Rename Messy"
        assert total >= 1
    finally:
        with queries.get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))


def test_list_projects_needing_name_cleanup_excludes_already_clean_names():
    project_id = queries.create_project("Already Clean Name", "", None)
    try:
        suggestions, _ = queries.list_projects_needing_name_cleanup(page_size="all")
        assert not any(s["id"] == project_id for s in suggestions)
    finally:
        with queries.get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))


def test_rename_projects_bulk_applies_selected_renames():
    project_id = queries.create_project("rename-me-model_files", "", None)
    try:
        queries.rename_projects_bulk([(project_id, "Renamed Project")])
        assert queries.get_project(project_id)["name"] == "Renamed Project"
    finally:
        with queries.get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))


def test_rename_projects_bulk_skips_blank_new_name():
    project_id = queries.create_project("keep-original-model_files", "", None)
    try:
        queries.rename_projects_bulk([(project_id, "   ")])
        assert queries.get_project(project_id)["name"] == "keep-original-model_files"
    finally:
        with queries.get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))


def test_rename_projects_bulk_handles_empty_list():
    queries.rename_projects_bulk([])  # must not raise
