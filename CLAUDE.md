# SPOOL

A local, searchable library for 3D printing files (.stl, .3mf, .step) — watches
folders, hashes and indexes files into Postgres, renders preview thumbnails, and
serves a localhost web UI so files can be found and previewed before opening in
Fusion360 or Bambu Studio. Runs entirely in Docker except a small native host
helper (Phase 08) that launches those GUI apps.

Full design spec (architecture, data model, all decisions made while speccing
this out): https://claude.ai/code/artifact/a0d3f281-fa08-4666-a93c-7942c7a785bc
This file tracks *current build status* — the artifact is the design record.

## Status

- [x] Phase 00 — Postgres schema, FastAPI health check, Compose skeleton
- [x] Phase 01 — ingestion core: watcher (live fs events), worker (backfill +
      job queue), Downloads relocation
- [x] Phase 02 — mesh thumbnail rendering for STL/3MF (trimesh + pyrender)
- [x] Phase 03 — STEP previews (OCP/OpenCASCADE), own `render_step` job lane
- [x] Phase 04 — browse & search UI (FastAPI + Jinja2 + htmx)
- [x] Phase 05 — tags, projects (nestable), print metadata (auto + manual), admin page
- [x] Phase 06 — relationships (manual + auto-suggest: filename/version, folder grouping)
- [x] Phase 07 — drift reconciliation (periodic rescan, hash rematching)
- [x] Phase 08 — host-helper (native launchd agent, open-in-Fusion/Bambu)
- [ ] Phase 09 — polish & scale ← **next**

The stack (postgres, api, watcher, worker) runs continuously — it's not a
one-shot build, it's meant to be up and watching folders in the background.

## Architecture

```
services/
  common/   shared lib used by watcher + worker — db, host<->container path
            mapping, hashing, ingest primitives (stage/relocate/enqueue)
  api/      FastAPI + Jinja2 + htmx. / is a searchable/filterable thumbnail
            grid (search-as-you-type + extension + tag checkboxes, all via
            htmx partial swaps on the same route), /files/{id} is the detail
            page (geometry stats + tags/projects/print-metadata/relationships
            panels), /projects is a nestable project tree + create form,
            /projects/{id} is a project's file grid, /admin lists watched
            roots with live-editable label/ingest_mode/active. Tag and
            project removal use hx-delete swapping the chip to nothing;
            everything else is a plain POST-redirect-GET form (simpler than
            partials for rare actions). Relationships (Phase 06) follow the
            same pattern: the "Related files" panel on the detail page shows
            confirmed links (hx-delete to remove) and worker-suggested ones
            (confirm/reject as plain POSTs) separately, plus a manual
            add-relationship form whose file-picker reuses the same
            search-as-you-type technique as the main grid (GET
            /files/{id}/relationships/search returns a partial of clickable
            `<button type=submit>` results sitting inside the add form, so
            picking one submits type+to_file_id together — no custom JS).
            Suggested project membership (from worker folder-grouping) gets
            the same confirm/reject treatment as a chip in the Projects
            panel. `/admin` also has a "Pending archives" panel (zip files
            worth reviewing — see zip_ingest below) and a project's page
            lists its folder's sidecar files (non-model files — README,
            preview images — that live alongside model files; no thumbnail,
            nothing to click, just filename + size). Shares `common/`
            (build context is ./services) — uses common.db for queries,
            all in queries.py.
  watcher/  live filesystem events via watchdog. Lightweight — stages a stub
            file row + queues an 'ingest' job, or relocates (Downloads), then
            gets out of the way. Polls watched_roots every 10s
            (ROOT_POLL_INTERVAL_SECONDS in app/main.py) and reconciles its
            live watchdog schedule against active/ingest_mode — pause/resume/
            edit an already-mounted root takes effect within ~10s, no
            restart. Adding a brand-new root still needs one (see Gotchas).
  worker/   heavy image (trimesh/pyrender/OCP). Also has
            relationship_suggest.py (Phase 06) — after a file is hashed
            (both the live ingest path and backfill call it, since backfill
            processes files one at a time and each new file is compared
            against everything already indexed, every real pair gets caught
            the first time either member is the "new" one), runs three
            content-only heuristics: identical content_hash -> duplicate_of;
            same basename, one side a STEP/STP and the other not ->
            derived_from (assumed export direction: non-STEP derived from
            STEP); same basename with a trailing `_v<N>`/`-v<N>` and same
            extension -> new_version_of, newer -> older. Separately,
            suggest_folder_project suggests a project for *any* indexed
            file sitting in a meaningful subfolder (skipped if that
            directory *is* the watched root) — even a lone file, a project
            of one, ready to pick up siblings later — into a flat,
            auto-created-if-missing top-level project named after the
            folder, deliberately not mirroring the whole directory tree,
            per spec. All suggestions insert with
            status='suggested' via `ON CONFLICT ... DO NOTHING` against the
            relationships_from_to_type_uniq constraint (migration 005) /
            the project_files PK, so a user's manual confirm or reject is
            never silently overwritten by a later rescan. Also has
            rescan.py (Phase 07) — a periodic (`RESCAN_INTERVAL_SECONDS`,
            default 300s) repeat of the same walk backfill does at startup,
            but for files already in the DB: cheap `os.stat` (size + the
            `mtime` column added in migration 006) gates an expensive
            re-hash, so an untouched library costs one stat per file per
            pass, not a full re-hash. A file gone from disk gets
            `status='missing'`; one that reappears (same path) gets
            revived; a real content change (hash differs) resets
            `render_status='pending'` + nulls the now-stale geometry/
            thumbnail columns + enqueues a fresh render. Deliberately
            does *not* re-run Phase 06's relationship/folder-grouping
            heuristics on a content change, to avoid suggestion-noise on
            every in-place slicer re-save. Shares `backfill.py`'s
            `_ingest_new_path`/`_walk_project_folders` rather than
            duplicating "how a brand-new file gets indexed." Gated on the same
            `RUN_BACKFILL` flag as backfill (only the fast `worker` lane
            runs it, not `worker-step` — otherwise both lanes would
            double-hash and race on the same rows) and checked once per
            iteration of the existing job-poll loop, no separate
            thread/scheduler.

            **Sidecar files, folder-preserving relocate, and zip
            extraction** (added after the folder-grouping/rescan work
            above, while populating the real library): both
            `run_backfill` and `run_rescan` walk directories via
            `_walk_project_folders` (yields model/sidecar/zip paths per
            directory, not a flat file list) instead of the old
            `_walk_matching`. A directory with ≥1 model file gets its
            non-model, non-zip files indexed into `sidecar_files`
            (`common/ingest.py::stage_sidecar` — no hash, no render, just
            presence, surfaced on that folder's project page only, never
            the main grid — a directory with zero model files gets no
            sidecar indexing at all). OS clutter (`.DS_Store`, `Thumbs.db`,
            `desktop.ini` — `common/paths.py::is_ignorable_junk`) is
            filtered out before it ever becomes a sidecar row; without
            this, every folder on a Mac gets a `.DS_Store` sidecar, which
            is exactly what happened the first time this ran against the
            real library. `common/ingest.py::relocate` (used for Downloads)
            now moves a file's **whole containing folder** as a unit
            (collision-suffix-renamed, e.g. `Widget` → `Widget (2)`,
            never merged) when that folder is a genuine leaf (no
            subdirectories of its own) — carries sidecars along and stops
            a downloaded kit's grouping from being destroyed by the old
            per-file flatten. `.zip` files get peeked (`common/
            zip_ingest.py` — `zipfile.namelist()`, no decompression) and
            only tracked in `zip_files` if they contain a recognized model
            extension; Admin's "Pending archives" panel confirms/rejects
            them (rejected rows are kept forever — `ON CONFLICT (path) DO
            NOTHING` on rediscovery means never asked about again).
            Confirming enqueues an `extract_zip` job
            (`services/worker/app/zip_extract.py`) — extracts, deletes the
            original zip, and (for `relocate_to_dropfolder` roots) moves
            the extracted folder into the drop folder the same way `relocate`
            does. Both `run_backfill` and `run_rescan` **materialize their
            walk into a list before doing any relocation** — moving a
            whole folder mid-walk can otherwise disrupt `os.walk`'s
            still-in-progress traversal of that same tree, a hazard the
            old per-file-only relocate never had.

            Also has bambu_metadata.py —
            after rendering a .3mf, checks for Metadata/project_settings.config
            (JSON) and Metadata/slice_info.config (XML) inside the zip; if
            present (a real Bambu Studio project export, not just any 3MF),
            upserts print_metadata with source='auto_extracted_3mf', never
            clobbering a manual edit (ON CONFLICT ... WHERE source != 'manual').
            Runs a one-shot backfill walk
            on startup (hashes inline, no self-queuing), then a Postgres-
            backed job queue consumer (SELECT ... FOR UPDATE SKIP LOCKED, no
            Redis). Image is tagged `spool-worker` and run as TWO Compose
            services off the SAME image, filtered by JOB_TYPES env var:
              - worker      JOB_TYPES=ingest,render   (fast lane, runs backfill)
              - worker-step JOB_TYPES=render_step     (slow CAD lane, RUN_BACKFILL=false)
            This is the "STEP renders shouldn't block quick mesh renders"
            requirement from the spec — real process-level lane separation,
            not just a priority column.
db/migrations/   plain numbered SQL files, NOT a real migration tool (see
                 Gotchas below) — run once by postgres on a fresh volume.
host-helper/     Phase 08 — the one piece NOT in Docker Compose (see below).
```

