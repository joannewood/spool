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
- [ ] Phase 08 — host-helper (native launchd agent, open-in-Fusion360/Bambu) ← **next**
- [ ] Phase 09 — polish & scale

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
            panel. Shares `common/` (build context is ./services) — uses
            common.db for queries, all in queries.py.
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
            suggest_folder_project groups files that share an immediate
            parent directory (skipped if that directory *is* the watched
            root) into a flat, auto-created-if-missing top-level project
            named after the folder — deliberately not mirroring the whole
            directory tree, per spec. All suggestions insert with
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
            `_ingest_new_path`/`_walk_matching` rather than duplicating
            "how a brand-new file gets indexed." Gated on the same
            `RUN_BACKFILL` flag as backfill (only the fast `worker` lane
            runs it, not `worker-step` — otherwise both lanes would
            double-hash and race on the same rows) and checked once per
            iteration of the existing job-poll loop, no separate
            thread/scheduler. Also has bambu_metadata.py —
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
```

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
  Phase 03).
- **Folder-based project auto-grouping matches by folder *name* only**
  (`suggest_folder_project` in `relationship_suggest.py`) — projects have no
  folder-path column in the schema, so two same-named leaf folders in
  unrelated parts of the library (e.g. two different `misc/` dumps) merge
  into one suggested project. Acceptable for a personal library; would need
  a schema change (a path or per-root scoping column on `projects`) to fix
  properly. Since membership is inserted as `status='suggested'`, a wrong
  auto-grouping is just one reject click away, not a destructive merge.
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
  - Library: `~/Documents/3D Printing` — **PLACEHOLDER**, doesn't point at
    your real existing library yet. Update the seed migration (and re-apply
    by hand per the migrations gotcha above) once you know the real path.
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

**To verify a UI change**, use the `run-spool` skill
(`.claude/skills/run-spool/SKILL.md`) rather than re-deriving the
no-browser-tooling workaround — `driver.sh <script.mjs>` runs a Playwright
script against `http://api:8000` in a throwaway container on the Compose
network. See `example-flow.mjs` in that directory for the pattern.

## Next: Phase 08 — host-helper

A small native (non-Docker) helper running on the Mac host, since a
container can't launch a macOS GUI app. Needs to: expose some local
mechanism the `api` container can reach (a tiny HTTP listener on the host,
or a launchd agent watching a drop file/queue table) that takes a
`files.path` (already the real host path, per the host_path-vs-
container_path gotcha) and opens it in Fusion360 or Bambu Studio via `open
-a`. The file detail page already has the "Opening directly in Fusion360 /
Bambu Studio arrives in a later phase" placeholder note and the real host
path displayed — Phase 08 replaces that note with a working "Open in..."
button. Since `api` runs inside Docker and has no route to the host GUI
session, this is the one piece of SPOOL that can't just be another Compose
service — worth deciding the host↔container communication mechanism first
(simplest: `api` writes a row to a small `open_requests` table, the host
helper polls it, similar in spirit to the existing `jobs` table pattern).

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
