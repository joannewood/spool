import os
import subprocess
import tempfile
from pathlib import Path

import psycopg
import pytest

from common.roots import WatchedRoot

REPO_ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = REPO_ROOT / "db" / "migrations"

TEST_DB_NAME = "spool_test"
TEST_DB_URL = f"postgresql://spool:changeme@localhost:55432/{TEST_DB_NAME}"

# Both env vars are read at *import time* by common/db.py and spool_api/
# main.py respectively, so they have to be set before any test file gets
# around to `import spool_api` (or anything that imports it) — this file
# is the first thing pytest loads, so module-level (not fixture) code here
# runs early enough. Forced (not setdefault) so api tests can never end up
# accidentally pointed at the real `spool` database. THUMBNAILS_DIR needs
# to exist and be writable — main.py does an unconditional os.makedirs on
# import, and the production default (/data/thumbnails) is neither on a
# host run outside Docker.
os.environ["DATABASE_URL"] = TEST_DB_URL
os.environ["THUMBNAILS_DIR"] = tempfile.mkdtemp(prefix="spool-test-thumbnails-")

# 003 seeds this machine's real personal watched-root paths (per CLAUDE.md,
# a deliberately hardcoded, non-portable seed) — applying it here would make
# run_backfill/run_rescan walk the *real* filesystem during tests, since
# tests run on the host, not in a container. Every other migration is
# schema-only and safe to apply as-is.
SKIP_MIGRATIONS = {"003_seed_watched_roots.sql"}


def _psql(database, *args):
    subprocess.run(
        ["docker", "compose", "exec", "-T", "postgres", "psql", "-U", "spool", "-d", database, *args],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )


@pytest.fixture(scope="session", autouse=True)
def _test_database():
    """(Re)creates spool_test fresh once per test session, applying every
    migration except the personal-machine seed (see SKIP_MIGRATIONS) — reuses
    the exact manual-apply mechanism already documented in CLAUDE.md for a
    live DB (the migrations dir is already bind-mounted into the postgres
    container at this path), rather than a new migration-runner."""
    _psql("postgres", "-c", f"DROP DATABASE IF EXISTS {TEST_DB_NAME};")
    _psql("postgres", "-c", f"CREATE DATABASE {TEST_DB_NAME};")
    for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if migration.name in SKIP_MIGRATIONS:
            continue
        _psql(TEST_DB_NAME, "-f", f"/docker-entrypoint-initdb.d/{migration.name}")


@pytest.fixture
def conn():
    """A fresh connection per test, rolled back at teardown — every test
    starts from the same clean migrated schema regardless of what earlier
    tests did. Autocommit is off here (unlike the real app's
    common.db.get_connection, which always autocommits) specifically so
    rollback-for-isolation works; every function under test takes `conn` as
    an explicit parameter rather than opening its own connection, so this
    requires no monkeypatching."""
    connection = psycopg.connect(TEST_DB_URL)
    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()


@pytest.fixture
def db_conn():
    """Autocommit, no rollback — matches the real app's own connection
    style (common.db.get_connection). Needed for spool_api.queries
    functions, which each open their own connection rather than accepting
    an injected `conn` the way worker functions do, so the `conn` fixture's
    rollback-based isolation doesn't apply to them. Tests using this
    fixture clean up whatever rows they insert."""
    connection = psycopg.connect(TEST_DB_URL, autocommit=True)
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture
def make_root(conn, tmp_path):
    """Creates a real watched_roots row (so fetch_active_roots-based
    functions like run_backfill/run_rescan see it) and returns the matching
    WatchedRoot instance. host_path and container_path both point at the
    same tmp_path-provided directory by default — the host/container split
    only matters for the real Docker-vs-Mac path translation, not for the
    ingestion logic itself."""
    counter = {"n": 0}

    def _make(label=None, kind="existing_library", ingest_mode="index_in_place", active=True, path=None):
        counter["n"] += 1
        n = counter["n"]
        root_dir = path or (tmp_path / f"root{n}")
        root_dir.mkdir(parents=True, exist_ok=True)
        label = label or f"Test root {n}"
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO watched_roots (host_path, container_path, label, kind, ingest_mode, active)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (str(root_dir), str(root_dir), label, kind, ingest_mode, active),
            )
            root_id = cur.fetchone()[0]
        return WatchedRoot(
            id=root_id,
            host_path=str(root_dir),
            container_path=str(root_dir),
            label=label,
            kind=kind,
            ingest_mode=ingest_mode,
            active=active,
        )

    return _make