**host-helper** (native macOS, not a Compose service) — a Linux container
can't launch a macOS GUI app, so `host_helper.py` runs directly on the Mac
as a launchd agent, stdlib-only (`http.server` + `subprocess`, deliberately
no FastAPI/venv to maintain natively — matches the project's "plain jobs
table instead of Redis" minimalism). Listens on `127.0.0.1:8100`; the `api`
container reaches it at `http://host.docker.internal:8100` (Docker Desktop
for Mac resolves that DNS name to the host automatically — no compose
networking config needed). One route, `POST /open` with `{"path", "app"}`:
validates the path exists and the app name is in a server-side allowlist
(`ALLOWED_APPS` — never trust the caller's app name into `subprocess`, even
though the list-form call isn't shell-injectable), then `open -a <app>
<path>`. `services/api/spool_api/host_helper_client.py` mirrors the ext→app
`APP_MAP` (kept in sync by hand — five lines, not worth a shared package
between a Docker image and a native process) and is what
`POST /files/{id}/open` (in `main.py`) calls; the file detail page's
"Open in..." form defaults the app dropdown from the file's extension but
lets you override it per click. Install/manage with
`host-helper/install.sh` / `uninstall.sh` (see Gotchas for why install.sh
copies the script out of this repo rather than running it in place).

## Key decisions & gotchas (read before touching schema or rendering)

- **host_path vs container_path**: `files.path` always stores the real macOS
  path (host-helper needs this later). Watcher/worker only ever see container
  paths (`/roots/dropfolder`, `/roots/library`, `/roots/downloads`). Convert
  with `common/paths.py:to_host_path`/`to_container_path`, keyed off each
  `watched_roots` row's `host_path` + `container_path` pair.
- **Migrations only run once.** `docker-entrypoint-initdb.d` scripts execute
  only on a truly empty `pgdata` volume. Once there's real indexed data, a new
  `.sql` file in `db/migrations/` will NOT get applied automatically — need to
  either apply it by hand (`docker compose exec postgres psql ...`) or wipe
  the volume (`docker compose down -v`, safe only while there's no data worth
  keeping). **We don't have real migration tooling yet** — worth adding
  (Alembic or similar) before Phase 05, once the DB holds data we can't just
  regenerate by re-running backfill.
- **content_hash is nullable.** A file is discovered (path/size) before it's
  hashed — live-ingested files sit with `content_hash IS NULL` until the
  worker's 'ingest' job runs. Backfill hashes inline instead (no self-queuing).
- **Job queue is a plain `jobs` table**, not Redis/Celery — `claim_next_job()`
  in `worker/app/main.py` does the `FOR UPDATE SKIP LOCKED` claim.
- **Headless rendering needs EGL, not OSMesa.** Debian's packaged `libosmesa6`
  doesn't support the core-profile GL context pyrender needs
  (`OSMesaCreateContextAttribs` isn't available) — use
  `PYOPENGL_PLATFORM=egl` with Mesa's software `llvmpipe` driver instead. Also:
  `import pyrender` unconditionally imports its pyglet-based interactive
  `Viewer` even though we only use `OffscreenRenderer` — needs `libx11-6`,
  `libxext6`, `libxrender1` installed just to satisfy that import, never
  actually used. All of this is already in `services/worker/Dockerfile`;
  don't strip those packages out.
- **trimesh's 3MF loader needs `lxml`** (not in trimesh's own dependency list).
- **STEP tessellation via OCP (`services/worker/app/step_loader.py`)** — the
  `cadquery-ocp` PyPI wheel (not `pythonocc-core`, which has poor aarch64 pip
  support) has real prebuilt wheels for linux/aarch64 and Just Worked once
  system libs were right: needs `libgl1` (already there for Phase 02) +
  `libgomp1` (OpenCASCADE uses OpenMP). API surface that works: read via
  `STEPControl_Reader`, tessellate via `BRepMesh_IncrementalMesh` with
  deflection scaled to the part's bounding diagonal (a fixed deflection is
  either too coarse for large parts or overkill for small ones), then pull
  triangles per-face via `TopoDS.Face_s` / `BRep_Tool.Triangulation_s`.
  Two non-obvious cleanup steps are required before `is_watertight`/`volume`
  are trustworthy on a genuinely closed solid — **don't remove these**:
  - `mesh.merge_vertices()` — each B-rep face tessellates independently, so
    vertices along a shared edge between two faces aren't bit-identical.
    Without merging, trimesh sees phantom boundary edges everywhere.
  - `mesh.update_faces(mesh.nondegenerate_faces())` +
    `remove_unreferenced_vertices()` — surfaces with a pole singularity
    (spheres, filleted corners) tessellate with a couple of zero-area
    triangles right at the pole. Real geometry, not a defect, but reads as
    a boundary edge to the watertight check just like the seam issue above.
  Verified against a sphere and a box-with-hole-and-fillets: both correctly
  watertight with volume within ~0.6% of the analytic value after these two
  steps; before them, both false-negatived on `is_manifold`.
- **Docker Desktop bind-mount fs events can duplicate.** The watcher's
  `stage_stub` is idempotent (`ON CONFLICT (path) DO NOTHING`) specifically
  because a single file copy can fire multiple watchdog events. This is
  expected, not a bug — don't "fix" it by adding dedup logic elsewhere.
- **Bambu 3MF metadata schema** (reverse-engineered from real files, not
  documented anywhere official) — `Metadata/project_settings.config` is JSON:
  `nozzle_diameter`/`layer_height`/`sparse_infill_density` (string with a
  trailing `%`!)/`printer_model`/`filament_colour`/`filament_type` — but
  those filament arrays cover **every configured AMS slot**, including ones
  a given print doesn't use. What's *actually* used lives in
  `Metadata/slice_info.config`, which is XML, not JSON: `<plate><metadata
  key="weight"/>` (grams) and `key="prediction"/>` (**seconds**, convert to
  minutes) plus one `<filament>` element per slot actually used on the
  plate. Use slice_info for material/color/weight/time, project_settings for
  process settings (nozzle/layer height/infill). A 3MF without
  `project_settings.config` just isn't a Bambu project file — `extract_bambu_metadata`
  returns `None`, don't treat that as an error.
- **Docker can't attach a new bind mount to a running container** — this is
  why the admin page only edits/pauses the 3 roots that were already mounted
  at container start, and has no "add root" UI. If that's ever built, it
  will need to write the row AND tell the user to run
  `docker compose up -d --build` — there's no way around the restart for a
  genuinely new host path, no matter how clever the polling loop is.
- **HTML `form="id"` attribute** (not `<form>` wrapping table rows, which is
  invalid HTML5) is how `admin.html` associates each row's inputs with its
  own POST form — see the pattern there if adding more per-row edit forms.
- **Testing note**: any file written into the real bind-mounted watched
  folders (even via a throwaway `docker compose run` script) gets picked up
  by the live watcher/backfill for real, since they're the actual host
  folders — not a bug, just remember to clean up test artifacts from both
  disk AND the `files`/`jobs` tables afterward (happened twice while building
  Phase 03; also now touches `sidecar_files`/`zip_files`/`projects` since
  the folder/sidecar/zip work). A bulk `cp -r` (creating a whole directory
  tree in one shot) is *not* reliably caught by the live watcher — confirmed
  while testing folder-preserving relocate, a bind-mount fs-event quirk
  consistent with the existing "Docker Desktop bind-mount fs events can
  duplicate" gotcha below (here it under-delivers instead). Individual
  `mkdir` + `cp` calls into an already-existing watched directory fire
  normally; Phase 07's periodic rescan is the reliable fallback either way.
- **Whole-folder relocate only preserves structure for true leaf folders**
  (`common/ingest.py::relocate` — checks `os.scandir(parent_dir)` for any
  subdirectory) — a folder containing *another* folder with its own model
  files falls back to flattening the individual file instead of moving the
  whole tree. Deliberate: moving a folder with nested subdirectories mid-walk
  could invalidate `os.walk` entries `run_backfill`/`run_rescan` already
  materialized for that nested folder. Matches the existing "flat per leaf
  folder" rule already accepted for folder-grouping.
- **Zip extraction into a read-only-mounted root fails loudly, by design**
  — the `Library` root is mounted `:ro` in `docker-compose.yml` (per Sheet 07
  of the spec, since `index_in_place` roots are never supposed to be
  written to); if a zip found there is confirmed, `process_extract_zip_job`
  hits a permissions error, which surfaces as `zip_files.error` in Admin
  rather than crashing the worker. Not a bug — extraction genuinely can't
  happen on a read-only mount; reject those or extract them manually
  outside SPOOL instead.
- **`files.mtime` starts `NULL` on rows from before migration 006** — the
  rescan drift check (`services/worker/app/rescan.py`) deliberately treats a
  `NULL` mtime as "changed," so the very first rescan pass after that
  migration re-hashes every existing file once (just confirms the hash
  still matches; harmless at personal-library scale). Don't try to
  backfill `mtime` for old rows to "avoid" that pass — it's a one-time,
  self-correcting cost, not a bug.
- **Docker Desktop restarting drops all containers, not just pauses them**
  (confirmed while testing Phase 07 — `docker compose ps` came back
  completely empty after Docker Desktop was quit/relaunched). `pgdata` and
  `thumbnails` are named volumes so the actual data survives; `docker
  compose up -d` recreates the containers from the already-built images
  (no rebuild needed) and the worker's one-shot backfill on the way back up
  is a no-op if nothing changed while it was down. Don't assume a `docker
  compose ps` with no rows means the project was torn down — check for
  volumes before doing anything destructive.
- **macOS TCC blocks a launchd-spawned `python3` from reading a script
  under `~/Documents`** (confirmed while building Phase 08 — launchd's
  `python3 host_helper.py` failed with "Operation not permitted" reading
  the script straight out of this repo, even though running the exact same
  script manually from a Terminal shell works fine). Terminal has already
  been granted Files-and-Folders access; a freshly-launchd-spawned process
  hasn't, and there's no way to pre-grant it without a manual System
  Settings → Privacy & Security click-through. `host-helper/install.sh`
  works around this by **copying** `host_helper.py` to
  `~/Library/Application Support/spool-host-helper/` (not one of the
  TCC-protected folders) and pointing the plist at that copy instead of the
  repo path — re-run `install.sh` after editing `host_helper.py` to pick up
  changes, editing the repo copy alone does nothing.
- **A second, separate TCC wall for actually deleting files** (not just
  reading the host-helper script) — confirmed while building the
  duplicate-file admin UI: `os.remove()` on a real file under
  `~/Documents/3DPrintFiles` failed with the same "Operation not
  permitted" until Full Disk Access was granted to `/usr/bin/python3` in
  System Settings → Privacy & Security (one-time manual grant, same as
  the read-side issue above but a *different* permission — moving the
  script out of `~/Documents` doesn't help here, since the target being
  written to is the protected folder, not the script's own location).
  `open -a` (used by `/open`) never hit this, since it just hands off to
  LaunchServices rather than touching the file itself — any *new*
  host-helper endpoint that directly reads/writes/deletes a file under a
  watched root should expect to need this same grant.
- **The real installed app bundle names differ from both the spec's casual
  wording and marketing names** — checked via `ls /Applications` /
  `~/Applications` rather than assuming: it's `Autodesk Fusion.app` (in
  `~/Applications`, not `/Applications` — Autodesk's installer put it in
  the per-user location, and Autodesk dropped "360" from the name at some
  point) and `BambuStudio.app` (no space), not "Fusion 360.app" / "Bambu
  Studio.app". `open -a` matches on the real bundle name, so
  `host_helper.py`'s `APP_MAP` uses these exact strings — if either app is
  ever reinstalled/renamed, re-check with `ls` rather than guessing.
- **Applying a migration to a live (non-empty) DB**: confirmed working —
  `docker compose exec postgres psql -U spool -d spool -f /docker-entrypoint-initdb.d/00N_whatever.sql`
  (the migrations folder is bind-mounted into the postgres container at that
  path already, so the file's already there — no need to copy it in).
- **htmx is vendored at build time**, not loaded from a CDN — `api/Dockerfile`
  fetches it via `ADD https://unpkg.com/...` during the image build (network
  access at build time is already normal, same as pip/apt), so the running
  app never needs network access at runtime. Keep it this way — matches the
  "all local" design; don't switch to a `<script src="https://...">` CDN tag.
- **No browser automation tooling on this host** — no Node, no Playwright, no
  chromium-cli. To visually verify the UI, ran a throwaway
  `mcr.microsoft.com/playwright:v1.48.0-jammy` container on the same Compose
  network (`--network data-platform_default`), `npm install playwright`
  inside it, and drove `http://api:8000` directly (Compose's internal DNS —
  no need to go through the host port mapping). Worked well; consider
  `/run-skill-generator` to capture this as a reusable project skill if UI
  verification keeps coming up.
- **Real watched roots are hardcoded** in `db/migrations/003_seed_watched_roots.sql`
  for this machine (`/Users/jo/...`) — this is a personal local tool, not
  meant to be portable. Current roots:
  - Drop folder: `~/Documents/3DPrintFiles` (created fresh, empty until used)
  - Library: `~/Documents/3D Printing` — no longer a placeholder, actively
    being populated with the real library (hundreds of real files as of
    this writing). The DB label still reads "Library (placeholder)" in
    the admin page — cosmetic only, harmless to leave or rename via the
    admin page whenever convenient.
  - Downloads: `~/Downloads`, `ingest_mode = relocate_to_dropfolder`

## Running it

```
docker compose up -d --build        # bring up postgres, api, watcher, worker
docker compose ps                   # check health
curl localhost:8000/health          # confirm api <-> postgres
docker compose logs worker -f       # watch backfill/render/ingest activity
docker compose logs watcher -f      # watch live fs events
docker compose exec postgres psql -U spool -d spool   # inspect data directly
docker compose down                 # stop (keeps pgdata + thumbnails volumes)
docker compose down -v              # stop AND wipe volumes (only if no data worth keeping)
```

`.env` (gitignored) holds real local paths/credentials — copy from `.env.example`
if it's ever missing.

host-helper is native, not Compose — install once (and re-run after editing
`host_helper.py`):
```
host-helper/install.sh                        # copies + starts the launchd agent
launchctl print gui/$(id -u)/com.spool.hosthelper   # confirm it's running
tail -f ~/Library/Logs/spool/host-helper.log        # watch open requests
host-helper/uninstall.sh                      # stop + remove it
```

Automated tests (`tests/`) run as plain `pytest` on the host against a real
Postgres — `docker compose up -d postgres` must be running (exposes
`localhost:55432`), then:
```
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest
```

**To verify a UI change**, use the `run-spool` skill
(`.claude/skills/run-spool/SKILL.md`) rather than re-deriving the
no-browser-tooling workaround — `driver.sh <script.mjs>` runs a Playwright
script against `http://api:8000` in a throwaway container on the Compose
network. See `example-flow.mjs` in that directory for the pattern.

## Next: Phase 09 — polish & scale

Search relevance, thumbnail cache tuning, and a performance pass for a
genuinely large library — per the original spec's closing phase. Paused
(at the user's request) while the real library gets populated — it's
actively filling in now (790 real files under `Library`, well past the
old placeholder-path state), so there's finally real scale to work
against.

- [x] Thumbnail cache tuning — see the ad hoc backlog entry below
      (`CachedStaticFiles` + content-hash-versioned URLs).
- [ ] Search relevance — still ILIKE + a fixed sort dropdown, no
      relevance ranking. At 790 rows a sequential scan is still trivially
      fast (checked: no missing indexes are actually causing slow
      queries yet), so this is a quality-of-ranking problem, not a
      performance one.
- [ ] General performance pass — revisit once the library is large enough
      that `EXPLAIN ANALYZE` on the search query actually shows a
      sequential scan cost worth caring about; premature to add indexes
      or restructure queries against 790 rows with nothing slow yet.

While populating the library, three ingestion-pipeline gaps surfaced
outside the Phase 09 pause (not part of it, just concurrent unplanned
work): the folder-grouping threshold, sidecar-file indexing, and
zip review/extraction — all described in the worker/ section above and
their own gotchas below.

## Ad hoc feature backlog (post-Phase-08, outside the phase structure)

User-requested additions being worked through in size order (small batches
first), independent of the paused Phase 09:

- [x] Grid cards show dimensions (`_results.html`/`project_detail.html`,
      needs `bbox_x/y/z` in the query SELECT).
- [x] Search matches `print_metadata` (material/printer/slicer/notes), not
      just filename — `queries.search_files`'s `q` condition grew an
      `id IN (SELECT file_id FROM print_metadata WHERE ...)` branch.
- [x] Ext badges are color-coded per format (migration-free — `--ext-stl`/
      `--ext-3mf`/`--ext-step` CSS vars, first 3 slots of the dataviz
      skill's fixed categorical order; `.step`/`.stp` share one class/color
      since they're the same format. Hue is accent-only — background tint
      + border, never the label's own text color — the skill's default
      palette flags slot 3 as failing light-mode text contrast on its own,
      and "text wears text tokens" is a hard rule regardless). Reused via
      a Jinja filter (`filters.py::ext_class`), not repeated template logic.
- [x] Per-file editable `display_name` (migration 009) — `NULL` means "just
      show `filename`," resolved via `display_name or filename` wherever a
      name is rendered (grid cards, file detail `<h1>`, relationship
      labels, the relationship link-picker). Edited via a plain form on the
      file detail page, `POST /files/{id}/name`.
- [x] "Printed" toggle + 1-5 star rating + comments per file — new
      `print_log` table (migration 010), deliberately separate from
      `print_metadata` so marking a file printed never touches that
      table's `source` column (which gates auto-extraction overwrites —
      folding this into `print_metadata` would have silently blocked
      future Bambu re-extraction for any file someone just marked
      printed). Field is named `comments`, not `notes`, specifically
      to avoid colliding with `print_metadata.notes` as a form field
      name on the same page (caught during testing — same name on two
      different `<textarea>`s on one page is a real footgun, e.g. a
      Playwright `page.fill('textarea[name="notes"]')` silently filled
      the wrong one). Star rating is a CSS-only radio/label trick
      (`.star-rating`, reverse DOM order + `flex-direction: row-reverse`
      + `~` sibling selectors); the rating/comments fields are revealed
      only once "printed" is checked, via `:has()` — no JS.
- [x] `.svg` and `.scad` file support — both added to `MODEL_EXTENSIONS`
      (`common/config.py`) and get a `render` job (fast lane) like STL/3MF,
      but `process_render_job` (`worker/app/main.py`) branches by
      extension before touching trimesh: `.svg` → `render_svg_thumbnail`
      (`worker/app/render.py`) just copies the file into `thumbnails/` as
      `{file_id}.svg` — browsers render SVG natively and safely even via a
      plain `<img>` tag (no script execution in that context), so no
      rasterization dependency was needed. `.scad` → marked
      `render_status='done'` immediately with no thumbnail (deliberately
      no preview — a real one means running arbitrary `.scad` scripts
      through the OpenSCAD CLI, a much heavier dependency than anything
      else in this project; settling at `done` instead of `pending`
      avoids it looking like a stuck job). Both map to an app in
      `host_helper.py`/`host_helper_client.py`'s `APP_MAP` (`.svg` →
      BambuStudio, `.scad` → Autodesk Fusion, per the user's instruction).
      Ext-badge color-coding deliberately stops at 4 slots (stl/3mf/step/
      svg) — the dataviz skill's palette only validates *all-pairs*
      comparisons (any two badges might sit side by side in a grid, not
      just adjacent-in-sequence) through its first four slots; `.scad`
      (no preview anyway) stays the neutral default badge style rather
      than reach for an unvalidated 5th hue.
- [x] `zip_files` uniqueness moved from `path` alone to `(path,
      content_hash)` (migration 011) — a rejected zip was staying rejected
      *forever for that path*, which is wrong for a common filename like
      "Archive.zip" that legitimately gets reused for different downloads
      over time (old one deleted, new one dropped in with the same name).
      `zip_ingest.py::stage_zip_if_relevant` now hashes the zip (only after
      the cheap namelist-peek already confirmed it's worth tracking, so an
      irrelevant zip never pays this cost) — same content at the same path
      still won't be re-asked about, but different content at a
      previously-used path gets a fresh row and a fresh `suggested` status.
      **Gotcha hit applying this**: existing rows had `content_hash = NULL`
      post-migration, and Postgres treats NULLs as distinct for uniqueness
      purposes — so the *next* scan of an already-known zip would insert a
      new row instead of matching the old one (briefly "re-asking" about
      already-decided zips once), since NULL never equals a real hash.
      Backfilling `content_hash` for existing rows (hash the file if it's
      still on disk) avoids the one-time gap; confirmed live during this —
      also confirmed the underlying fix itself works: a genuinely different
      "Archive 2.zip" showed up as a fresh `suggested` row alongside the
      old `rejected` one for the same path, exactly as intended.
- [x] Rejected-archives review page (`/admin/rejected-archives`, linked
      from the main Admin page) — lists everything with
      `status='rejected'` with an "Un-reject" button
      (`queries.unreject_zip` → back to `suggested`, reappears in the
      normal Pending archives flow). The file itself is never touched by
      either state.
- [x] Duplicate-file review/deletion admin UI (`/admin/duplicates`) —
      groups files by identical `content_hash` directly (`queries.
      list_duplicate_groups`), not by walking `duplicate_of` relationship
      rows — same hash always means the same render (rendering is a
      deterministic function of file bytes), so a `GROUP BY content_hash
      HAVING count(*) > 1` answers the whole question without needing a
      relationship row to exist for every pair. Actual deletion required a
      **new host-helper endpoint** (`POST /delete`) — the `api` container
      has no filesystem access at all (only `thumbnails` is mounted), and
      even `worker`/`watcher` can't write to the `:ro`-mounted `Library`
      root, so deletion has to go through host-helper the same way "Open"
      does. Confirmed live while building this: deleting (unlike
      launching an app via `open -a`, which just hands off to
      LaunchServices) needs the process itself to hold real filesystem
      permission — macOS blocked host-helper's `os.remove()` with
      "Operation not permitted" until Full Disk Access was granted to
      `/usr/bin/python3` in System Settings → Privacy & Security (can't be
      done from a script — one-time manual grant). Unlike `/open`,
      `/delete` independently re-validates the path falls under a
      hardcoded allowlist of the known watched-root host paths before
      touching disk (`ALLOWED_DELETE_ROOTS` in `host_helper.py`) — a
      deliberately stronger check than `/open` gets, since deletion is
      irreversible. The DB row is only deleted after the disk delete
      actually succeeds (never the reverse), so a failed/denied delete
      never leaves a "phantom" untracked-but-still-present file. "Select
      all" (checks every non-oldest copy per group, leaving the first/
      earliest `first_seen_at` file unchecked) is the one place in the
      whole UI with real inline JS — no CSS-only trick makes one checkbox
      toggle a set of unrelated others, and the feature was explicitly
      requested as a bulk action.
