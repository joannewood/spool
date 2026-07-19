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
    assert 'class="add-tag-toggle"' in resp.text


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
