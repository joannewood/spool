def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "database": "connected"}


def test_file_detail_404_for_missing_file(client):
    resp = client.get("/files/999999999")
    assert resp.status_code == 404


def test_file_detail_200_for_real_file(client, make_file):
    file_id = make_file(filename="widget.stl")
    resp = client.get(f"/files/{file_id}")
    assert resp.status_code == 200
    assert "widget.stl" in resp.text


def test_file_detail_thumbnail_url_is_content_hash_versioned(client, make_file):
    file_id = make_file(filename="widget.stl", thumbnail_path=f"widget.png", content_hash="abcdef1234567890")
    resp = client.get(f"/files/{file_id}")
    assert resp.status_code == 200
    assert '/thumbnails/widget.png?v=abcdef12"' in resp.text


def test_file_detail_shows_render_error_reason_not_bare_failed(client, make_file, db_conn):
    file_id = make_file(filename="broken.3mf", render_status="failed")
    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO jobs (file_id, job_type, status, error) VALUES (%s, 'render', 'failed', %s)",
            (file_id, "3MF has 166 <item>/<component> build references, over the 60-reference safety limit"),
        )
    resp = client.get(f"/files/{file_id}")
    assert resp.status_code == 200
    assert "Too complex to render" in resp.text
    assert "60-reference safety limit" in resp.text  # raw reason surfaced in the footer too


def test_cached_static_files_sets_long_cache_control(tmp_path):
    # Tested against a standalone Starlette app rather than the real
    # /thumbnails mount, so this doesn't depend on a real thumbnail
    # existing on disk or on mutating the shared app's routing.
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from spool_api.main import CachedStaticFiles

    (tmp_path / "test-thumb.png").write_bytes(b"fake-png-bytes")

    probe_app = FastAPI()
    probe_app.mount("/thumbnails", CachedStaticFiles(directory=str(tmp_path)), name="thumbnails")
    probe_client = TestClient(probe_app)

    resp = probe_client.get("/thumbnails/test-thumb.png")
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_index_page_loads(client):
    resp = client.get("/")
    assert resp.status_code == 200


def test_index_search_by_filename(client, make_file):
    file_id = make_file(filename="findme-unique-xyz.stl")
    resp = client.get("/?q=findme-unique-xyz")
    assert resp.status_code == 200
    assert "findme-unique-xyz.stl" in resp.text


# ---- regression: None must never render as literal text -------------------

def test_file_detail_does_not_render_none_for_null_metadata_fields(client, make_file, db_conn):
    file_id = make_file()
    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO print_metadata (file_id, material) VALUES (%s, 'PLA')",
            (file_id,),
        )
    resp = client.get(f"/files/{file_id}")
    assert resp.status_code == 200
    # material is set, but printer/slicer/notes are NULL — none of them
    # should render as the literal text "None" in their form fields.
    assert ">None<" not in resp.text
    assert "None</textarea>" not in resp.text
    assert 'value="None"' not in resp.text


# ---- display name -----------------------------------------------------------

def test_set_display_name_round_trip(client, make_file):
    file_id = make_file(filename="original.stl")
    resp = client.post(f"/files/{file_id}/name", data={"display_name": "Friendly Name"}, follow_redirects=False)
    assert resp.status_code == 303

    detail = client.get(f"/files/{file_id}")
    assert "Friendly Name" in detail.text


# ---- tags ---------------------------------------------------------------

def test_add_and_remove_tag_via_routes(client, make_file):
    file_id = make_file()
    resp = client.post(f"/files/{file_id}/tags", data={"name": "cool-tag"}, follow_redirects=False)
    assert resp.status_code == 303

    detail = client.get(f"/files/{file_id}")
    assert "cool-tag" in detail.text


def test_file_detail_tags_have_no_panel_header(client, make_file):
    file_id = make_file()
    resp = client.get(f"/files/{file_id}")
    assert "<h2>Tags</h2>" not in resp.text
    assert 'class="tag-chips"' in resp.text
    # Adding a tag opens a modal via an icon button, not an inline reveal.
    assert 'data-modal="add-tag-modal"' in resp.text
    assert 'id="add-tag-modal"' in resp.text


