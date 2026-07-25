# SPOOL

A local, searchable library for your 3D printing files (`.stl`, `.3mf`, `.step`,
`.svg`, `.scad`, `.gcode`, `.obj`). SPOOL watches your folders, hashes and indexes every file
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
- **Real previews, not icons** — STL/3MF/OBJ are rendered via `trimesh`/`pyrender`;
  STEP is tessellated through OpenCASCADE (`cadquery-ocp`) first; SVG renders
  itself; sliced `.gcode` shows the preview image your slicer already embedded
  in it, if it wrote one; a watertightness check flags files that won't slice
  cleanly.
- **Search and browse** — search-as-you-type across filenames, tags, and
  print metadata (material, printer, slicer, your own print notes), filter by
  extension, color-coded by file type. Hyphens, underscores, and spaces are
  treated as the same thing, so searching "cake stand" finds a file
  literally named `cake_stand.stl`.
- **Tags, nestable projects, print metadata** — organize files by hand, or
  let SPOOL auto-suggest a project for files that share a folder.
- **Relationships** — link a STEP file to the STL exported from it, or a part
  to its next revision, with auto-suggested `duplicate_of` /
  `new_version_of` / `derived_from` detection based on content hash and
  filename patterns.
- **Archive review** — a `.zip`, `.7z`, or `.rar` containing a recognized
  model file gets surfaced for you to confirm or dismiss before anything is
  extracted; nothing unrelated to 3D printing is ever touched.
- **Duplicate cleanup** — files with byte-identical content are grouped for
  review, with bulk select/delete.
- **Printed tracker** — mark a file as printed, rate it, and leave yourself
  notes on how it turned out.
- **Open in your CAD/slicer app** — a native helper launches Fusion or Bambu
  Studio directly from the file's page (the one piece that isn't Docker,
  since a Linux container can't launch a macOS GUI app).

## Requirements

- A Mac (the native host-helper piece that launches Fusion/Bambu Studio is
  Mac-specific — everything else is just Docker)
- Docker Desktop (free — see step 1 below)
- Python 3.9+ on the host, only if you want to run the test suite (most
  people setting this up just to use it can skip this entirely)

## Setting up on your own machine

These steps assume you've never used Terminal or Docker before — if you
already have, skip ahead freely. Every command below is meant to be copied
and pasted exactly as written, one at a time, pressing Return after each.

### Step 0: Open Terminal

Terminal is the app you'll paste commands into. Open it with
**Spotlight**: press `Cmd + Space`, type `Terminal`, press Return. A window
with a text prompt appears — that's it, that's Terminal. Leave it open;
every command in these instructions gets typed (or pasted) there.

### Step 1: Install Docker Desktop

SPOOL runs inside Docker, which keeps everything it needs (the database,
the web server, etc.) neatly contained instead of installed loose on your
Mac.

1. Go to <https://www.docker.com/products/docker-desktop/> and download
   Docker Desktop for Mac (pick Apple Silicon or Intel — if you're not
   sure which, click the Apple logo top-left → "About This Mac" and check
   the chip listed there).
2. Open the downloaded file and drag Docker into Applications, same as
   any other Mac app.
3. Open Docker Desktop from Applications. The first launch asks for a
   few permissions — accept them. Wait until the little whale icon in
   your menu bar (top of the screen) stops animating and Docker Desktop's
   own window says it's running. **Docker Desktop needs to be open and
   running every time you use SPOOL** — if the whale icon isn't in your
   menu bar, SPOOL won't work until you open Docker Desktop again.

### Step 2: Get the SPOOL code onto your Mac

If you were sent a link to this project's GitHub page: click the green
**Code** button, then **Download ZIP**. Once it downloads, double-click the
ZIP file in your Downloads folder to unzip it, then drag the resulting
folder somewhere you'll remember (your Documents folder is a good choice).

Now tell Terminal to work inside that folder — type `cd ` (with a trailing
space), then drag the folder itself from Finder into the Terminal window
(this pastes its full path in automatically), then press Return. Your
prompt should now show the folder's name, confirming you're "in" it.

(If you're comfortable with git instead: `git clone <the repo URL>` and
`cd` into the folder it creates.)

### Step 3: Tell SPOOL which folders to watch

SPOOL needs to know three real folders on your Mac: a "drop folder" for
new downloads, your existing 3D print library, and your Downloads folder.
These are set in a file called `.env`, which doesn't exist yet — you copy
it from a template.

Paste this into Terminal and press Return:

```bash
cp .env.example .env
```

Nothing appears to happen — that's normal, it just means it worked. Now
open the new `.env` file in TextEdit by pasting this and pressing Return:

```bash
open -e .env
```

You'll see a handful of lines like `DROPFOLDER_HOST_PATH=...`. Edit the
three `_HOST_PATH` lines to real folders on your Mac — for example:

```
DROPFOLDER_HOST_PATH=/Users/yourname/Documents/3DPrintFiles
LIBRARY_HOST_PATH=/Users/yourname/Documents/3D Printing
DOWNLOADS_HOST_PATH=/Users/yourname/Downloads
```

(Tip: if a folder doesn't exist yet, create it in Finder first — Docker
needs the real folder to already be there.) Also change
`POSTGRES_PASSWORD` from the placeholder to anything else — it's just a
password for the database SPOOL keeps on your own Mac, not something you
need to remember or share. Save the file (`Cmd + S`) and close TextEdit.

