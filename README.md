# SPOOL

A local, searchable library for your 3D printing files (`.stl`, `.3mf`, `.step`,
`.svg`, `.scad`). SPOOL watches your folders, hashes and indexes every file
into Postgres, renders a real preview thumbnail for each one, and serves a
searchable web page so you can find and preview a file before opening it in
Fusion or Bambu Studio — no more digging through folders full of
`bracket_v2_final_ACTUAL.stl`.

![SPOOL library view](docs/screenshot-library.png)

## What it does

- **Watches your folders** — a drop folder, your existing library, and
  Downloads (auto-relocated into the drop folder) are indexed automatically
  as files arrive, plus a periodic rescan catches anything a live filesystem
  event missed (moved, edited, or deleted files).
- **Real previews, not icons** — STL/3MF are rendered via `trimesh`/`pyrender`;
  STEP is tessellated through OpenCASCADE (`cadquery-ocp`) first; SVG renders
  itself; a watertightness check flags files that won't slice cleanly.
- **Search and browse** — search-as-you-type across filenames, tags, and
  print metadata (material, printer, slicer, your own print notes), filter by
  extension, color-coded by file type.
- **Tags, nestable projects, print metadata** — organize files by hand, or
  let SPOOL auto-suggest a project for files that share a folder.
- **Relationships** — link a STEP file to the STL exported from it, or a part
  to its next revision, with auto-suggested `duplicate_of` /
  `new_version_of` / `derived_from` detection based on content hash and
  filename patterns.
- **Zip review** — a `.zip` containing a recognized model file gets surfaced
  for you to confirm or dismiss before anything is extracted; nothing
  unrelated to 3D printing is ever touched.
- **Duplicate cleanup** — files with byte-identical content are grouped for
  review, with bulk select/delete.
- **Printed tracker** — mark a file as printed, rate it, and leave yourself
  notes on how it turned out.
- **Open in your CAD/slicer app** — a native helper launches Fusion or Bambu
  Studio directly from the file's page (the one piece that isn't Docker,
  since a Linux container can't launch a macOS GUI app).

## Requirements

- macOS (the native host-helper piece is Mac-specific — everything else is
  just Docker)
- Docker Desktop
- Python 3.9+ on the host, only if you want to run the test suite

## Setting up on your own machine

1. **Configure your folders.** Copy `.env.example` to `.env` and fill in the
   three real paths on your Mac — a drop folder for new prints, your
   existing library, and Downloads (auto-relocated into the drop folder).
   Also change `POSTGRES_PASSWORD` from the placeholder.

   ```bash
   cp .env.example .env
   ```

2. **Bring up the stack.**

   ```bash
   docker compose up -d --build        # bring up postgres, api, watcher, worker
   docker compose ps                   # check health
   curl localhost:8000/health          # confirm api <-> postgres
   ```

   Then open `http://localhost:8000`. Your three folders from `.env` are
   seeded as watched roots automatically — but only on a genuinely fresh
   `pgdata` volume (first-ever `docker compose up`). If you change the paths
   in `.env` later, edit the roots directly on the `/admin` page instead —
   re-running `docker compose up` won't re-seed an existing database.

3. **Install the host-helper** (native, not Docker — a Linux container can't
   launch a macOS GUI app, so this one piece runs directly on your Mac as a
   launchd agent):

   ```bash
   host-helper/install.sh
   ```

   It reads the same three paths from `.env`, so run this *after* step 1.
   Open `host-helper/host_helper.py` first and check `APP_MAP` — it's
   hardcoded to Autodesk Fusion + Bambu Studio (this project's own setup);
   change it to whichever CAD/slicer apps you actually use, using their real
   `.app` bundle name, not the marketing name (`ls ~/Applications /Applications`
   — e.g. Autodesk's own app is `Autodesk Fusion.app` under `~/Applications`,
   not `/Applications`, and Bambu's is `BambuStudio.app`, no space — `open -a`
   only matches the real bundle name). Re-run `install.sh` any time you edit
   `host_helper.py` or `.env`.

4. **Grant macOS permissions for the duplicate-delete feature.** "Open in
   app" works with no extra setup — it just hands off to macOS's own
   LaunchServices. Actually *deleting* a file (the duplicate-files admin
   page) needs real filesystem access, which macOS's privacy protections
   (TCC) block by default for a launchd-spawned process. If a delete fails
   with "Operation not permitted", grant Full Disk Access to
   `/usr/bin/python3` in **System Settings → Privacy & Security → Full Disk
   Access** (one-time, can't be scripted). Everything else — including
   host-helper starting up and "Open in app" — works without this.

### Day-to-day

```bash
docker compose ps                   # check health
docker compose logs worker -f       # watch backfill/render/ingest activity
docker compose logs watcher -f      # watch live filesystem events
docker compose exec postgres psql -U spool -d spool   # inspect the data directly
docker compose down                 # stop (keeps your data — pgdata + thumbnails are named volumes)
docker compose down -v              # stop AND wipe all data — only if you're OK starting over
```

Quitting/restarting Docker Desktop stops every container (not just pauses
them) — your data survives in named volumes either way, so `docker compose
up -d` brings it all back with nothing lost.

```bash
host-helper/uninstall.sh                            # stop + remove the host-helper agent
launchctl print gui/$(id -u)/com.spool.hosthelper    # confirm it's running
tail -f ~/Library/Logs/spool/host-helper.log         # watch open/delete requests
```

### Running the test suite

```bash
docker compose up -d postgres        # only postgres needs to be running
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest
```

Tests run on the host (not in a container) against a real, separate
`spool_test` database on the same Postgres instance (exposed at
`localhost:55432` for exactly this).

### Known limitations

- **Adding a *new* watched root isn't a UI action.** Docker can't attach a
  new bind mount to an already-running container, so the admin page can
  only edit/pause the three roots mounted at startup. To watch a fourth
  folder, add it to `docker-compose.yml`'s volume mounts yourself and
  `docker compose up -d --build`.
- **Changing a path in `.env` after first setup doesn't re-seed the
  database** — the seed only runs once, against a brand-new `pgdata`
  volume. Update the path on the `/admin` page instead (and re-run
  `host-helper/install.sh` if it's one of the delete-allowlist paths).
- **Zip files can't be extracted from your Library folder.** It's mounted
  read-only (an "existing library" root is never supposed to be written
  to) — confirming a zip found there will fail with a permissions error in
  Admin, by design. Extract it yourself, or drop the zip in your drop
  folder instead.

## Status

Nine build phases done — ingestion, mesh + STEP + SVG previews, browse/search,
tags/projects/print metadata, relationships, drift reconciliation, the native
open-in-app helper, and a growing backlog of quality-of-life features (search
across print metadata, duplicate cleanup, a printed/rating tracker, and more).
124 automated tests covering the ingestion pipeline and the API. Runnable on
someone else's Mac — watched-root paths are configured via `.env`, not
hardcoded — aside from a one-line `APP_MAP` edit in `host_helper.py` for
whichever CAD/slicer apps you actually use (see setup instructions above).

## License

[GPLv3](LICENSE) — free to use, share, and modify; if you distribute a
modified version, it needs to stay open under the same license. Copyright
© 2026 Jo Wood.

## Credits

<a href="https://www.flaticon.com/free-icons/3d" title="3d icons">3d icons created by Flat-icons-com - Flaticon</a>