def test_file_detail_footer_has_rarely_needed_fields(client, make_file):
    file_id = make_file()
    resp = client.get(f"/files/{file_id}")
    assert '<footer class="detail-footer">' in resp.text
    assert "Render status" in resp.text
    assert "Manifold" in resp.text
    assert "Hash" in resp.text
    assert "First seen" in resp.text
    # and the main dl no longer carries them
    dl_start = resp.text.index("<dl>")
    dl_end = resp.text.index("</dl>", dl_start)
    main_dl = resp.text[dl_start:dl_end]
    assert "Render status" not in main_dl
    assert "Hash" not in main_dl


# ---- projects -----------------------------------------------------------

def test_create_project_and_view_it(client, db_conn):
    resp = client.post("/projects", data={"name": "Route Test Project", "description": ""}, follow_redirects=False)
    assert resp.status_code == 303
    project_id = resp.headers["location"].rsplit("/", 1)[-1]

    try:
        detail = client.get(f"/projects/{project_id}")
        assert detail.status_code == 200
        assert "Route Test Project" in detail.text
    finally:
        with db_conn.cursor() as cur:
            cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))


def test_rename_project_via_route(client, db_conn):
    from spool_api import queries

    project_id = queries.create_project("Before Rename", "", None)
    try:
        resp = client.post(f"/projects/{project_id}/name", data={"name": "After Rename"}, follow_redirects=False)
        assert resp.status_code == 303
        assert queries.get_project(project_id)["name"] == "After Rename"
    finally:
        with db_conn.cursor() as cur:
            cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))


def test_add_file_to_existing_project_via_route(client, make_file, db_conn):
    from spool_api import queries

    file_id = make_file(filename="add-existing-project.stl")
    project_id = queries.create_project("Existing Project", "", None)
    try:
        resp = client.post(f"/files/{file_id}/projects", data={"project_id": str(project_id)}, follow_redirects=False)
        assert resp.status_code == 303
        assert [p["id"] for p in queries.get_file_projects(file_id)] == [project_id]
    finally:
        with db_conn.cursor() as cur:
            cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))


def test_add_file_to_new_project_via_route(client, make_file, db_conn):
    # The "+ create new project…" <select> option (file_detail.html's
    # add-project-modal) posts project_id="__new__" alongside the typed
    # name instead of a real id — the route creates the project inline.
    from spool_api import queries

    file_id = make_file(filename="add-new-project.stl")
    resp = client.post(
        f"/files/{file_id}/projects",
        data={"project_id": "__new__", "new_project_name": "Brand New Project"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    projects = queries.get_file_projects(file_id)
    try:
        assert [p["name"] for p in projects] == ["Brand New Project"]
    finally:
        for p in projects:
            with db_conn.cursor() as cur:
                cur.execute("DELETE FROM projects WHERE id = %s", (p["id"],))


def test_add_file_to_new_project_with_blank_name_is_a_no_op(client, make_file):
    from spool_api import queries

    file_id = make_file(filename="add-new-project-blank.stl")
    resp = client.post(
        f"/files/{file_id}/projects",
        data={"project_id": "__new__", "new_project_name": "   "},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert queries.get_file_projects(file_id) == []


def test_project_detail_shows_other_project_but_not_its_own(client, make_file, db_conn):
    # The file card is the same shared component the library grid uses,
    # showing every confirmed project a file belongs to — except a
    # project's own page would just be showing its own name back at you
    # on every card, so the route filters that one out before rendering.
    from spool_api import queries

    project_a = queries.create_project("Current Project", "", None)
    project_b = queries.create_project("Other Project", "", None)
    file_id = make_file(filename="multiproject-route.stl")
    try:
        queries.add_file_to_project(file_id, project_a)
        queries.add_file_to_project(file_id, project_b)

        resp = client.get(f"/projects/{project_a}")
        assert resp.status_code == 200
        # "Current Project" legitimately appears elsewhere on its own page
        # (the <title>, the <h1>, the rename form's input value) — only
        # the *card badge* rendering is what should be filtered out.
        assert 'title="In project: Other Project"' in resp.text
        assert 'title="In project: Current Project"' not in resp.text
    finally:
        with db_conn.cursor() as cur:
            cur.execute("DELETE FROM projects WHERE id IN (%s, %s)", (project_a, project_b))


# ---- URL-encoded name cleanup shows up through the real route too --------

def test_index_grid_shows_cleaned_filename(client, make_file):
    file_id = make_file(filename="AAA+battery+tray.stl", path="/tmp/api-test-root/AAA+battery+tray.stl")
    resp = client.get("/?q=AAA%2Bbattery")
    assert resp.status_code == 200
    assert "AAA battery tray.stl" in resp.text
    assert "AAA+battery+tray.stl" not in resp.text


def test_admin_page_shows_cleaned_zip_filename(client, db_conn, test_root_id):
    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO zip_files (watched_root_id, path, filename, size_bytes) VALUES (%s, %s, %s, 100) RETURNING id",
            (test_root_id, "/tmp/api-test-root/Kit+Files.zip", "Kit+Files.zip"),
        )
        zip_id = cur.fetchone()[0]
    try:
        resp = client.get("/admin/pending-archives")
        assert resp.status_code == 200
        assert "<td>Kit Files.zip</td>" in resp.text
        # the raw path column intentionally stays uncleaned (real disk path
        # for verification), only the filename cell should be cleaned
        assert "<td>Kit+Files.zip</td>" not in resp.text
    finally:
        with db_conn.cursor() as cur:
            cur.execute("DELETE FROM zip_files WHERE id = %s", (zip_id,))


# ---- admin page: hide empty sections -------------------------------------

def test_admin_page_hides_duplicate_and_suggestions_sections_when_empty(client):
    resp = client.get("/admin")
    assert resp.status_code == 200
    assert "Duplicate files" not in resp.text
    assert "Suggestions" not in resp.text


def test_admin_page_shows_duplicate_section_when_duplicates_exist(client, make_file, db_conn):
    make_file(filename="a.stl", content_hash="shared-hash-xyz")
    make_file(filename="b.stl", content_hash="shared-hash-xyz")
    resp = client.get("/admin")
    assert resp.status_code == 200
    assert "Duplicate files" in resp.text
    assert "1 group" in resp.text


def test_admin_page_shows_suggestions_section_when_project_suggestion_exists(client, make_file, db_conn):
    from spool_api import queries

    file_id = make_file()
    project_id = queries.create_project("Suggestion Test Project", "", None)
    try:
        with db_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO project_files (project_id, file_id, status) VALUES (%s, %s, 'suggested')",
                (project_id, file_id),
            )
        resp = client.get("/admin")
        assert resp.status_code == 200
        assert "Suggestions" in resp.text
        assert "1 suggested project assignment" in resp.text
    finally:
        with db_conn.cursor() as cur:
            cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))