- [x] Test coverage — worker ingestion/heuristics first (`tests/common/`,
      `tests/worker/`; 51 tests). Plain `pytest` against a **real** Postgres
      (`spool_test`, a separate database on the same `postgres` container —
      needed its own host port mapping, `55432:5432` in `docker-compose.yml`,
      since `postgres` was previously internal-only) rather than mocking the
      DB, since most of this codebase's real complexity lives in SQL/schema
      interactions. `tests/conftest.py`'s session-scoped fixture
      (re)creates `spool_test` and applies every migration **except**
      `003_seed_watched_roots.sql` (personal hardcoded paths — applying it
      would make `run_backfill`/`run_rescan` walk the *real* filesystem
      during tests, since tests run on the host, not in a container) via
      the exact already-documented manual-apply mechanism (`docker compose
      exec postgres psql -f /docker-entrypoint-initdb.d/00N_x.sql`), not a
      new migration-runner. Per-test isolation is a rollback, not
      re-migration: `common/db.py:get_connection()` always uses
      `autocommit=True` (the real app never rolls anything back), but every
      function under test takes `conn` as an explicit parameter rather than
      opening its own connection — so the `conn` fixture just opens its
      own connection with autocommit **off** and calls `conn.rollback()` at
      teardown, with no monkeypatching needed. `pyproject.toml`'s
      `pythonpath` makes `common` and `worker`'s `app` package importable
      directly (`services/api` route tests came later — see their own
      entry below for how the `app`-vs-`app` package collision that
      blocked this originally got resolved).
      Run with `docker compose up -d postgres` (already the normal dev
      state) then `python3 -m venv .venv && .venv/bin/pip install -r
      requirements-dev.txt && .venv/bin/pytest` from the repo root — the
      venv deliberately doesn't include `services/worker/requirements.txt`'s
      heavy geometry deps (trimesh/pyrender/cadquery-ocp), since none of
      the worker-first target modules import `render.py`/`step_loader.py`.
      Confirmed the suite actually exercises the real code (not
      tautological) by deliberately breaking the `duplicate_of` hash-match
      query mid-session — exactly the two tests depending on it failed,
      nothing else did.
