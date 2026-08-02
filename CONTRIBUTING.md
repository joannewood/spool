# Contributing to SPOOL

This is the developer-facing companion to [README.md](README.md), which is
written for testers installing and using SPOOL. This file is for anyone
working on the code itself — running it from source, adding a feature,
fixing a bug, or building a release.

## Architecture

```
services/
  common/   Shared library imported by watcher + worker (not api — see
            below). DB access (common/db.py), host<->container path
            mapping (common/paths.py), hashing, ingest primitives
            (stage/relocate/enqueue), app-wide settings (common/settings.py).
  api/      FastAPI + Jinja2 + htmx. Package is `spool_api` on disk
            (services/api/spool_api/) but the Dockerfile COPYs it to a
            container-internal `app/`, so `uvicorn app.main:app` never
            needs to know about the rename — done specifically so
            `spool_api` and the worker's own `app` package could both be
            importable in the same pytest session (see pyproject.toml).
            api/queries.py functions each open their own DB connection
            (common.db.get_connection(), always autocommit) rather than
            taking one as a parameter — the opposite convention from
            worker/common below, driven by how each side is actually
            used (one function call per request vs. a long-lived batch
            process threading one connection through everything).
  watcher/  Live filesystem events via watchdog. Lightweight — stages a
            stub row + queues a job, or relocates (Downloads), then gets
            out of the way. Polls watched_roots every 10s to pick up
            admin-page changes (pause/label/mode) without a restart.
  worker/   The heavy lane — trimesh/pyrender (mesh thumbnails), OCP/
            OpenCASCADE (STEP), a plain Postgres job queue (`jobs` table,
            `FOR UPDATE SKIP LOCKED`, no Redis/Celery). Every function
            here takes `conn` as an explicit parameter instead of opening
            its own connection — this is what makes the test suite's
            rollback-based isolation possible with zero mocking (see
            Testing below). Ships as one image (`spool-worker`) run as
            two Compose services filtered by `JOB_TYPES`: `worker` (fast
            lane: ingest/render/extract_zip, also runs backfill + the
            periodic rescan) and `worker-step` (slow STEP-tessellation
            lane only) — real process-level separation so a big STEP file
            can't block quick mesh renders.
db/migrations/   Plain numbered SQL files (001_init.sql, 002_..., etc.),
                 NOT a real migration tool. Run once by Postgres's
                 docker-entrypoint-initdb.d on a *fresh* volume only — see
                 "Migrations" below for what that means in practice.
host-helper/     The one piece that isn't Docker — native Mac (launchd
                 agent) / Windows (Startup-folder script) processes that
                 can actually launch a GUI app or delete a file on the
                 real host, since a Linux container can't. Protocol-
                 compatible (same JSON request/response shapes) across
                 both OSes, so services/api/spool_api/host_helper_client.py
                 needs no OS-specific branching.
scripts/         Build tooling, not part of the running app:
                 build-mac-installer.sh / setup-platypus-tools.sh (Mac
                 installer, signed & notarized) and windows-installer.iss
                 (Windows installer, built via
                 .github/workflows/build-windows-installer.yml on a
                 GitHub-hosted runner — there's no Windows machine in
                 this project's normal dev loop, so that CI workflow is
                 the only place this code actually executes before a
                 release).
```

## Running it locally

```bash
cp .env.example .env      # edit DROPFOLDER_HOST_PATH etc. to real paths on your machine
docker compose up -d --build
docker compose ps                        # all 5 services should be Up
curl localhost:8000/health               # {"status":"ok","database":"connected"}
```

After changing code in one service, rebuild just that one rather than
everything:

```bash
docker compose up -d --build api            # api/spool_api changes
docker compose up -d --build worker worker-step   # worker/common changes (both share the same image)
docker compose up -d --build watcher        # watcher changes
```

```bash
docker compose logs worker -f      # watch backfill/render/ingest activity
docker compose logs watcher -f     # watch live filesystem events
docker compose exec postgres psql -U spool -d spool   # inspect data directly
docker compose down                # stop (keeps pgdata + thumbnails — named volumes)
docker compose down -v             # stop AND wipe all data
```