def test_admin_page_shows_suggestions_section_when_relationship_suggestion_exists(client, make_file, db_conn):
    file_a = make_file()
    file_b = make_file()
    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO relationships (from_file_id, to_file_id, type, status) VALUES (%s, %s, 'variant_of', 'suggested') RETURNING id",
            (file_a, file_b),
        )
        rel_id = cur.fetchone()[0]
    try:
        resp = client.get("/admin")
        assert resp.status_code == 200
        assert "Suggestions" in resp.text
        assert "1 suggested relationship" in resp.text
    finally:
        with db_conn.cursor() as cur:
            cur.execute("DELETE FROM relationships WHERE id = %s", (rel_id,))


# ---- admin page: archives section ----------------------------------------

def test_admin_page_hides_pending_archives_link_when_none_pending(client):
    resp = client.get("/admin")
    assert resp.status_code == 200
    assert "pending archive" not in resp.text.lower()


def test_admin_page_always_shows_rejected_archives_link(client):
    resp = client.get("/admin")
    assert resp.status_code == 200
    assert "View rejected archives" in resp.text


def test_admin_page_shows_pending_archives_link_when_present(client, db_conn, test_root_id):
    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO zip_files (watched_root_id, path, filename, size_bytes) VALUES (%s, %s, %s, 100) RETURNING id",
            (test_root_id, "/tmp/api-test-root/Somekit.zip", "Somekit.zip"),
        )
        zip_id = cur.fetchone()[0]
    try:
        resp = client.get("/admin")
        assert resp.status_code == 200
        assert "Review 1 pending archive" in resp.text
        assert "View rejected archives" in resp.text  # still there alongside it
    finally:
        with db_conn.cursor() as cur:
            cur.execute("DELETE FROM zip_files WHERE id = %s", (zip_id,))


