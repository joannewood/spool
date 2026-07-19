import pytest
from fastapi.testclient import TestClient

from spool_api.main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def test_root_id(db_conn):
    """A watched_roots row for FK purposes — spool_api.queries functions
    each open their own autocommit connection, so this (like `make_file`
    below) tracks and cleans up its own rows rather than relying on the
    worker tests' rollback-based `conn` fixture."""
    with db_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO watched_roots (host_path, container_path, label, kind, ingest_mode, active)
            VALUES ('/tmp/api-test-root', '/tmp/api-test-root', 'api test root', 'existing_library', 'index_in_place', true)
            RETURNING id
            """
        )
        root_id = cur.fetchone()[0]
    yield root_id
    with db_conn.cursor() as cur:
        cur.execute("DELETE FROM watched_roots WHERE id = %s", (root_id,))


@pytest.fixture
def make_file(db_conn, test_root_id):
    """Factory for a minimal real `files` row, with sensible overridable
    defaults. Tracks every id it creates and deletes them (cascades to
    tags/relationships/print_metadata/print_log/project_files) at
    teardown."""
    created_ids = []
    counter = {"n": 0}

    def _make(**overrides):
        counter["n"] += 1
        n = counter["n"]
        fields = {
            "watched_root_id": test_root_id,
            "path": f"/tmp/api-test-root/file{n}.stl",
            "filename": f"file{n}.stl",
            "ext": ".stl",
            "size_bytes": 100,
            "content_hash": f"hash{n}",
        }
        fields.update(overrides)
        columns = ", ".join(fields.keys())
        placeholders = ", ".join(["%s"] * len(fields))
        with db_conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO files ({columns}) VALUES ({placeholders}) RETURNING id",
                list(fields.values()),
            )
            file_id = cur.fetchone()[0]
        created_ids.append(file_id)
        return file_id

    yield _make

    with db_conn.cursor() as cur:
        for file_id in created_ids:
            cur.execute("DELETE FROM files WHERE id = %s", (file_id,))