**No browser automation on a fresh dev machine** — see
`.claude/skills/run-spool/SKILL.md` for the pattern this project uses
instead (a throwaway Playwright container on the same Compose network).

## Migrations

`db/migrations/*.sql` only runs automatically via
`docker-entrypoint-initdb.d` on a genuinely empty `pgdata` volume. Once
there's real data, a new migration file needs applying by hand:

```bash
docker compose exec postgres psql -U spool -d spool -f /docker-entrypoint-initdb.d/0NN_whatever.sql
```

(The migrations folder is already bind-mounted into the postgres
container at that path, so the file is already there.) There's no real
migration tool tracking what's been applied — keep migration files
small, additive, and idempotent-safe to re-run where practical (`CREATE
TABLE IF NOT EXISTS`-style caution isn't used everywhere, so check
before re-running one against a database that might already have it).

## Testing

```bash
docker compose up -d postgres        # only postgres needs to be running
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest
```

Tests run on the host (not in a container) against a real, separate
`spool_test` database on the same Postgres instance (`localhost:55432`).
`tests/conftest.py`'s session-scoped fixture (re)creates it and applies
every migration except `003_seed_watched_roots.sh` (personal host paths
— would make backfill/rescan walk the real filesystem during tests).

Two different isolation strategies, matching the two DB-access
conventions above:

- **Worker/common tests** (`tests/worker/`, `tests/common/`) use a `conn`
  fixture — autocommit off, rolled back at teardown. Works with zero
  mocking specifically because every function under test already takes
  `conn` as a parameter.
- **API tests** (`tests/api/`) use a `db_conn` fixture (autocommit, no
  rollback) instead, since `spool_api.queries` functions open their own
  connections the real app's own style — tests clean up their own
  inserted rows explicitly (see `make_file`/`test_root_id` in
  `tests/api/conftest.py`), and a table with exactly one always-existing
  row (e.g. `app_settings`) gets its original values saved and restored
  rather than deleted.

Route tests use FastAPI's `TestClient` (in-process ASGI, no real server).

The worker's heavy geometry deps (trimesh/pyrender/cadquery-ocp) are
deliberately **not** in `requirements-dev.txt` — none of the
lightweight-test-path modules import `render.py`/`step_loader.py`, and
those are genuinely heavy to install. Modules that need to stay
importable without them (`job_queue.py`, `gcode_thumbnail.py`,
`gcode_metadata.py`, `bambu_metadata.py`, `mesh_safety.py`, `rescan.py`)
are kept stdlib/psycopg-only for exactly this reason — think about that
boundary before adding a new import to one of them.

## Building a release installer

Both build scripts export exactly the **git-tracked** repo (`git archive
HEAD` on Mac; `actions/checkout` on the Windows CI runner) — commit
first, or your build won't include uncommitted changes.

**Mac** (run locally; needs a Developer ID Application certificate and a
`notarytool` keychain profile set up once — see the script's own header
comment):

```bash
scripts/setup-platypus-tools.sh      # one-time, fetches Platypus's CLI, no sudo
scripts/build-mac-installer.sh       # exports, builds, signs, notarizes, staples, .dmg
```

