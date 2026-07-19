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
        resp = client.get("/admin")
        assert resp.status_code == 200
        assert "<td>Kit Files.zip</td>" in resp.text
        # the raw path column intentionally stays uncleaned (real disk path
        # for verification), only the filename cell should be cleaned
        assert "<td>Kit+Files.zip</td>" not in resp.text
    finally:
        with db_conn.cursor() as cur:
            cur.execute("DELETE FROM zip_files WHERE id = %s", (zip_id,))