def test_pending_archives_page_lists_zips_and_confirm_redirects_back(client, db_conn, test_root_id):
    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO zip_files (watched_root_id, path, filename, size_bytes) VALUES (%s, %s, %s, 100) RETURNING id",
            (test_root_id, "/tmp/api-test-root/NoModelHere.zip", "NoModelHere.zip"),
        )
        zip_id = cur.fetchone()[0]
    try:
        resp = client.get("/admin/pending-archives")
        assert resp.status_code == 200
        assert "NoModelHere.zip" in resp.text

        # confirming a zip with no real file on disk will error inside the
        # worker's own job processing, not this route — we're only checking
        # the redirect target here, not the extraction outcome
        resp = client.post(f"/admin/zips/{zip_id}/reject", follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/admin/pending-archives"
    finally:
        with db_conn.cursor() as cur:
            cur.execute("DELETE FROM zip_files WHERE id = %s", (zip_id,))


def test_pending_archives_page_has_select_all_and_no_nested_forms(client, db_conn, test_root_id):
    # Regression coverage for a real bug: a per-row action wrapped in its own
    # <form> nested inside the page's bulk-accept <form> is invalid HTML5 —
    # browsers drop the nested start tag, so the button silently submits the
    # OUTER bulk form instead of its own intended action. Buttons must use
    # formaction on a bare <button> living directly in the one outer form.
    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO zip_files (watched_root_id, path, filename, size_bytes) VALUES (%s, %s, %s, 100) RETURNING id",
            (test_root_id, "/tmp/api-test-root/BulkKit.zip", "BulkKit.zip"),
        )
        zip_id = cur.fetchone()[0]
    try:
        resp = client.get("/admin/pending-archives")
        assert resp.status_code == 200
        # Exactly one POST form (the bulk-accept one) — the page-size
        # selector's own GET forms (added for pagination) are separate
        # siblings, not nested inside it, so they don't reintroduce the bug.
        assert resp.text.count("<form method=\"POST\" action=\"/admin/zips/accept-bulk\"") == 1
        assert 'class="select-all-checkbox" data-target=".zip-checkbox"' in resp.text
        assert f'name="zip_ids" value="{zip_id}"' in resp.text
        assert f'formaction="/admin/zips/{zip_id}/confirm"' in resp.text
        assert f'formaction="/admin/zips/{zip_id}/reject"' in resp.text
    finally:
        with db_conn.cursor() as cur:
            cur.execute("DELETE FROM zip_files WHERE id = %s", (zip_id,))


def test_accept_zips_bulk_confirms_each_and_redirects(client, db_conn, test_root_id):
    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO zip_files (watched_root_id, path, filename, size_bytes) VALUES (%s, %s, %s, 100) RETURNING id",
            (test_root_id, "/tmp/api-test-root/BulkA.zip", "BulkA.zip"),
        )
        zip_a = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO zip_files (watched_root_id, path, filename, size_bytes) VALUES (%s, %s, %s, 100) RETURNING id",
            (test_root_id, "/tmp/api-test-root/BulkB.zip", "BulkB.zip"),
        )
        zip_b = cur.fetchone()[0]
    try:
        resp = client.post(
            "/admin/zips/accept-bulk", data={"zip_ids": [str(zip_a), str(zip_b)]}, follow_redirects=False
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/admin/pending-archives"

        with db_conn.cursor() as cur:
            cur.execute("SELECT status FROM zip_files WHERE id = ANY(%s) ORDER BY id", ([zip_a, zip_b],))
            statuses = [row[0] for row in cur.fetchall()]
        assert statuses == ["confirmed", "confirmed"]

        with db_conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM jobs WHERE zip_file_id = ANY(%s) AND job_type = 'extract_zip'", ([zip_a, zip_b],))
            assert cur.fetchone()[0] == 2
    finally:
        with db_conn.cursor() as cur:
            cur.execute("DELETE FROM zip_files WHERE id = ANY(%s)", ([zip_a, zip_b],))


def test_suggested_projects_page_has_no_nested_forms(client, make_file, db_conn):
    # Same regression as the pending-archives test above — this page had the
    # exact bug (Confirm silently submitted the bulk form instead of its own
    # per-row action) until fixed alongside the archives bulk-select feature.
    from spool_api import queries

    file_id = make_file()
    project_id = queries.create_project("Nested Form Regression Project", "", None)
    try:
        with db_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO project_files (project_id, file_id, status) VALUES (%s, %s, 'suggested')",
                (project_id, file_id),
            )
        resp = client.get("/admin/suggested-projects")
        assert resp.status_code == 200
        # See the pending-archives version of this test for why this checks
        # the POST form specifically, not the total <form> count.
        assert resp.text.count("<form method=\"POST\" action=\"/admin/suggested-projects/accept-bulk\"") == 1
        assert f'formaction="/admin/suggested-projects/{project_id}/{file_id}/confirm"' in resp.text
        assert f'formaction="/admin/suggested-projects/{project_id}/{file_id}/reject"' in resp.text
    finally:
        with db_conn.cursor() as cur:
            cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))