- [x] Custom favicon — `services/api/spool_api/static/favicon.svg`, a simple
      spool/reel glyph in the UI's existing `--accent` blue, wired via a
      plain `<link rel="icon" type="image/svg+xml">` in `base.html`. SVG
      favicons need no build step/rasterization and scale cleanly.
- [x] `README.md` for GitHub (separate from `CLAUDE.md`, which stays the
      detailed internal build log/gotchas doc) — project pitch, feature
      list, a real screenshot (`docs/screenshot-library.png`), setup
      instructions, and a license section. `LICENSE` is the unmodified
      canonical GPLv3 text fetched directly from `gnu.org` rather than
      typed out by hand (long verbatim legal text is exactly the kind of
      output that can trip an LLM content-length filter — fetching the
      authoritative source sidesteps that and guarantees byte-accuracy
      either way). Copyright/attribution line lives in the README, not
      inserted into the LICENSE file itself — GPLv3's canonical text has
      no name/year placeholder the way MIT's template does; the license
      says to add short notices to source files instead, which this
      project hasn't done per-file (a reasonable-for-a-personal-project
      simplification, not a requirement).
  - **License is changeable later, with one caveat** (came up mid-decision,
    worth remembering): as sole author, the user can relicense *future*
    commits/releases anytime, but can't retroactively change the terms for
    a copy someone already received under the old license (e.g. Redis Inc.
    relicensing away from BSD didn't stop the community forking the last
    BSD-licensed snapshot — that fork became Valkey). Moot for now since
    the GitHub repo is currently **private** — nobody outside the user has
    received a copy under any license yet, so there's no lock-in until the
    repo actually goes public or is shared (task above, still pending).
