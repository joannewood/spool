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
- [ ] Phase 04 — browse & search UI ← **next**
- [ ] Phase 05 — tags, projects, print metadata, admin page (watched roots CRUD)
- [ ] Phase 06 — relationships (manual + auto-suggest: filename/version, folder grouping)
- [ ] Phase 07 — drift reconciliation (periodic rescan, hash rematching)
- [ ] Phase 08 — host-helper (native launchd agent, open-in-Fusion360/Bambu)
- [ ] Phase 09 — polish & scale

The stack (postgres, api, watcher, worker) runs continuously — it's not a
one-shot build, it's meant to be up and watching folders in the background.

## Architecture

```
services/
  common/   shared lib used by watcher + worker — db, host<->container path
            mapping, hashing, ingest primitives (stage/relocate/enqueue)
  api/      FastAPI. Currently just /health. Gets real endpoints in Phase 04+.
  watcher/  live filesystem events via watchdog. Lightweight — stages a stub
            file row + queues an 'ingest' job, or relocates (Downloads), then
            gets out of the way.
  worker/   heavy image (trimesh/pyrender/OCP). Runs a one-shot backfill walk
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
- **Testing note**: any file written into the real bind-mounted watched
  folders (even via a throwaway `docker compose run` script) gets picked up
  by the live watcher/backfill for real, since they're the actual host
  folders — not a bug, just remember to clean up test artifacts from both
  disk AND the `files`/`jobs` tables afterward (happened twice while building
  Phase 03).
- **Applying a migration to a live (non-empty) DB**: confirmed working —
  `docker compose exec postgres psql -U spool -d spool -f /docker-entrypoint-initdb.d/00N_whatever.sql`
  (the migrations folder is bind-mounted into the postgres container at that
  path already, so the file's already there — no need to copy it in).
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

## Next: Phase 04 — browse & search UI

First real `api` endpoints beyond `/health`: a searchable/filterable grid of
thumbnails, per the spec ("the first genuinely useful version of SPOOL").
Needs `api` to actually query `files`/`watched_roots`/etc — will want to
mount the `thumbnails` volume into `api` (read-only) for the first time,
per the docker-compose plan in the spec (Sheet 07 said `api` gets `thumbnails
(ro)` — not wired up yet, only `worker`/`worker-step` have it). FastAPI +
Jinja2 + htmx per the spec's tech-stack decision, no separate JS build step.