def test_suggested_relationships_page_has_no_nested_forms(client, make_file, db_conn):
    file_a = make_file()
    file_b = make_file()
    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO relationships (from_file_id, to_file_id, type, status) VALUES (%s, %s, 'variant_of', 'suggested') RETURNING id",
            (file_a, file_b),
        )
        rel_id = cur.fetchone()[0]
    try:
        resp = client.get("/admin/suggested-relationships")
        assert resp.status_code == 200
        # See the pending-archives version of this test for why this checks
        # the POST form specifically, not the total <form> count.
        assert resp.text.count("<form method=\"POST\" action=\"/admin/suggested-relationships/accept-bulk\"") == 1
        assert f'formaction="/admin/suggested-relationships/{rel_id}/confirm"' in resp.text
        assert f'formaction="/admin/suggested-relationships/{rel_id}/reject"' in resp.text
    finally:
        with db_conn.cursor() as cur:
            cur.execute("DELETE FROM relationships WHERE id = %s", (rel_id,))


# ---- library filter panel: rating / printed / material -------------------

def test_index_filters_by_rating(client, make_file, db_conn):
    file_a = make_file(filename="rated-a.stl")
    file_b = make_file(filename="rated-b.stl")
    with db_conn.cursor() as cur:
        cur.execute("INSERT INTO print_log (file_id, printed, rating) VALUES (%s, true, 5)", (file_a,))
        cur.execute("INSERT INTO print_log (file_id, printed, rating) VALUES (%s, true, 2)", (file_b,))

    resp = client.get("/?rating=5")
    assert resp.status_code == 200
    assert "rated-a.stl" in resp.text
    assert "rated-b.stl" not in resp.text


def test_index_filters_by_printed_status(client, make_file, db_conn):
    printed_file = make_file(filename="was-printed.stl")
    unprinted_file = make_file(filename="never-printed.stl")
    with db_conn.cursor() as cur:
        cur.execute("INSERT INTO print_log (file_id, printed) VALUES (%s, true)", (printed_file,))

    resp = client.get("/?printed=yes")
    assert "was-printed.stl" in resp.text
    assert "never-printed.stl" not in resp.text

    resp = client.get("/?printed=no")
    assert "was-printed.stl" not in resp.text
    assert "never-printed.stl" in resp.text


def test_index_filters_by_material(client, make_file, db_conn):
    pla_file = make_file(filename="pla-part.stl")
    petg_file = make_file(filename="petg-part.stl")
    with db_conn.cursor() as cur:
        cur.execute("INSERT INTO print_metadata (file_id, material) VALUES (%s, 'PLA-unique-test')", (pla_file,))
        cur.execute("INSERT INTO print_metadata (file_id, material) VALUES (%s, 'PETG-unique-test')", (petg_file,))

    resp = client.get("/?material=PLA-unique-test")
    assert "pla-part.stl" in resp.text
    assert "petg-part.stl" not in resp.text
    # the filter panel's dropdown should offer both real values
    assert "PLA-unique-test" in resp.text
    assert "PETG-unique-test" in resp.text