- [x] Sort-by filter on the library page (`newest`/`oldest`/`name_asc`/
      `name_desc`/`size_desc`/`size_asc` — `queries.SORT_CLAUSES`, a fixed
      whitelist dict mapping each option to a trusted SQL fragment, since
      `ORDER BY` can't be parameterized the way `WHERE` values can; the
      lookup itself is what keeps this injection-safe, not string
      escaping). Wired into the same htmx live-update trigger the
      extension/tag checkboxes already use.
- [x] Search also matches `print_log.comments` (the "printed" feature's
      own notes-to-self field, migration 010) — same `id IN (SELECT
      file_id FROM ... WHERE ... ILIKE %s)` pattern already used for
      `print_metadata`, just a second table.
- [x] Search understands a few structured print-settings phrasings —
      "0.2mm nozzle", "20% infill", "0.12mm layer height" — that plain
      `ILIKE` can't reach, since Bambu's auto-extraction
      (`worker/app/bambu_metadata.py`) writes these as plain numbers
      inside `print_metadata.settings_json` (e.g. `"nozzle_diameter_mm":
      0.4`), not as text containing "mm"/"nozzle" anywhere.
      `queries._structured_metadata_clauses` is a keyword-presence +
      nearest-number heuristic (not a real parser — "nozzle" or "layer"
      or "infill" anywhere in `q`, plus the first number found anywhere in
      `q`), so both "0.2mm nozzle" and "nozzle 0.2mm" work; matches with a
      small tolerance (`BETWEEN value±0.005` for mm fields, `±0.5` for the
      percent field) rather than exact float equality, and the JSONB
      value is regex-validated as numeric-looking before the `::float`
      cast so a future non-numeric value in that key can't raise a
      runtime cast error. Purely additive — ORed alongside the existing
      filename/print_metadata/print_log text search, so a query matching
      no structured pattern behaves exactly as before.
- [x] Editable project name (`project_detail.html`) — a pencil icon next
      to the `<h1>` toggles a `<details>/<summary>` reveal (no JS needed
      for the toggle itself — the one native HTML idiom for "click to
      reveal a section"), containing a plain rename form,
      `POST /projects/{id}/name` → `queries.set_project_name`.
- [x] Bulk review pages for suggestions (`/admin/suggested-projects`,
      `/admin/suggested-relationships`, linked from Admin) — every
      `status='suggested'` row across the whole library on one page instead
      of one file/project at a time, with individual Confirm/Reject buttons
      per row plus a "select all" + bulk-accept form (same one-inline-JS
      checkbox-toggle pattern as `/admin/duplicates`, since no CSS-only
      technique exists for one checkbox to set a set of unrelated others).
      Both pages are thin wrappers around already-proven query functions
      (`confirm_file_project`/`reject_file_project`,
      `confirm_relationship`/`reject_relationship`) reused from the
      per-file panels — the new routes just target a library-wide list
      instead of redirecting to a single file/project page. New query
      functions `list_suggested_project_assignments()` and
      `list_suggested_relationships_all()` (the latter always uses the
      "out"/from→to label phrasing since both files are shown side by
      side, unlike the per-file panel which is relative to "this" file).
      Bulk-accept posts `pairs=<project_id>:<file_id>` (projects) or
      `rel_ids=<id>` (relationships) as repeated form fields, same
      `list[str]`/`list[int] = Form([])` pattern already used by
      `/admin/duplicates/delete`. Verified confirm/reject/bulk-accept all
      three ways against synthetic rows (a throwaway `__test_project__`
      project and a throwaway `variant_of` relationship between two real
      files, inserted and deleted via `psql` directly) rather than
      clicking real suggestions on the live library, since confirming a
      real suggestion as a "test" would permanently alter actual project/
      relationship data.
- [x] Filter out macOS AppleDouble shadow files (`._<name>`) — noticed
      live in the new suggested-projects page (`._Hammer handle.stl` sitting
      right next to the real `Hammer handle.stl`, both grouped into the same
      suggested project). These carry a real model extension, so
      `is_model_file` alone can't exclude them — `is_ignorable_junk`
      (`common/paths.py`) now also matches any `._`-prefixed basename, and
      the check moved earlier in `_walk_project_folders`
      (`worker/app/backfill.py`, shared by rescan) so a `._*` path is
      dropped from `full_paths` before it's ever classified as model/
      sidecar/zip — same fix applies to the live watcher
      (`watcher/app/main.py::RootEventHandler._handle`), which previously
      didn't call `is_ignorable_junk` at all. Cleaned up the 142 already-
      indexed `._*` rows from the real library (`files` + `sidecar_files`,
      cascade-deletes their tags/relationships/project_files/print_metadata/
      print_log rows via existing `ON DELETE CASCADE`) — confirmed none had
      thumbnails generated, and confirmed a fresh backfill doesn't re-stage
      them now that the filter runs earlier.
- [x] UI polish pass (font-size scale, custom `<select>` styling, spacing) —
      requested after the user flagged the library page's sort dropdown as
      "not very nice" next to the styled search input, plus general
      cramped vertical space and inconsistent font sizes across the app.
      `style.css` gained a 7-step type scale (`--fs-2xs` through `--fs-2xl`,
      11–22px) that every font-size declaration now resolves to instead of
      the ~13 ad hoc decimal values that had accumulated feature-by-feature
      (two deliberate off-scale exceptions stay literal: the 32px empty-
      state extension glyph and the 22px star-rating icon, since those are
      UI elements sized as icons, not body text). Every `<select>` in the
      app (sort, ingest-mode, parent-project, app-picker, relationship-type)
      gets `appearance: none` + a CSS-only chevron (inline SVG data-URI,
      separate light/dark stroke colors) instead of relying on OS chrome —
      **gotcha**: the per-context rules that also set a plain `background:`
      shorthand (`.inline-form select`, `.admin-table select`, `.stack-form
      select`) had to switch to the `background-color` longhand, since the
      shorthand resets `background-image` to `none` and would silently
      kill the chevron. The library page's extension checkboxes became
      pill-style toggles reusing the same per-extension accent colors as
      the grid's ext-badges (CSS `:has(input:checked)`, same checkbox-
      hiding technique as the existing star-rating widget — no JS). Added
      a global `button {}` base rule so the several admin buttons that had
      no class at all (zip Confirm/Reject, Un-reject, Delete/Accept
      selected) stop rendering as raw unstyled OS buttons; a two-tier size
      system distinguishes primary-CTA buttons (`.searchbar`/`.stack-form`/
      `.printed-log-form button`, 10px/20px) from compact inline ones
      (`.inline-form`/`.admin-table button`, 6px/12px) rather than making
      every button identical, which would have flattened the UI's visual
      hierarchy. `admin.html` was restructured from four bare `<h1>`
      sections running directly into each other into a single page title
      plus four `.panel` cards (new `.admin-sections` wrapper) — same
      treatment already used on the file detail page. `projects.html`'s
      create-project form is now wrapped in its own `.panel` card instead
      of floating loose above the project list. Panel padding/gap and
      project-list row padding all increased for more breathing room.
- [x] Folder-grouping ignores generic container folder names — a common
      download/export convention is `<ProjectName>/files/widget.stl`,
      where `files` is just the model-file container, not the project's
      actual identity. `suggest_folder_project` (`relationship_suggest.py`)
      was naming the suggested project after the *immediate* folder
      (`files`) every time, so unrelated projects using this convention
      all collided into one shared "files" project — confirmed live: the
      real library had 53 files from 11+ unrelated kits (a bookshelf kit,
      several 3DBenchy variants, etc.) merged into one confirmed `files`
      project. New `_GENERIC_CONTAINER_NAMES = {"files"}` set: when the
      immediate folder's name matches, the project name/lookup falls back
      to the *parent* folder's name instead — sibling detection stays
      scoped to the original folder (so the right files still get
      grouped), only the identity used for naming/matching changes. Falls
      back to keeping `files` as-is in the rare case where the generic
      folder sits directly in the watched root (no more-meaningful parent
      to use). Cleaned up the existing real `files` project by re-deriving
      the correct project per file from its actual path and moving each
      file across (preserving `confirmed` status, since the user had
      already vetted these as real project members — just wrongly
      grouped); one-off script initially missed the same watched-root
      edge case the real code guards against (2 files whose `files`
      folder sat directly under the watched root got a bogus project
      named after the watched root itself, `3DPrintFiles`) — caught and
      corrected by hand before considering the cleanup done.