### Step 4: Start SPOOL

Back in Terminal, paste this and press Return:

```bash
docker compose up -d --build
```

This downloads and builds everything SPOOL needs — the first time, it can
take several minutes (you'll see a lot of text scroll by; that's normal).
When it finishes and gives you a new prompt, check that everything started
correctly:

```bash
docker compose ps
```

You should see five services (`postgres`, `api`, `watcher`, `worker`,
`worker-step`) all saying `running` or `Up`. Then open a web browser and
go to:

```
http://localhost:8000
```

You should see SPOOL's search page. Your three folders from `.env` start
being indexed automatically in the background — if they contain a lot of
files, thumbnails will keep appearing over the next while as SPOOL works
through them, no action needed from you.

*(If you ever change a folder path in `.env` later, editing the file
alone won't update an already-running SPOOL — go to the `/admin` page in
the browser and edit the path there instead.)*

### Step 5: Install the host-helper (lets SPOOL open files in Fusion/Bambu Studio)

Everything above runs inside Docker, which — deliberately, for safety —
can't reach out and open another app on your actual Mac. One small
separate helper program handles just that piece; it's not Docker, it's a
tiny program that starts automatically in the background whenever you log
in to your Mac.

First, open `host-helper/host_helper.py` (find it in Finder, inside the
SPOOL folder, and open it with TextEdit) and look for a section called
`APP_MAP`. It's currently set up for this project's own apps (Autodesk
Fusion and Bambu Studio) — if you use different CAD or slicer software,
change the app names there to match. The name has to be the *exact* file
name of the app as it sits in your Applications folder, not its display
name — to check, paste this in Terminal:

```bash
ls ~/Applications /Applications
```

and use exactly what's printed there (e.g. some apps are named slightly
differently than you'd expect — "Autodesk Fusion.app", not
"Fusion 360.app"). Save and close the file if you changed anything, then
run:

```bash
host-helper/install.sh
```

If you ever edit `host_helper.py` or `.env` again later, re-run that same
command to pick up the change.

### Step 6: One-time permission for deleting duplicate files

Everything works right away except one specific feature: actually
deleting a file from the duplicate-files review page (opening a file in
Fusion/Bambu Studio needs no extra setup). If you try to delete a
duplicate and see "Operation not permitted," macOS is blocking it for
safety. To allow it, only once:

1. Open **System Settings**.
2. Go to **Privacy & Security → Full Disk Access**.
3. Click the **+** button, press `Cmd + Shift + G` to open the "Go to
   folder" box, type `/usr/bin`, press Return, then select `python3` and
   add it.

That's it — SPOOL is fully set up. Bookmark `http://localhost:8000` and
come back to it any time Docker Desktop is running.

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
- **Archives can't be extracted from your Library folder.** It's mounted
  read-only (an "existing library" root is never supposed to be written
  to) — confirming a zip/7z/rar found there will fail with a permissions
  error in Admin, by design. Extract it yourself, or drop it in your drop
  folder instead.
- **Don't point a watched root at a folder under iCloud Drive sync (e.g.
  anywhere inside `~/Documents` or `~/Desktop` if "Desktop & Documents
  Folders" is on) while "Optimize Mac Storage" is enabled.** iCloud will
  periodically evict local copies of files you haven't touched recently
  back to cloud-only placeholders to save disk space. Docker Desktop's
  virtualized filesystem bridge doesn't trigger iCloud's on-demand
  download for these the way native macOS file access does, so the
  watcher/worker containers just get `OSError: [Errno 35] Resource
  deadlock avoided` trying to even `stat()` the file — indefinitely, not
  a transient error. Confirmed live: an affected file shows a real size
  in `ls -la` but `stat -f "blocks=%b"` reports `0`. Reading the file
  once from the host (Terminal, Finder, anything running directly on the
  Mac, not in a container) reliably materializes it and unblocks the
  container — but iCloud can evict it again later under storage
  pressure, so this isn't a one-time fix, it can recur on a shifting set
  of files indefinitely. The real fix is either turning off "Optimize Mac
  Storage" (System Settings → your Apple ID → iCloud → iCloud Drive →
  Options) so watched files always stay downloaded locally, or keeping
  watched folders entirely outside any iCloud-synced directory.

## Status

Nine build phases done — ingestion, mesh + STEP + SVG previews, browse/search,
tags/projects/print metadata, relationships, drift reconciliation, the native
open-in-app helper, and a growing backlog of quality-of-life features (search
across print metadata, duplicate cleanup, a printed/rating tracker, and more).
296 automated tests covering the ingestion pipeline and the API. Runnable on
someone else's Mac — watched-root paths are configured via `.env`, not
hardcoded — aside from a one-line `APP_MAP` edit in `host_helper.py` for
whichever CAD/slicer apps you actually use (see setup instructions above).

## License

[GPLv3](LICENSE) — free to use, share, and modify; if you distribute a
modified version, it needs to stay open under the same license. Copyright
© 2026 Jo Wood.

## Credits

<a href="https://www.flaticon.com/free-icons/3d" title="3d icons">3d icons created by Flat-icons-com - Flaticon</a>