def test_index_filter_panel_no_longer_at_top(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert 'id="filter-panel"' in resp.text
    assert 'id="filter-toggle"' in resp.text


def test_index_filter_panel_lists_every_model_extension(client):
    # Regression test: main.py's ALL_EXTENSIONS (the filter panel's file
    # type checkboxes) is a separate, hand-maintained list from
    # common.config.MODEL_EXTENSIONS (the actual set of extensions SPOOL
    # ingests) — these drifted out of sync once already (gcode/.obj
    # support landed in MODEL_EXTENSIONS without this second list being
    # updated, so both were fully ingested/searchable but invisible in
    # the filter panel). main.py now asserts the two stay in sync at
    # import time; this confirms the checkboxes a user actually sees
    # cover every recognized extension, not just that the assertion
    # exists.
    from common.config import MODEL_EXTENSIONS

    resp = client.get("/")
    assert resp.status_code == 200
    for ext in MODEL_EXTENSIONS:
        assert f'value="{ext}"' in resp.text, f"{ext} missing from the rendered filter panel"


# ---- processing status dashboard (/admin/status) --------------------------

def test_admin_status_page_loads(client):
    resp = client.get("/admin/status")
    assert resp.status_code == 200
    assert "Processing status" in resp.text
    assert "Job queue" in resp.text
    assert "Recent activity" in resp.text


def test_admin_status_page_self_polls_via_htmx(client):
    resp = client.get("/admin/status")
    assert resp.status_code == 200
    assert "every 4s" in resp.text
    assert 'hx-select="#status-top"' in resp.text
    assert 'hx-select="#recent-activity-panel"' in resp.text


def test_admin_status_job_queue_is_a_type_by_status_matrix(client, make_file, db_conn):
    file_id = make_file(filename="matrix-check.stl")
    with db_conn.cursor() as cur:
        cur.execute("INSERT INTO jobs (file_id, job_type, status) VALUES (%s, 'ingest', 'queued')", (file_id,))

    resp = client.get("/admin/status")
    assert resp.status_code == 200
    # One row per job_type (not one row per job_type+status combination) —
    # scoped to the Job queue table specifically, since Recent activity
    # below it also renders an unrelated "ingest" cell for this same job.
    job_queue_html = resp.text.split("Job queue")[1].split("Watched roots")[0]
    assert job_queue_html.count("<td>ingest</td>") == 1
    assert "Queued" in job_queue_html and "Running" in job_queue_html


def test_admin_status_job_queue_omits_done_and_failed_lifetime_totals(client, make_file, db_conn):
    # jobs rows are never deleted once done/failed, so those would be
    # ever-growing lifetime totals, not live queue state — confirmed
    # unhelpful by direct user feedback, so this matrix only ever shows
    # the two genuinely "live" columns.
    file_id = make_file(filename="matrix-no-lifetime-cols.stl")
    with db_conn.cursor() as cur:
        cur.execute("INSERT INTO jobs (file_id, job_type, status) VALUES (%s, 'ingest', 'done')", (file_id,))

    resp = client.get("/admin/status")
    assert resp.status_code == 200
    job_queue_html = resp.text.split("Job queue")[1].split("Watched roots")[0]
    assert "Done" not in job_queue_html
    assert "Failed" not in job_queue_html


def test_admin_status_filters_by_target_filename(client, make_file, db_conn):
    match_id = make_file(filename="filterable-unique-name.stl")
    other_id = make_file(filename="totally-different.stl")
    with db_conn.cursor() as cur:
        cur.execute("INSERT INTO jobs (file_id, job_type, status) VALUES (%s, 'render', 'done')", (match_id,))
        cur.execute("INSERT INTO jobs (file_id, job_type, status) VALUES (%s, 'render', 'done')", (other_id,))

    resp = client.get("/admin/status", params={"q": "filterable-unique-name"})
    assert resp.status_code == 200
    assert "filterable-unique-name.stl" in resp.text
    assert "totally-different.stl" not in resp.text


def test_admin_status_filters_by_status(client, make_file, db_conn):
    done_id = make_file(filename="status-filter-done.stl")
    failed_id = make_file(filename="status-filter-failed.stl")
    with db_conn.cursor() as cur:
        cur.execute("INSERT INTO jobs (file_id, job_type, status) VALUES (%s, 'render', 'done')", (done_id,))
        cur.execute(
            "INSERT INTO jobs (file_id, job_type, status, error) VALUES (%s, 'render', 'failed', 'boom')",
            (failed_id,),
        )

    resp = client.get("/admin/status", params={"status": "failed", "q": "status-filter"})
    assert resp.status_code == 200
    assert "status-filter-failed.stl" in resp.text
    assert "status-filter-done.stl" not in resp.text


def test_admin_status_filters_by_job_type(client, make_file, db_conn):
    file_id = make_file(filename="jobtype-filter-unique.stl")
    with db_conn.cursor() as cur:
        cur.execute("INSERT INTO jobs (file_id, job_type, status) VALUES (%s, 'ingest', 'done')", (file_id,))
        cur.execute("INSERT INTO jobs (file_id, job_type, status) VALUES (%s, 'render', 'done')", (file_id,))

    resp = client.get("/admin/status", params={"q": "jobtype-filter-unique", "job_type": "ingest"})
    assert resp.status_code == 200
    text = resp.text
    # Both rows share the same target name, so assert on the row count
    # instead of substring presence — the ingest row should render, the
    # render row (same file, different job_type) should not.
    assert text.count("jobtype-filter-unique.stl") == 1


def test_admin_status_invalid_filter_values_ignored(client):
    resp = client.get("/admin/status", params={"status": "not-a-real-status", "job_type": "not-a-real-type"})
    assert resp.status_code == 200  # falls back to unfiltered rather than erroring


def test_admin_status_recent_activity_is_paginated(client, make_file, db_conn):
    file_id = make_file(filename="paginated-status-check.stl")
    with db_conn.cursor() as cur:
        cur.execute("INSERT INTO jobs (file_id, job_type, status) VALUES (%s, 'render', 'done')", (file_id,))

    resp = client.get("/admin/status", params={"q": "paginated-status-check", "page_size": 100})
    assert resp.status_code == 200
    assert "paginated-status-check.stl" in resp.text
    assert "1 total" in resp.text


def test_admin_page_links_to_status_page(client):
    resp = client.get("/admin")
    assert resp.status_code == 200
    assert 'href="/admin/status"' in resp.text


# ---- live status summary, moved to the top of /admin ----------------------

def test_admin_page_shows_running_job_target_name(client, make_file, db_conn):
    file_id = make_file(filename="admin-page-running.stl")
    with db_conn.cursor() as cur:
        cur.execute("INSERT INTO jobs (file_id, job_type, status) VALUES (%s, 'render', 'running')", (file_id,))

    resp = client.get("/admin")
    assert resp.status_code == 200
    assert "admin-page-running.stl" in resp.text
    assert "idle — nothing currently processing" not in resp.text
    assert "status-dot-ok" in resp.text


def test_admin_page_idle_shows_gray_dot_when_nothing_running(client):
    resp = client.get("/admin")
    assert resp.status_code == 200
    assert "idle — nothing currently processing" in resp.text
    assert "status-dot-idle" in resp.text


def test_admin_page_self_polls_the_live_status_section(client):
    resp = client.get("/admin")
    assert resp.status_code == 200
    assert "every 4s" in resp.text
    assert 'hx-select="#live-status"' in resp.text


def test_admin_page_shows_ingestion_totals_with_warn_dot_on_failures(client, make_file, db_conn):
    file_id = make_file(filename="admin-page-render-failed.stl")
    with db_conn.cursor() as cur:
        cur.execute("UPDATE files SET render_status = 'failed' WHERE id = %s", (file_id,))

    resp = client.get("/admin")
    assert resp.status_code == 200
    assert "Ingestion totals" in resp.text
    assert "status-dot-warn" in resp.text


# ---- library page pagination (top and bottom) ------------------------------

def test_index_shows_pagination_at_top_and_bottom_when_multiple_pages(client, make_file):
    from spool_api.queries import PAGE_SIZE

    for i in range(PAGE_SIZE + 1):
        make_file(filename=f"pagination-test-{i}.stl")

    resp = client.get("/", params={"q": "pagination-test"})
    assert resp.status_code == 200
    assert "Page 1 of 2" in resp.text
    assert resp.text.count('class="pagination pagination-top"') == 1
    assert resp.text.count('class="pagination pagination-bottom"') == 1


def test_index_no_pagination_shown_for_a_single_page(client, make_file):
    make_file(filename="single-page-result.stl")

    resp = client.get("/", params={"q": "single-page-result"})
    assert resp.status_code == 200
    assert "pagination-top" not in resp.text
    assert "pagination-bottom" not in resp.text


# ---- bulk-review "all" page size + page-size cookie persistence -----------

def test_admin_suggested_projects_page_size_all_shows_everything_on_one_page(client, make_file, db_conn):
    from spool_api import queries as q

    project_id = q.create_project("All Page Size Route Project", "", None)
    file_id = make_file(filename="all-page-size-route.stl")
    try:
        with db_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO project_files (project_id, file_id, status) VALUES (%s, %s, 'suggested')",
                (project_id, file_id),
            )
        resp = client.get("/admin/suggested-projects", params={"page_size": "all"})
        assert resp.status_code == 200
        assert "all-page-size-route.stl" in resp.text
        assert '<nav class="pagination">' not in resp.text  # everything fits on the one page
    finally:
        with db_conn.cursor() as cur:
            cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))