**Windows** (there's no Windows dev machine — this only runs in CI):

```bash
gh workflow run build-windows-installer.yml
gh run watch <run-id> --exit-status
gh run download <run-id> --name SPOOL-Installer
```

Then attach both to a GitHub release:

```bash
gh release create vX.Y.Z dist/SPOOL-Installer.dmg SPOOL-Installer.exe --title "..." --notes "..."
```

## Code conventions worth knowing before you dig in

- **No ORM** — plain SQL via `psycopg` everywhere, `row_factory=dict_row`
  where a dict is more convenient than a tuple.
- **Boundary-only validation** — internal code trusts its inputs; a
  malformed value from a browser form gets a sane fallback (an unknown
  `sort=` value silently falls back to the default) rather than a 400,
  matching how the rest of the app already behaves.
- **Fixed allowlists over dynamic SQL** for anything that ends up in a
  raw `ORDER BY`/column name — see `SORT_CLAUSES`, `ALL_EXTENSIONS`'s
  `assert` against `common.config.MODEL_EXTENSIONS`. Never string-format
  user input into SQL structure, even column/table names.
- **Minimal new JS** — htmx covers most interactivity; a handful of
  small, single-purpose scripts (`inline-edit.js`, `select-all.js`,
  `modal.js`, `favicon-status.js`) exist only where no CSS-only trick
  could do the job, and each says so in its own header comment.
- **A shared macro over copy-pasted markup** once the same component
  shows up in two templates (`_file_card.html`, `_icons.html`,
  `_bulk_review_paging.html`) — check for an existing partial before
  writing a new block of near-identical HTML.

## Known technical limitations

The README's "Known limitations" section is written for testers/users;
this is the same list with the actual technical detail behind each one,
for anyone working on the code.

- **Windows hasn't been run on real hardware.** The app-detection logic
  in `configure_apps.py` was validated against synthetic test cases
  modeling real installer layouts (including Autodesk's own
  deeply-nested one), and `SPOOL-Installer.exe` has been verified to
  build correctly in CI — but neither that installer nor `setup.ps1` nor
  the Windows host-helper has actually been run interactively on a real
  Windows machine, since none exists in this project's dev environment.
- **`SPOOL-Installer.exe` isn't code-signed.** A Windows code-signing
  certificate is a real ongoing cost (unlike Apple's notarization, which
  the Mac `.dmg` uses and is covered by the existing $99/year Apple
  Developer account) and isn't part of this project yet — hence the
  SmartScreen warning.
- **No automatic app icons on Windows yet.** macOS extracts each
  configured app's real icon from its `.icns`; there's no equivalent
  step wired up for Windows `.exe`/`.ico` resources yet, so a
  Windows-configured app just shows a plain two-letter badge.
- **Re-running the installer to change watched folders**: choosing
  **Re-run Full Setup** then **No** when asked to keep the existing
  folder configuration walks through the same three folder questions
  again, and the install reconciles `watched_roots` to match on its own
  — password is preserved (not regenerated), rows are added/updated/
  deactivated as needed. The one case this doesn't cover is a genuinely
  new *fourth* watched folder beyond drop folder/Library/Downloads —
  Docker can't attach a brand-new bind mount to an already-running
  container, so that needs a manual edit to `docker-compose.yml` (a new
  volume mount) followed by `docker compose up -d --build`. Separately,
  the `/admin` page's own per-root edit form only ever changes a root's
  **label**, **ingest mode**, or **active/paused** state — it was never
  able to change the underlying folder path itself.
- **Library is mounted `:ro` in `docker-compose.yml`**, and the native
  host-helper's delete endpoint independently refuses any path under
  Library too (it runs outside Docker, so the read-only mount alone
  wouldn't stop it). Confirming an archive found in Library fails with a
  permissions error in Admin; deleting a duplicate that lives there
  fails with a clear error instead of silently succeeding.
- **iCloud Drive + "Optimize Mac Storage" + a watched folder is a real
  hazard, confirmed live**: iCloud periodically evicts local copies of
  untouched files to cloud-only placeholders, and Docker Desktop's
  virtualized filesystem bridge doesn't trigger iCloud's on-demand
  download for these the way native macOS file access does — the
  watcher/worker containers just get `OSError: [Errno 35] Resource
  deadlock avoided` trying to even `stat()` the file, indefinitely, not
  as a transient error. Confirmed live: an affected file shows a real
  size in `ls -la` but `stat -f "blocks=%b"` reports `0`. Reading the
  file once from the host (Terminal, Finder, anything running directly
  on the Mac, not in a container) reliably materializes it and unblocks
  the container — but iCloud can evict it again later under storage
  pressure, so this isn't a one-time fix, it can recur on a shifting set
  of files indefinitely. See GitHub issue #7 for the considered-but-not-
  built auto-download idea and why it was scoped the way it was.

## Filing issues / opening PRs

Use GitHub Issues for bugs and feature ideas — see README.md's "Found a
bug, or something confusing?" section for what to include. No formal PR
template yet; a clear description of what changed and why is enough.