- [x] Sidecar files render as grid cards, merged into the project's own
      "Files" grid (appended after the model-file cards, no separate
      section) — image sidecars (a kit's preview photo, etc.) get a real
      thumbnail; everything else gets the same ext-label placeholder
      treatment as an unrendered model file. A muted gray tint
      (`color-mix(in oklab, var(--ink-muted) 24%, var(--surface))` on
      both background and border, checkerboard removed since it's not a
      "possible transparency" cue here) visually separates "just a file
      that lives alongside the models" from an actual 3D-printable file,
      applied uniformly regardless of the sidecar's own extension — this
      is an accessory/model distinction, not a format one, so it
      deliberately doesn't reuse the ext-badge hues. Clicking a sidecar
      card opens the real file on the host (via host-helper) instead of
      navigating to a detail page it doesn't have — the card is a
      `<button>` inside a `<form>` (`POST /projects/{id}/sidecars/{id}
      /open`), the `<form>` wrapper is `display: contents` (same trick as
      `chip-inline-form`) so it disappears from the grid's box model and
      the button is the effective grid item; `button.card` resets the
      width/padding/text-align the global `button{}` base rule would
      otherwise impose (background/border/color don't need resetting —
      `.card`'s class selector already outranks the bare `button` type
      selector regardless of source order). Sidecars aren't CAD files
      with one obvious app to open them in (a README, a PDF, a preview
      photo), so this needed a new host-helper code path: `POST /open`
      with no `app` field now hands off to `open <path>` (no `-a` flag),
      letting macOS/LaunchServices pick the file's own default handler,
      rather than extending `APP_MAP`/`ALLOWED_APPS` to guess apps for
      formats with no natural CAD-app mapping. New `sidecar_files.
      thumbnail_path` column (migration 012); `stage_sidecar` copies an
      image sidecar into the thumbnails dir the same lightweight way SVG
      model files get their preview (plain `shutil.copyfile`, no
      rasterization needed since it's already a raster image) —
      `common/ingest.py` reads `THUMBNAILS_DIR` the same
      `os.environ.get`-with-fallback way `render.py` does, safe to import
      from the watcher (which never calls `stage_sidecar`) since nothing
      requires the env var at import time. Verified live end-to-end
      against a real project folder: staged a throwaway `preview.jpg`
      sidecar (bypassing the ~5min rescan wait via a one-off script
      calling `stage_sidecar` directly in the worker container), confirmed
      the thumbnail copy landed in the shared `thumbnails` volume,
      confirmed clicking the card in the browser actually launched
      Preview.app on the Mac for the real file, then cleaned up the test
      file from disk, the sidecar row, and its thumbnail.
- [x] Chip sizing fix — a long project name in the suggested-project chip
      (`.suggest-chip`, badge + name + confirm/reject icons all in one
      pill) stretched the `border-radius: 999px` pill into a distorted
      oval as the name wrapped across several lines, since the chip has
      no cap on its own height. First fix attempt (a hardcoded `max-width:
      180px` on `.chip a`) was wrong for this specific variant — the
      suggested chip has more sibling content (badge + 2 icon buttons)
      competing for the same space as the plain confirmed chip, so a
      static guess that fit one didn't fit the other and just moved the
      overflow from "too tall" to "too wide." Real fix: `.chip` gets
      `max-width: 100%; min-width: 0` (so it can actually shrink within
      its flex container instead of overflowing), the name link becomes
      `flex: 1 1 auto; min-width: 0` (so *it* absorbs all the shrinking,
      truncating via ellipsis to however much room is actually left),
      and the badge/icon-button siblings get `flex-shrink: 0` (so they
      keep their natural size instead of squeezing). Also dropped
      `border-radius` from `999px` (full pill) to `6px`, matching the
      input/select radius elsewhere — a true pill shape reads as broken
      once it's forced wide/tall by long content; a rounded rectangle
      doesn't. `title="{{ name }}"` added to both chip variants' project
      links so the full name is still available on hover once truncated.
- [x] "Open in..." replaced with real per-app icon buttons — the file
      detail page's dropdown + separate "Open" button became one icon
      button per app (`.app-icons`), each a direct click-to-open (no
      selection step). Icons are the actual macOS app icons, extracted
      **once** as a manual step, not via a live host-helper endpoint:
      `sips -s format png <bundle>/Contents/Resources/<icon>.icns --out
      services/api/spool_api/static/icons/<name>.png` (`sips` is a built-in
      macOS CLI, no new dependency) — found each icon's filename via
      `/usr/libexec/PlistBuddy -c "Print :CFBundleIconFile" <bundle>/
      Contents/Info.plist` rather than guessing (`Icon.icns` for
      BambuStudio, `Fusion_Launch.icns` for Autodesk Fusion). These never
      change short of a reinstall, so they're checked-in static assets
      like `favicon.svg`, not something worth a dynamic extraction/
      caching feature. `host_helper_client.APP_ICONS` maps app name ->
      icon filename (alongside the existing `APP_MAP`/`ALL_APPS`); the
      default app for the file's extension gets an accent border
      (`.app-icon-default`) so it's still visually distinguished even
      though every icon is now an equally-real click target, not just the
      dropdown's pre-selected option. Verified live: clicking the
      BambuStudio icon for a real `.3mf` file actually launched
      BambuStudio with that file, same as the old dropdown+button flow.
- [x] Fixed `None` literally rendering in the print-metadata form —
      `{{ print_metadata.material if print_metadata else '' }}` renders
      the Python `None` as the *text* "None" whenever the row exists but
      that specific column is NULL (the `if/else` only guards against no
      row at all). Affected all four fields (material, printer, slicer,
      notes), not just the one originally reported — same class of bug
      already fixed once this session for `print_log.comments`. Fixed by
      wrapping each with `(x or '') if print_metadata else ''`.
- [x] `common/text.py::clean_name` — strips literal URL encoding from
      displayed names (a Thingiverse/Printables download convention: a
      "+" for space from a query-string filename, or literal `%20`-style
      escapes, both extracted onto disk without decoding). Cosmetic only
      — applied wherever a name is *displayed* (via a `clean_name` Jinja
      filter in the api, and directly in Python for names already
      resolved server-side like `_fetch_relationships`), never touching
      the real `files.path`/`filename` columns or the file on disk, so
      search/host-helper/relocate all keep working against the real
      value. Guarded to only fire when the name has a `%XX` escape or a
      "+" with no real space already present, so a name that
      legitimately contains a literal "+" (rare, but e.g. "C++ Project")
      isn't mangled. Shared between the worker (project names, folded
      into `suggest_folder_project`, replacing its earlier narrower
      "+"-only `_cleanup_folder_name` helper) and the api (file/sidecar
      names) via `common/`, rather than duplicating the heuristic in two
      places the way `host_helper.py`/`host_helper_client.py`'s `APP_MAP`
      is (that duplication crosses a container boundary; this one
      doesn't — both services already import `common`). Applied to the
      existing real "4th+of+July+Uncle+Sam+Hat" project by hand
      (renamed via `UPDATE projects SET name = ...`) since the fix only
      changes behavior for future folder-grouping suggestions, not
      already-created rows.
- [x] Folder-grouping now matches by real folder *path*, not name —
      closes the long-standing "Deliberate scope boundary" that same-
      named leaf folders in unrelated parts of the library (two different
      "misc" dumps, say) merged into one shared suggested project.
      Migration 013 adds `projects.source_folder_path` (nullable,
      `UNIQUE`); `suggest_folder_project` looks up/creates projects by
      this column instead of `lower(name) = lower(folder_name)`. A
      project created any other way (the manual "+ new project" form)
      has a NULL `source_folder_path`, so it's never a match candidate —
      only projects this function itself created can be reused by it,
      which also fixes a smaller latent bug: a manually-created project
      that happened to share a name with a real folder could previously
      have suggestions silently glued onto it. Renaming an auto-created
      project (the pencil-edit UI) no longer breaks future matching for
      that folder either, since the lookup key is the path, not whatever
      the name currently is — previously a rename would have caused the
      *next* new file in that folder to spawn a duplicate project under
      the old auto-generated name. The generic-container-name fallback
      (`_GENERIC_CONTAINER_NAMES`, e.g. `.../ProjectName/files/x.stl`)
      now resolves the *same* parent folder for both the match path and
      the display name, rather than just the name as before.
      Backfilled `source_folder_path` for the 23 existing real projects
      by deriving each one's folder from its member files' actual paths
      (only when all members agreed on one directory — none were
      ambiguous). **Caught one edge case the backfill script initially
      missed**: a project whose only member file sat directly in the
      watched root itself got backfilled to the root's own path, which
      `suggest_folder_project` would never actually produce (it returns
      early before ever reaching the matching logic for that case) —
      corrected that one row back to NULL by hand after noticing it in a
      spot-check, rather than leaving stale/impossible data in place.
- [x] API test coverage (`tests/api/`) — closes the gap noted when
      worker-first test coverage was originally built: `services/api`'s
      package was literally named `app`, the same as the worker's, and
      two same-named top-level packages can't coexist on `sys.path` in
      one pytest session. Fixed at the root: `services/api/app/` was
      renamed on disk to `services/api/spool_api/` (`git mv`, keeping
      history) — its `Dockerfile`'s `COPY api/app ./app` became `COPY
      api/spool_api ./app`, so the *container-internal* package name is
      still `app` and the `uvicorn app.main:app` CMD didn't need to
      change at all, only the copy source. `pyproject.toml`'s
      `pythonpath` gained `"services/api"`, making `spool_api` importable
      alongside worker's `app` in the same session. Two more things had
      to be handled before `spool_api` would even import cleanly under
      pytest: `common/db.py` reads `DATABASE_URL` at *import* time, and
      `spool_api/main.py` does an unconditional `os.makedirs(THUMBNAILS_
      DIR)` at import time too (the production default, `/data/
      thumbnails`, doesn't exist on a host run outside Docker and can't
      be created without root) — both env vars are now force-set at the
      very top of the root `tests/conftest.py`, early enough to apply
      before any test file anywhere imports `spool_api`.
      **Second design difference from the worker tests**: `spool_api.
      queries` functions each open their *own* `common.db.get_connection()`
      call rather than accepting an injected `conn` the way every worker
      function does, so the existing rollback-based `conn` fixture's
      isolation doesn't apply to them — a new `db_conn` fixture
      (autocommit, no rollback, matching the real app's own connection
      style) is used instead, and api tests clean up their own inserted
      rows explicitly (a `make_file`/`test_root_id` factory-fixture pair
      in `tests/api/conftest.py` tracks and deletes what it creates).
      Route tests use FastAPI's `TestClient` (needs `httpx` — added to
      `requirements-dev.txt` alongside `fastapi`/`jinja2`/
      `python-multipart`, all pinned to match `services/api/
      requirements.txt`, since `spool_api.main` has to actually import
      successfully on the host). 25 new tests across `tests/api/
      test_queries.py` (pure-function + CRUD coverage) and `tests/api/
      test_routes.py` (real route round-trips) — confirmed the full
      95-test suite runs cleanly together in one session, proving the
      package collision is genuinely resolved, not just avoided by
      accident of file naming. Includes an explicit regression test for
      the `print_metadata` "None"-literal bug fixed earlier this session
      (asserts `>None<`/`None</textarea>`/`value="None"` never appear in
      a real rendered `/files/{id}` response) — exactly the class of bug
      this whole effort was meant to start catching automatically instead
      of by eyeballing screenshots.
- [x] `clean_name` applied to zip filenames too (`admin.html`'s pending-
      archives table, `admin_rejected_archives.html`) — same URL-encoding
      artifact that affected model/sidecar/project names could show up in
      a downloaded zip's own name just as easily. The raw `path` column on
      both pages deliberately stays uncleaned (the real disk path, shown
      for verification before confirm/reject/un-reject), same principle
      as the duplicate-files admin page. Added a route test asserting the
      filename cell specifically gets cleaned while the path cell doesn't
      (a plain `not in resp.text` check would have false-failed, since
      the raw path legitimately contains the same uncleaned substring).
- [x] Thumbnail caching (Phase 09) — `/thumbnails` is now served through
      `CachedStaticFiles` (`spool_api/main.py`, a `StaticFiles` subclass
      overriding `file_response` to add `Cache-Control: public,
      max-age=31536000, immutable`), so the browser stops re-requesting
      already-seen thumbnails on every page view/repeat visit. Safe only
      because the URL is now cache-busted: a thumbnail's filename is
      stable (`{file_id}.png`, overwritten in place on re-render), so
      blindly caching the plain URL would have kept serving a stale image
      after a real re-render until the browser's cache expired.
      `filters.py::thumb_url(thumbnail_path, content_hash)` appends
      `?v=<content_hash[:8]>` — a real content change always produces a
      new URL, so the long cache lifetime can never go stale. Threaded
      `content_hash` into every query that renders a thumbnail but didn't
      already select it (`search_files`, `get_project_files`,
      `list_duplicate_groups`, `_fetch_relationships`) and swapped every
      template's `/thumbnails/{{ x.thumbnail_path }}` for `{{ thumb_url(x.
      thumbnail_path, x.content_hash) }}`. Sidecar thumbnails skip the
      `?v=` entirely (`thumb_url(s.thumbnail_path)`, no second arg) —
      they have no `content_hash` column and are never re-rendered in
      place once created (`stage_sidecar`'s `ON CONFLICT (path) DO
      NOTHING` means a sidecar is only ever processed once), so there's
      nothing to bust. Deliberately **not** applied to the `/static`
      mount (CSS/JS/icons) — those change during active development
      without any equivalent versioning scheme, so caching them
      aggressively would serve stale assets after every deploy; this is
      specifically safe for thumbnails because of the cache-buster, not
      a blanket "add caching everywhere" change.
- [x] File move/rename tracking — closes the "moved file loses its tags/
      relationships" scope boundary. New `common/ingest.py::repoint_file`
      re-points an existing row's `path`/`filename`/`ext` (and
      `watched_root_id`, in case a move somehow crosses roots) to a new
      location instead of the old path going `missing` and the new path
      becoming an unrelated brand-new row — since tags/relationships/
      project membership/print_metadata are all keyed by file id, not
      path, they survive automatically. Two independent detection paths,
      since either alone misses real cases:
        - **Live watcher** (`watcher/app/main.py::on_moved`) — watchdog's
          native `FileMovedEvent` gives an explicit `(src_path, dest_path)`
          pair directly, no guessing needed: look up the tracked row for
          `src_path`, repoint it if found, otherwise fall through to
          normal new-file handling (covers a browser's `.crdownload` ->
          final-name rename, since the temp name was never tracked).
          Skipped for `relocate_to_dropfolder` roots (Downloads) — files
          there are never meant to stay tracked at their Downloads path
          anyway, so there's nothing meaningful to repoint.
        - **Rescan** (`worker/app/rescan.py::_find_move_source`) — the
          reliable fallback, since **confirmed live** that Docker
          Desktop's bind-mount fs events don't reliably deliver a move
          within this project's real setup either (moved a real test
          file on the host; the watcher never logged the move, matching
          the same already-documented bind-mount fs-event unreliability
          as other gotchas above). Rescan has no explicit src/dest
          signal at all, so it infers a move: a newly-discovered path
          with no row of its own gets its content hashed, then matched
          against still-`active` (not `missing`) rows from *this same
          root* not yet found elsewhere in *this same pass*. Deliberately
          scoped to `active` rows only — a row already `missing` from a
          *prior* rescan is presumed really gone, so re-downloading the
          exact same file elsewhere gets its own new row rather than
          resurrecting an old one on a coincidental hash match (a real
          test case: confirmed a "new copy of a deleted file" still gets
          treated as new, not a move). Verified live end-to-end:
          staged a throwaway file, moved+renamed it into a subfolder,
          confirmed the live watcher didn't catch it (per the bind-mount
          gotcha above), then ran a manual rescan and confirmed it
          reported "1 moved" and the same file id now pointed at the new
          path — no duplicate row.
- [x] Sidecar file drift tracking — closes the "a missing sidecar stays
      listed forever" scope boundary. Migration 014 adds `sidecar_files.
      status` (reusing the existing `file_status` enum — `active`/
      `missing`, same values `files` already uses). `run_rescan` now
      tracks sidecars the same shape as model files (known-by-path
      snapshot, seen-this-pass set, anything unseen goes `missing`,
      anything `missing` that reappears at the same path goes back to
      `active`) — but presence-only, no hash/re-render concept, since
      sidecars were never hashed or rendered in the first place.
      `queries.get_project_sidecars` now filters `status = 'active'`, so
      a missing sidecar just quietly stops appearing on the project page
      — matching exactly how a missing *model* file already disappears
      from the main browse grid (`search_files`'s `status = 'active'`
      filter), rather than inventing a new "review missing sidecars" UI
      pattern with no precedent even for regular files.
- [x] Admin page hides the "Duplicate files" and "Suggestions" sections
      entirely when there's nothing to review — previously both were
      always-visible static links regardless of whether anything needed
      approval, which read as "go check this" even on a fully-caught-up
      library. `/admin` now fetches counts (`len(queries.
      list_duplicate_groups())`, `list_suggested_project_assignments()`,
      `list_suggested_relationships_all()`) and each section's `{% if %}`
      gates on the relevant count(s); the link text itself grows the
      count too ("Review 4 suggested relationships →") so it's visible
      without a click. Reused the existing list functions rather than
      writing dedicated `COUNT(*)`-only queries — a personal library's
      duplicate/suggestion counts are small enough that fetching the full
      rows just to take `len()` isn't worth a second, near-duplicate
      query path.
- [x] Pending archives moved to its own page (`/admin/pending-archives`),
      same pattern as duplicates/suggestions — the admin page's "Archives"
      section now only shows a "Review N pending archives →" link
      (conditional on count, matching the other sections), while "View
      rejected archives →" stays **unconditionally** visible regardless of
      pending count, per explicit instruction — un-rejecting only makes
      sense as an always-reachable escape hatch, not something that should
      disappear once you're caught up. `confirm_zip`/`reject_zip` now
      redirect to `/admin/pending-archives` instead of `/admin`, matching
      how the duplicates/suggestions confirm/reject actions already
      redirect back to their own page rather than the main admin page.
- [x] Base link color for dark mode — a plain unstyled `<a>` (several
      admin-page links, "+ new project", etc.) previously fell back to
      the browser's own default blue/purple, which isn't tuned for the
      dark surface at all (`:visited`'s default purple especially reads
      as barely-visible there). New global `a, a:visited { color:
      var(--accent); }` — one accent color for both states, matching how
      every other accent-colored element already works; this app has no
      real "have I been here before" navigational need that would
      justify a second color. Contexts that deliberately use a different
      base link color (`.chip a`, `.card`, `.project-node a`, etc., all
      `color: var(--ink)` with accent only on hover) are unaffected —
      those class selectors already outrank the new bare `a` rule by
      specificity regardless of source order.
- [x] Double-click-to-edit for file display names and project names —
      replaces the file page's always-visible input+Save row and the
      project page's pencil-icon `<details>` reveal with a single
      `<h1 class="editable-name">` wrapping a text span and a `hidden`
      form; double-clicking the name swaps them in place. New
      `static/inline-edit.js` (event delegation on `document`, no
      per-element setup) is the **second** deliberate exception to this
      app's "no custom JS" rule, alongside the bulk select-all checkbox —
      there's no CSS-only way to detect a double-click and swap to an
      editable field. Enter submits the real POST-redirect-GET form
      (same routes/field names as before, unchanged); Escape or
      clicking/tabbing away reverts to display **without** saving —
      deliberately not save-on-blur, since an inline box that silently
      submits on a stray click risks an unintended save. Pressing Enter
      with the value unchanged from what's already displayed just
      reverts instead of submitting, both to skip a no-op round trip and
      (for file display names specifically) to avoid turning an unset
      `display_name`'s dynamic filename fallback into a frozen, explicit
      value just because the box was opened and closed — the JS compares
      the input against the *displayed* text (which the input is
      pre-filled from on open), not the raw underlying value, so this
      falls out naturally rather than needing special-casing. No visible
      icon or button — a dashed underline on hover is the only hint,
      discovered via `title="Double-click to rename"` otherwise. Verified
      live end-to-end (prefill, save, Escape-cancel, restore) against a
      real project and a real file, cleaning up the test edits after.
- [x] Printed status moved from a sidebar panel to a badge over the detail
      thumbnail — the "Printed" section (checkbox + star rating +
      comments, always visible, always taking up a whole panel) is
      replaced by a small badge in the thumbnail's top-right corner:
      grayscale + faded when not printed, full color when it is, with
      the star rating (if set) shown as a small row of ★ beneath the
      icon, and the comment surfaced via the badge's own `title`
      attribute (native browser tooltip on hover — no extra markup
      needed). Clicking the badge opens a native `<dialog>` modal
      (`.showModal()`) containing the exact same checkbox/stars/textarea
      form as before, posting to the same existing `/files/{id}/print-log`
      route — no backend changes. Icon is a real image (Flaticon, "3d
      print icons created by Magnific" — credited in the modal itself and
      in the README's new Credits section), resized to 64px via `sips`
      like the app-open icons; grayscale/color is a CSS `filter`, not a
      swapped image. A small inline `<script>` in `file_detail.html`
      (not a shared `static/*.js` file, since only this page uses it)
      wires the badge click to `showModal()`, a Cancel button to
      `.close()`, and a backdrop-click-to-close handler (native `<dialog>`
      doesn't do that on its own) — Escape-to-close is already built into
      the browser for free. This is the **third** deliberate exception to
      the "no custom JS" rule, alongside the bulk select-all checkbox and
      double-click-to-edit names.
- [x] Dimensions moved onto the thumbnail itself, bottom-left corner, on
      every page that shows one (library grid, project grid, file detail)
      — a `.dims-overlay` chip (fixed dark background + white text
      regardless of light/dark theme, since it sits on arbitrary
      thumbnail image content rather than the page's own surface) inside
      `.thumb`/`.detail-thumb` (both gained `position: relative`),
      replacing the old below-the-filename `.dims` line on grid cards and
      the "Dimensions" `<dl>` row on the file detail page. Deliberately
      scoped to *model-file* dimensions only — a sidecar card's own
      `.dims` (showing file size, not bbox measurements, a coincidentally
      reused class name for an unrelated field) was left exactly where it
      was, on `project_detail.html`'s sidecar card block specifically.
- [x] Library page: extension/tag checkboxes moved off the top bar into a
      "Filters" side panel, alongside new rating/printed/material/
      printer/slicer filters. The panel is a plain fixed-position `<div>`
      sliding in via a class toggle (`.filter-panel-open`, added/removed
      by a page-specific inline `<script>`) — deliberately **not** a
      `<dialog>`/`.showModal()` this time, since a true modal dims/blocks
      the results grid behind it, defeating the point of a side panel
      (comparing filter changes against the still-visible, still-
      interactive grid). Every input inside targets the searchbar form
      via `form="search-form"` (the same cross-DOM-location trick
      `admin.html`'s per-row edit forms already use) so it submits/live-
      updates together with the rest of the search despite not being a
      DOM descendant of that form; the existing `hx-trigger` gained
      `change from:input[type='radio']` for the new Printed radios (the
      old trigger only covered checkboxes/selects). New `queries.
      list_print_metadata_values(column)` (a hardcoded-column-name
      allowlist, same SQL-injection-safety pattern as `SORT_CLAUSES`)
      populates the Material/Printer/Slicer dropdowns with values that
      actually exist in the library — deliberately dropdowns-of-real-
      values rather than free text, since the main search bar already
      does free-text ILIKE across those same columns; a second text box
      would just be redundant. "Not printed" matches files with **no**
      `print_log` row at all, not just an explicit `printed=false` row
      (`NOT IN (SELECT file_id FROM print_log WHERE printed = true)`
      naturally covers both). The active-filter-count badge on the
      "Filters" button lives outside `#results`, so it isn't covered by
      the searchbar's htmx partial swap — a small JS function recomputes
      it directly from the panel's own current input states on every
      `change` instead of waiting on a server round trip.
      **Caught two real bugs while verifying live** (not just written
      blind): the printed-radio "is anything selected" check used
      `input[value!=""]`, which isn't valid CSS attribute-selector syntax
      (`!=` doesn't exist; fixed to `:not([value=""])`) — this silently
      threw inside the change handler and would have left the badge
      permanently stuck, caught only because the browser console was
      checked, not just the visual result. Separately, the badge showed
      a "0" instead of being hidden by default — `.filter-count-badge`'s
      own `display: inline-flex` beat the `hidden` attribute's UA-
      stylesheet `display: none` (equal specificity, author stylesheet
      wins over UA default), needing an explicit `.filter-count-badge
      [hidden] { display: none; }` override.
- [x] File detail page decluttered — rarely-needed fields (render status,
      manifold, hash, first seen) moved out of the main `<dl>` into a
      quiet `<footer class="detail-footer">` at the bottom of the page
      (muted, smaller text, separated by a top border) — the "⚠ not
      watertight" *warning badge* near the top stays put, since that's an
      actionable alert, not idle detail; only the plain Manifold status
      row moved. The "Tags" panel is gone entirely — tags now sit
      directly under the right-hand `<dl>` (no header) as plain chips
      plus a small dashed "+" circle; clicking it reveals the add-tag
      form via `<details>/<summary>` (no JS needed, matching the pattern
      used for project rename before that became double-click editing) —
      the `title="Add a tag"` on the summary is the mouse-over explainer.
- [ ] Package for sharing with friends — deferred by the user until the
      tool is feature-complete and they're happy with it; will need to
      address the hardcoded-personal-paths gotcha above (seed migration,
      `.env`) for portability to someone else's machine.

## Deliberate scope boundaries (not bugs, revisit only if they start to hurt)

- Phase 07's rescan doesn't re-run Phase 06's relationship/folder-grouping
  heuristics when a file's content changes in place, or when a file moves
  (see the rename-tracking fix in the ad hoc backlog below) — deliberate,
  same reasoning either way: re-suggesting on every in-place slicer
  re-save or every reorganization would be exactly the suggestion-noise
  that rule exists to avoid.
- Nested multi-level kits (a Downloads folder containing another folder
  that itself has model files) don't get full structure preservation on
  relocate — only the innermost leaf folders move as units, per the
  leaf-folder-only gotcha above.