def test_admin_suggested_projects_remembers_page_size_via_cookie(client):
    first = client.get("/admin/suggested-projects", params={"page_size": "500"})
    assert first.status_code == 200
    assert first.cookies.get("bulk_review_page_size") == "500"

    # No explicit page_size this time — the cookie set above should carry
    # forward instead of resetting to the 100 default.
    second = client.get("/admin/suggested-projects")
    assert second.status_code == 200
    assert 'value="500" selected' in second.text


def test_admin_suggested_projects_garbage_page_size_falls_back_to_default(client):
    resp = client.get("/admin/suggested-projects", params={"page_size": "not-a-real-value"})
    assert resp.status_code == 200  # falls back rather than erroring
    assert 'value="100" selected' in resp.text


# ---- duplicate-file bulk delete (batched connections + thumbnail cleanup) --

def test_delete_duplicates_route_deletes_successes_and_reports_failures(client, make_file, monkeypatch):
    import os

    from spool_api import host_helper_client, queries

    os.makedirs(queries.THUMBNAILS_DIR, exist_ok=True)
    thumbnail_path = os.path.join(queries.THUMBNAILS_DIR, "route-delete-thumb.png")
    with open(thumbnail_path, "wb") as f:
        f.write(b"fake png bytes")

    keep_id = make_file(filename="route-delete-keep.stl", path="/tmp/route-delete-keep.stl")
    fail_id = make_file(filename="route-delete-fail.stl", path="/tmp/route-delete-fail.stl")
    ok_id = make_file(filename="route-delete-ok.stl", path="/tmp/route-delete-ok.stl", thumbnail_path="route-delete-thumb.png")

    def fake_request_delete(path):
        if path == "/tmp/route-delete-fail.stl":
            return False, "simulated host-helper failure"
        return True, None

    monkeypatch.setattr(host_helper_client, "request_delete", fake_request_delete)

    resp = client.post(
        "/admin/duplicates/delete",
        data={"file_ids": [str(ok_id), str(fail_id)]},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "delete_errors=" in resp.headers["location"]

    assert queries.get_file(ok_id) is None  # deleted
    assert queries.get_file(fail_id) is not None  # host-helper "failed", so kept
    assert queries.get_file(keep_id) is not None  # never selected, untouched
    assert not os.path.exists(thumbnail_path)  # its thumbnail went with it

    # clean up the two rows this test didn't get SPOOL itself to delete
    with queries.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM files WHERE id = ANY(%s)", ([fail_id, keep_id],))


# ---- bulk project-name cleanup ---------------------------------------------

def test_projects_page_links_to_bulk_rename_when_cleanup_needed(client):
    from spool_api import queries

    project_id = queries.create_project("route-check-messy-model_files", "", None)
    try:
        resp = client.get("/projects")
        assert resp.status_code == 200
        assert 'href="/projects/bulk-rename"' in resp.text
    finally:
        with queries.get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))


def test_bulk_rename_page_shows_suggested_name(client):
    from spool_api import queries

    project_id = queries.create_project("route-bulk-rename-model_files", "", None)
    try:
        resp = client.get("/projects/bulk-rename", params={"page_size": "all"})
        assert resp.status_code == 200
        assert "route-bulk-rename-model_files" in resp.text
        assert 'value="route bulk rename"' in resp.text
    finally:
        with queries.get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))


def test_bulk_rename_apply_only_renames_checked_rows(client):
    from spool_api import queries

    checked_id = queries.create_project("route-checked-model_files", "", None)
    unchecked_id = queries.create_project("route-unchecked-model_files", "", None)
    try:
        resp = client.post(
            "/projects/bulk-rename",
            data={
                "project_ids": [str(checked_id), str(unchecked_id)],
                "new_names": ["Route Checked", "Route Unchecked"],
                "checked_ids": [str(checked_id)],
            },
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert queries.get_project(checked_id)["name"] == "Route Checked"
        assert queries.get_project(unchecked_id)["name"] == "route-unchecked-model_files"
    finally:
        with queries.get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM projects WHERE id = ANY(%s)", ([checked_id, unchecked_id],))
