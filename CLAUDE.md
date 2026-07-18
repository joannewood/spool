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
<path>`. `services/api/app/host_helper_client.py` mirrors the ext→app
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
- **Folder-based project auto-grouping matches by folder *name* only**
  (`suggest_folder_project` in `relationship_suggest.py`) — projects have no
  folder-path column in the schema, so two same-named leaf folders in
  unrelated parts of the library (e.g. two different `misc/` dumps) merge
  into one suggested project. Acceptable for a personal library; would need
  a schema change (a path or per-root scoping column on `projects`) to fix
  properly. Since membership is inserted as `status='suggested'`, a wrong
  auto-grouping is just one reject click away, not a destructive merge.
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

**To verify a UI change**, use the `run-spool` skill
(`.claude/skills/run-spool/SKILL.md`) rather than re-deriving the
no-browser-tooling workaround — `driver.sh <script.mjs>` runs a Playwright
script against `http://api:8000` in a throwaway container on the Compose
network. See `example-flow.mjs` in that directory for the pattern.

## Next: Phase 09 — polish & scale

Search relevance, thumbnail cache tuning, and a performance pass for a
genuinely large library — per the original spec's closing phase. Paused
(at the user's request) while the real library gets populated — it's
actively filling in now (hundreds of real files under `Library` already,
well past the old placeholder-path state), so there's finally real scale
to work against once this resumes.

While populating the library, three ingestion-pipeline gaps surfaced
outside the Phase 09 pause (not part of it, just concurrent unplanned
work): the folder-grouping threshold, sidecar-file indexing, and
zip review/extraction — all described in the worker/ section above and
their own gotchas below. Resume Phase 09 proper whenever ready.

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
- [ ] Test coverage for major components — deliberately last, once the
      surface area above has settled.
- [ ] Package for sharing with friends — deferred by the user until the
      tool is feature-complete and they're happy with it; will need to
      address the hardcoded-personal-paths gotcha above (seed migration,
      `.env`) for portability to someone else's machine.

## Deliberate scope boundaries (not bugs, revisit only if they start to hurt)

- Phase 06's folder-grouping heuristic matches by folder *name* only, not
  full path (see gotcha above) — same-named leaf folders in different
  places merge into one suggested project.
- Phase 07's rescan doesn't re-run Phase 06's relationship/folder-grouping
  heuristics when a file's content changes in place, and doesn't handle a
  file *moved* to a new path as a rename — a move looks like the old path
  going missing and the new path being a brand-new file (losing tags/
  relationships on the "new" row). True rename-tracking would need the
  live watcher's `on_moved` event wired up (evaluated during Phase 07
  planning, deliberately deferred — periodic rescan was judged sufficient
  for now since Docker Desktop bind-mount fs events are already known to be
  unreliable, per the gotcha above).
- `sidecar_files` has no `status`/drift-tracking column — a sidecar whose
  file disappears just stays listed forever (no `missing` state like
  `files` gets from Phase 07). Low-value to fix until it's actually
  annoying in practice.
- Nested multi-level kits (a Downloads folder containing another folder
  that itself has model files) don't get full structure preservation on
  relocate — only the innermost leaf folders move as units, per the
  leaf-folder-only gotcha above.
