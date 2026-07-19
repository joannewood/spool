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
   `.app` bundle name (`ls ~/Applications /Applications`), then run
   `install.sh`. Re-run it any time you edit `host_helper.py` or `.env`.

See [`CLAUDE.md`](CLAUDE.md) for full architecture notes, every non-obvious
decision made along the way, and the running list of what's built vs. still
planned.

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

<a href="https://www.flaticon.com/free-icons/3d-print" title="3d print icons">3d print icons created by Magnific - Flaticon</a>
