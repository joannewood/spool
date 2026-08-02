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
- **Open in your CAD/slicer app** — launches Fusion, Bambu Studio, or
  whatever you use directly from the file's page (macOS and Windows both
  supported).

## Requirements

- macOS or Windows (the "open in your CAD/slicer app" and "delete a
  duplicate" pieces need a small native helper program specific to each —
  everything else is just Docker, so both platforms get the exact same
  web app).
- Docker Desktop (free) — install it and keep it open. SPOOL runs inside
  Docker, so it needs to be open and running every time you use SPOOL; if
  you restart your computer and SPOOL doesn't seem to work, check that
  Docker Desktop is open first.
- Python 3 — **optional**, **Mac only**. Mac usually already has it; it's
  used to auto-detect your CAD/slicer apps during setup and to run the
  automated test suite, and SPOOL works fully without it either way — you'd
  just configure those apps by hand afterward instead. (Windows doesn't
  need Python at all — setup asks you to browse to and select each app
  directly.)

## Setting up on your own machine

Setup asks about three folders — here's what they mean, once, up front:

- **Drop folder** — SPOOL's main working folder, read-write. It's where
  you'd put a new kit you've downloaded and unzipped, or where files land
  after being auto-moved out of Downloads. **Required.**
- **Library** — your *existing*, already-organized collection of 3D print
  files, if you have one. Mounted **read-only** — SPOOL only indexes what's
  already there; it will never move, rename, or delete anything inside it.
  **Optional.**
- **Downloads** — normally your computer's actual Downloads folder. SPOOL
  watches it for new 3D-print files and **automatically moves them into
  your drop folder** the moment they finish downloading. **Optional.**

Only the drop folder is required — leaving Library and/or Downloads out
just means SPOOL won't have that feature active, nothing breaks. (Adding
one back later isn't quite as simple as flipping a setting — see "Adding
a folder you initially skipped" under Known limitations.)

**Download the installer for your OS below, run it, and follow the
prompts** — it handles everything: picking your folders, starting SPOOL,
and setting up "open in" for your CAD/slicer apps. It opens SPOOL in your
browser automatically when it's done; if that doesn't happen, go to
`http://localhost:8000` yourself (that's a special address that always
means "this same computer," so it works with Wi-Fi off and nobody outside
your machine can reach it — bookmark it once you're there).

### 🍎 Mac

1. Install [Docker Desktop for Mac](https://www.docker.com/products/docker-desktop/)
   (pick Apple Silicon or Intel — Apple menu → **About This Mac** tells you
   which chip you have if you're not sure). Open it from Applications and
   wait until the whale icon in your menu bar stops animating.
2. Go to the [**Releases** page](https://github.com/joannewood/spool/releases/latest)
   and download `SPOOL-Installer.dmg`. Double-click it to mount, then
   double-click **SPOOL Installer** inside.
3. The first time you open it, macOS shows a one-time "downloaded from
   the internet — are you sure?" confirmation — click **Open**.
   `SPOOL Installer` is signed and notarized by Apple, so that's the only
   prompt you'll see.
4. Follow the prompts — native Yes/No dialogs and Finder folder pickers,
   no typing required. It installs to `~/Applications/SPOOL`.
5. Once it's done, a **SPOOL** shortcut appears on your Desktop —
   double-click it any time to open SPOOL without retyping the address.

Skip ahead to [**Using SPOOL**](#using-spool).

### 🪟 Windows

1. Install [Docker Desktop for Windows](https://www.docker.com/products/docker-desktop/),
   open it from the Start menu, and wait until it says it's running.
2. Go to the [**Releases** page](https://github.com/joannewood/spool/releases/latest)
   and download `SPOOL-Installer.exe`, then double-click it.
3. Windows SmartScreen will show a blue "Windows protected your PC"
   warning the first time — this is expected, not a sign anything's
   wrong (the installer isn't code-signed yet, a real ongoing cost not
   yet part of this project). Click **More info**, then **Run anyway**.
   You'll only see this once.
4. Follow the installer wizard, then the guided setup that runs
   afterward — folder pickers and Yes/No dialogs, no typing required. It
   installs to `%LOCALAPPDATA%\SPOOL`. When it asks about your CAD/slicer
   apps, a file browser opens for each one — navigate to and select the
   real `.exe` (Cancel skips that app, no Python needed).
5. Once it's done, a **SPOOL** shortcut appears on your Desktop —
   double-click it any time to open SPOOL without retyping the address.

Skip ahead to [**Using SPOOL**](#using-spool).

---

**Prefer a terminal script, or want every step spelled out by hand
instead?** See [**Advanced setup: scripts and manual
installation**](#advanced-setup-scripts-and-manual-installation) at the
very bottom of this page. The vast majority of people should just use the
installer above — the advanced routes exist for troubleshooting, or if
you'd rather understand/control every step yourself.

## If SPOOL looks stopped, or something seems wrong

The fix for almost anything — Docker Desktop wasn't running, something
crashed, files stopped being picked up — is the same installer you used
for setup, not the Desktop shortcut (that shortcut just opens the SPOOL
web page, which can't do anything if SPOOL itself isn't running):

1. Find the **SPOOL Installer** file you downloaded (or wherever you
   saved it — check Downloads, or re-download it from the
   [Releases page](https://github.com/joannewood/spool/releases/latest)
   if you can't find it) and open it again.
2. Since SPOOL is already set up, it now shows a quick menu instead of
   the full setup wizard: **Restart SPOOL**, **Re-run Full Setup**, or
   **Exit**.
3. Choose **Restart SPOOL**. This brings everything back up and opens
   SPOOL in your browser once it's ready — no need to touch your folder
   settings or CAD/slicer configuration again.

Still not working? Open `/admin/status` in your browser — the small
icon in the browser tab, and the "Auto-sync" panel on that page, both
turn amber if the background scanning looks stopped. If restarting still
doesn't fix it, see [**Found a bug, or something
confusing?**](#found-a-bug-or-something-confusing) below.

## Using SPOOL

**Give it time after first setup.** SPOOL doesn't wait for you to ask —
the moment it starts, it's already walking your drop folder and library
in the background, hashing every file and rendering a thumbnail for each
one. For a library of a few hundred files that's minutes; for several
thousand, it can be a while. You don't need to do anything — just refresh
the library page occasionally, or watch progress live on `/admin/status`
(a running counter of files hashed/rendered/failed and what's currently
being worked on).

### Browsing and searching

The home page (`http://localhost:8000`) is a grid of thumbnails, newest
first. Type in the search box at the top to filter live as you type — it
searches filenames, tags, and print metadata (material, printer, slicer,
your own notes) all at once, and treats hyphens/underscores/spaces as
interchangeable, so "cake stand" finds `cake_stand.stl` too. Click
**Filters** for a side panel with extension, tag, star rating, "printed"
status, and material/printer/slicer dropdowns; the **sort** dropdown next
to search covers newest/oldest/name/size. Click any card to open that
file's own page — dimensions, whether it's watertight (manifold), tags,
project membership, any auto-extracted or manually-entered print
settings, related files, and buttons to open it directly in your CAD or
slicer app.

### Organizing: tags and projects

On a file's page, click the small **+** next to Tags or Project to add
one (or create a new project on the spot). Double-click a file's name or
a project's name to rename it in place. You don't have to organize
everything by hand, though — SPOOL watches for files that share a folder
and suggests a project for them automatically; those show up as a
lighter, dashed-outline chip with a checkmark/× to confirm or dismiss.
The same auto-suggestion happens for relationships (e.g. a `.stl`
detected as probably exported from a `.step` file with the same name).

If suggestions pile up faster than you want to review them one at a time,
`/admin` has dedicated bulk-review pages for suggested projects and
suggested relationships, each with a "confirm all" option.

### Marking what you've printed

On a file's page, click the small printer badge over the thumbnail to
open a form: a "printed" checkbox, a 1–5 star rating, and a free-text
note to yourself (how the print went, what settings you used, etc.).

### Opening a file in Fusion/Bambu Studio (or whatever you configured)

Every file's page has one icon button per app you configured during
setup, right next to its file path — click one to open that exact file
in that exact app. The app matching the file's own type (e.g. your
slicer for a `.stl`) gets a highlighted border as the obvious default,
but every configured app is always clickable for any file.

### Reviewing what SPOOL found: the Admin page

`/admin` is mission control for everything that needs a human decision:

- **Pending archives** — a `.zip`/`.7z`/`.rar` SPOOL noticed contains a
  recognized model file, waiting for you to confirm (extract it) or
  reject (ignore it forever). **Nothing is extracted automatically.**
- **Duplicate files** — groups of files with byte-identical content,
  with a bulk-select-and-delete flow.
- **Suggested projects** / **suggested relationships** — the bulk-review
  pages mentioned above.
- **Rejected archives** — anything you've dismissed, in case you change
  your mind.
- **Watched roots** — edit the label, pause, or reactivate any of your
  three configured folders.
- **Status** — the live processing dashboard mentioned above: what's
  running right now, recent successes/failures (with the full error for
  anything that failed), and per-folder file counts.

## Best practices for testers

- **This is a personal, single-user tool, not a shared service.** There's
  no login and no per-user separation — SPOOL is meant to run on *your
  own* computer against *your own* folders. If several of you are trying
  it out, each person should do their own setup on their own machine
  (their own `.env`, their own `http://localhost:8000`), not share one
  running copy over a network.
- **Confirming an archive deletes the original after extracting it.**
  Once you click Confirm on `/admin/pending-archives`, SPOOL extracts the
  contents into your drop folder and removes the original `.zip`/`.7z`/
  `.rar` — there's no undo. If you're not sure yet, click Reject instead
  (you can un-reject it later from `/admin/rejected-archives` with the
  original file untouched) rather than experimenting with Confirm on
  something you care about.
- **Deleting a duplicate is permanent** — it removes the real file from
  disk, not just the SPOOL record of it. The one exception: a duplicate
  that lives in your read-only Library folder can't be deleted this way
  at all — you'll get a clear error instead — since Library is the one
  root SPOOL guarantees it will never write to or delete from.
- **"Select all" only ever applies to what's currently on the page** on
  the bulk-review admin pages — it won't silently reach into suggestions
  you haven't scrolled to yet, but do check what's actually checked
  before clicking a bulk "accept"/"delete" button, especially if you've
  turned the page size up.
- **A big first import takes real time and CPU**, especially STEP files
  (they go through a separate, slower rendering lane specifically so they
  don't block everything else) — this is expected, not a hang. Check
  `/admin/status` before assuming something's stuck.
- See **Known limitations** below for a few sharp edges worth knowing
  about up front (cloud-synced folders, the read-only Library root, and
  what does/doesn't need a restart after a config change).

## Found a bug, or something confusing?

Please file it as a **GitHub issue** rather than just mentioning it in
passing — it's the one place that won't get lost, and lets more than one
of you comment on the same thing.

1. Go to the **Issues** tab at the top of the repo's GitHub page (or
   <https://github.com/joannewood/spool/issues> directly), then click the
   green **New issue** button.
2. Give it a short, specific title (e.g. "Setup script fails on the
   folder-picker step on Windows 11", not just "doesn't work").
3. In the description, include:
   - **What you did** (the exact steps, as best you can recall).
   - **What you expected** vs. **what actually happened**.
   - **Your OS** (macOS or Windows — and Windows version if you know it).
   - Any error text on screen, and if it's setup-related, the output of
     `docker compose ps` and `docker compose logs api` (or `logs worker`)
     pasted in — more context almost always beats less.
4. Click **Submit new issue**. That's it — no special permissions needed
   beyond having been added to the repo.

Screenshots help a lot for anything UI-related; drag an image straight
into the issue's text box on GitHub and it'll attach itself. General
feedback ("this would be more useful if...") is just as welcome as bug
reports — open an issue for those too rather than sitting on them.

## Updating SPOOL

Download the newer installer from the [**Releases**
page](https://github.com/joannewood/spool/releases/latest) and run it
again — it always installs to the same location (`~/Applications/SPOOL`
on Mac, `%LOCALAPPDATA%\SPOOL` on Windows), finds your existing `.env`
there, and offers to keep it, so nothing about your configuration is
lost.

Set up via the terminal script or fully manually instead? See "Updating
without the installer" in [**Advanced setup**](#advanced-setup-scripts-and-manual-installation)
below.

## Day-to-day operations

Run these from your SPOOL folder (`~/Applications/SPOOL` on Mac,
`%LOCALAPPDATA%\SPOOL` on Windows, if you used the installer above).

### Useful commands

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

### Working on SPOOL itself

Running the test suite, the codebase's architecture, and how to build a
release installer all live in [CONTRIBUTING.md](CONTRIBUTING.md) instead
— this section of the README is for using an already-running SPOOL, not
developing it.

## Known limitations

- **The Windows path is newer and hasn't been exercised on real Windows
  hardware** the way the macOS path has (this project was built on a
  Mac) — the app-detection logic in `configure_apps.py` was validated
  against synthetic test cases for real installer layouts (including
  Autodesk's own deeply-nested one), and `SPOOL-Installer.exe` has been
  verified to build correctly in CI, but neither has been run
  interactively on real Windows hardware yet. If `setup.ps1`, the
  installer, or the Windows host-helper hits something unexpected on
  your machine, please report it rather than assuming it's supposed to
  work that way.
- **`SPOOL-Installer.exe` isn't code-signed.** A Windows code-signing
  certificate is a real ongoing cost (unlike Apple's notarization, which
  the Mac `.dmg` uses and is covered by a $99/year developer account) and
  isn't part of this project yet — Windows SmartScreen will show a blue
  "Windows protected your PC" warning the first time you run it. Click
  **More info** → **Run anyway**; this is expected, not a sign of a
  problem, and only shows once per machine.
- **No automatic app icons on Windows yet.** macOS extracts each
  configured app's real icon from its `.icns`; Windows apps don't have an
  equivalent step wired up yet, so a Windows-configured app just shows a
  plain two-letter badge next to a file instead of its real icon —
  cosmetic only, "Open in..." still works normally.
- **Adding a folder you initially skipped, or changing an existing one,
  is now just re-running the installer** — no terminal, no manual
  database commands. Open **SPOOL Installer** again (or re-run
  `setup.sh`/`setup.ps1`), choose **Re-run Full Setup**, then **No**
  when asked to keep your existing folder configuration as-is — you'll
  be walked through the same three folder questions again (add a
  Library/Downloads you skipped the first time, change a path that
  moved, or clear one out entirely), and the install picks up the
  change on its own: your database password is preserved (it doesn't
  regenerate one that would stop working), and the underlying watched
  folder is added, updated, or turned off to match, automatically.
  - **Exception: a genuinely new *fourth* watched folder** beyond drop
    folder/Library/Downloads isn't supported this way — Docker can't
    attach a brand-new bind mount to an already-running container, so
    that specific case still needs a manual edit to `docker-compose.yml`
    (adding a new volume mount) before `docker compose up -d --build`,
    and isn't something the installer's three-folder flow covers.
  - The `/admin` page's own edit form only changes a root's **label**,
    **ingest mode**, or **active/paused** state — it was never able to
    change the underlying folder path itself; re-running the installer
    (above) is the way to actually change where a root points.
- **Nothing SPOOL does can write to or delete from your Library folder**
  — it's mounted read-only in Docker (an "existing library" root is
  never supposed to be written to), and separately, the native
  host-helper that handles real file deletion (for the duplicate-cleanup
  page) explicitly refuses any path under Library too, since that helper
  runs outside Docker and wouldn't otherwise be stopped by the read-only
  mount. Confirming an archive found in Library will fail with a
  permissions error in Admin, and deleting a duplicate that lives there
  fails with a clear error instead of silently succeeding — extract/
  delete it yourself outside SPOOL, or drop a copy in your drop folder
  instead.
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
308 automated tests covering the ingestion pipeline and the API. Runnable
on someone else's Mac or Windows machine via a signed/notarized installer
(Mac) or an installer built in CI (Windows), or the underlying guided
`./setup.sh` / `.\setup.ps1` scripts either one wraps — watched-root paths
and CAD/slicer app choices are both configured interactively rather than
hardcoded, with the fully manual, step-by-step path still available for
anyone who wants it (see Advanced setup below). The Windows path is newer
and less battle-tested than the macOS one (see Known limitations).

## License

[GPLv3](LICENSE) — free to use, share, and modify; if you distribute a
modified version, it needs to stay open under the same license. Copyright
© 2026 Jo Wood.

## Credits

<a href="https://www.flaticon.com/free-icons/3d" title="3d icons">3d icons created by Flat-icons-com - Flaticon</a>

<details>
<summary><h2>Advanced setup: scripts and manual installation</h2></summary>

**Most people should use the installer above instead** — everything here
does exactly the same thing, just with more steps you run yourself. Use
this if the installer didn't work for you, you'd rather not run an
unsigned `.exe` (Windows), or you just want to understand/control every
step.

### 🍎 Mac: guided script (`setup.sh`)

Equivalent to the Mac installer above, minus the native install wizard —
useful if you'd rather work in Terminal, or the `.dmg` didn't work for
you.

1. **Install Docker Desktop** — see step 1 of the Mac installer section
   above.
2. **Get the SPOOL code**: click the green **Code** button on this
   project's GitHub page, then **Download ZIP**. Once it downloads,
   double-click the ZIP file in your Downloads folder to unzip it, then
   drag the resulting folder somewhere you'll remember (your Documents
   folder is a good choice). (Comfortable with git instead? `git clone
   <the repo URL>` creates the folder directly.)
3. **Open Terminal**: press `Cmd + Space`, type `Terminal`, press Return.
   Type `cd ` (with a trailing space), drag the SPOOL folder from Finder
   into the Terminal window (pastes its path automatically), then press
   Return.
4. **Run the setup script**:

   ```bash
   ./setup.sh
   ```

   It asks for your **drop folder** (required), then whether you have an
   **existing library** to index and whether you want **Downloads**
   auto-managed, popping up a native Yes/No dialog and a Finder window
   for either one you say yes to (see "Setting up on your own machine"
   above for what each folder means). It generates a database password
   for you, waits for each step to finish before moving to the next, and
   tells you plainly if something didn't work. It also scans
   `~/Applications`/`/Applications` and tries to guess your CAD program
   and slicer automatically, asking you to confirm or pick from a list.

   **Safe to run more than once** — if it finds a `.env` you already set
   up, it asks whether to keep it before touching anything.

Follow the prompts it prints, and skip ahead to [**Using
SPOOL**](#using-spool) once it says you're done. If anything fails, see
**Mac: fully manual** below.

### 🍎 Mac: fully manual

Full control over every step, or a fallback if `./setup.sh` above hit a
snag — everything here uses macOS commands and apps (Terminal, Finder,
TextEdit).

#### Step 1: Tell SPOOL which folders to watch

See "Setting up on your own machine" near the top of this page for what
the drop folder, Library, and Downloads each actually do, and which are
required — here's just the mechanics of setting them.

These paths are set in a file called `.env`, which doesn't exist yet —
you copy it from a template.

Paste this into Terminal and press Return:

```bash
cp .env.example .env
```

Nothing appears to happen — that's normal, it just means it worked. Now
open the new `.env` file in TextEdit by pasting this and pressing Return:

```bash
open -e .env
```

You'll see a handful of lines like `DROPFOLDER_HOST_PATH=...`. Set
`DROPFOLDER_HOST_PATH` to a real folder on your Mac. For `LIBRARY_HOST_PATH`
and `DOWNLOADS_HOST_PATH`, either set them too, or leave them exactly as
`LIBRARY_HOST_PATH=` (nothing after the `=`) to skip that one entirely —
for example, to use a library but skip Downloads auto-move:

```
DROPFOLDER_HOST_PATH=/Users/yourname/Documents/3DPrintFiles
LIBRARY_HOST_PATH=/Users/yourname/Documents/3D Printing
DOWNLOADS_HOST_PATH=
```

(Tip: if a folder doesn't exist yet, create it in Finder first — Docker
needs the real folder to already be there.) Also change
`POSTGRES_PASSWORD` from the placeholder to anything else — it's just a
password for the database SPOOL keeps on your own Mac, not something you
need to remember or share. Save the file (`Cmd + S`) and close TextEdit.

#### Step 2: Start SPOOL

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
`worker-step`) all saying `running` or `Up`. Now open
`http://localhost:8000` in your browser — you should see SPOOL's search
page, currently empty or nearly so. Your folders from `.env` start being
indexed automatically in the background — if they contain a lot of
files, thumbnails will keep appearing over the next while as SPOOL works
through them; there's nothing else you need to click or run for that to
happen, just wait and refresh the page occasionally.

*(If you ever change a folder path in `.env` later, editing the file
alone won't update an already-running SPOOL — go to the `/admin` page in
the browser and edit the path there instead.)*

#### Step 3: Install the host-helper (lets SPOOL open files in Fusion/Bambu Studio)

Everything above runs inside Docker, which — deliberately, for safety —
can't reach out and open another app on your actual Mac. One small
separate helper program handles just that piece; it's not Docker, it's a
tiny program that starts automatically in the background whenever you log
in to your Mac.

Every Mac already comes with Python 3, so just run this and let it look
at what's installed and ask you to confirm:

```bash
python3 host-helper/configure_apps.py
```

It scans `~/Applications`/`/Applications`, guesses your CAD app and
slicer, and asks you to pick from a numbered list if it finds more than
one candidate (or if it finds none, lets you type the exact name
yourself). This is exactly what `./setup.sh` already ran for you if you
used the setup script instead of this manual guide — running it again
re-asks and overwrites the previous choice, so it's fine to change your
mind later.

Then finish by running:

```bash
host-helper/install.sh
```

If you ever change `host_helper.py`, `host_helper_client.py`, or `.env`
again later, re-run that same command (and `docker compose up -d --build
api` too, if you changed `host_helper_client.py`) to pick up the change.

#### Step 4: One-time permission for deleting duplicate files

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

### 🪟 Windows: guided script (`setup.ps1`)

Equivalent to the Windows installer above, minus the install wizard —
useful if you'd rather work in PowerShell, or don't want to run an
unsigned `.exe`.

1. **Install Docker Desktop** — see step 1 of the Windows installer
   section above.
2. **Get the SPOOL code**: click the green **Code** button on this
   project's GitHub page, then **Download ZIP**, and unzip it (or
   `git clone` if you're comfortable with git) — then open it: right-click
   the folder in File Explorer and choose **"Open in Terminal"** (or
   **PowerShell**).
3. **Run the setup script**:

   ```powershell
   .\setup.ps1
   ```

   If you see an error like *"running scripts is disabled on this
   system"*, that's PowerShell's default safety setting blocking an
   unsigned script — run this first, in the same window (it only affects
   this one window, not your whole computer), then try `.\setup.ps1`
   again:

   ```powershell
   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
   ```

   The script asks for your drop folder (required), then asks whether
   you have an existing library to index and whether you want Downloads
   auto-managed, popping up a folder picker or a Yes/No dialog for either
   one (see "Setting up on your own machine" near the top of this page
   for what these mean). It also generates a database password for you,
   starts everything, and for your CAD/slicer apps, opens a file browser
   for you to navigate to and select each real `.exe` directly (Cancel
   skips that one — no Python needed, unlike the macOS script's
   auto-detect-and-confirm approach). Right at the end it opens SPOOL for
   you automatically in your default web browser. It's safe to run this
   whole script more than once. One genuine difference from macOS:
   there's no separate permission step needed for deleting duplicate
   files — Windows' own normal file permissions already cover that.

Once it says you're done, skip up to [**Using SPOOL**](#using-spool). If
anything fails, see **Windows: fully manual** below.

### 🪟 Windows: fully manual

Full control over every step, or a fallback if `.\setup.ps1` above hit a
snag — everything here uses Windows commands and apps (PowerShell,
File Explorer, Notepad).

#### Step 1: Tell SPOOL which folders to watch

See "Setting up on your own machine" near the top of this page for what
the drop folder, Library, and Downloads each actually do, and which are
required — here's just the mechanics of setting them.

These paths are set in a file called `.env`, which doesn't exist yet —
you copy it from a template. In PowerShell (or Command Prompt), in your
SPOOL folder:

```powershell
copy .env.example .env
```

Nothing appears to happen — that's normal, it just means it worked. Now
open the new `.env` file in Notepad:

```powershell
notepad .env
```

You'll see a handful of lines like `DROPFOLDER_HOST_PATH=...`. Set
`DROPFOLDER_HOST_PATH` to a real folder on your PC — **using forward
slashes, not backslashes**, even though that looks unusual for a Windows
path (e.g. `C:/Users/you/Documents/3DPrintFiles`, not
`C:\Users\you\Documents\3DPrintFiles`; see the comment at the top of
`.env.example` for why). For `LIBRARY_HOST_PATH` and
`DOWNLOADS_HOST_PATH`, either set them too, or leave them exactly as
`LIBRARY_HOST_PATH=` (nothing after the `=`) to skip that one entirely —
for example, to use a library but skip Downloads auto-move:

```
DROPFOLDER_HOST_PATH=C:/Users/yourname/Documents/3DPrintFiles
LIBRARY_HOST_PATH=C:/Users/yourname/Documents/3D Printing
DOWNLOADS_HOST_PATH=
```

(Tip: if a folder doesn't exist yet, create it in File Explorer first —
Docker needs the real folder to already be there.) Also change
`POSTGRES_PASSWORD` from the placeholder to anything else — it's just a
password for the database SPOOL keeps on your own PC, not something you
need to remember or share. Save the file (`Ctrl + S`) and close Notepad.

#### Step 2: Start SPOOL

Back in PowerShell, paste this and press Return:

```powershell
docker compose up -d --build
```

This downloads and builds everything SPOOL needs — the first time, it
can take several minutes (you'll see a lot of text scroll by; that's
normal). When it finishes, check that everything started correctly:

```powershell
docker compose ps
```

You should see five services (`postgres`, `api`, `watcher`, `worker`,
`worker-step`) all saying `running` or `Up`. Now open
`http://localhost:8000` in your browser — you should see SPOOL's search
page, currently empty or nearly so. Your folders from `.env` start being
indexed automatically in the background — if they contain a lot of
files, thumbnails will keep appearing over the next while as SPOOL works
through them; there's nothing else you need to click or run for that to
happen, just wait and refresh the page occasionally.

*(If you ever change a folder path in `.env` later, editing the file
alone won't update an already-running SPOOL — go to the `/admin` page in
the browser and edit the path there instead.)*

#### Step 3: Install the host-helper (lets SPOOL open files in Fusion/Bambu Studio)

Everything above runs inside Docker, which — deliberately, for safety —
can't reach out and open another app on your actual PC. One small
separate helper program handles just that piece; it's not Docker, it's a
tiny program that starts automatically in the background whenever you
log in.

Easiest path (no Python needed) — a file browser opens for each app slot;
navigate to and select the real `.exe`, Cancel to skip:

```powershell
powershell -ExecutionPolicy Bypass -File host-helper\configure_apps_windows.ps1
```

This is exactly what `.\setup.ps1` already ran for you if you used the
setup script instead of this manual guide — running it again re-asks and
overwrites the previous choice, so it's fine to change your mind later.

Have Python installed and would rather it scan `Program Files` and offer
a pick-from-a-list instead of browsing to each `.exe` yourself? Both
write to the exact same files in the exact same format, so use whichever
you prefer:

```powershell
python host-helper\configure_apps.py
```

If you'd rather do it by hand instead: open `host-helper\host_helper_windows.py`
(find it in File Explorer, inside the SPOOL folder, and open it with
Notepad) and look for two sections, `APP_MAP` and `APP_PATHS` — unlike
macOS, Windows needs both, since there's no equivalent of `open -a` that
resolves an app name to a real program on its own. To find an app's real
`.exe` path: find it in the Start menu, right-click it → **More** →
**Open file location** (this reveals a shortcut in File Explorer),
then right-click *that* shortcut → **Properties** — the **Target** field
shows the real path. There's a matching `APP_MAP` (not `APP_PATHS`, that
one's Windows-only) in `services/api/spool_api/host_helper_client.py`
too — keep both in sync.

Either way, finish by running:

```powershell
powershell -ExecutionPolicy Bypass -File host-helper\install_windows.ps1
```

If you ever change `host_helper_windows.py`, `host_helper_client.py`, or
`.env` again later, re-run that same command (and `docker compose up -d
--build api` too, if you changed `host_helper_client.py`) to pick up the
change.

That's it — SPOOL is fully set up, with no extra permission step needed
(unlike macOS, Windows' own normal file permissions already cover
deleting duplicates). Bookmark `http://localhost:8000` and come back to
it any time Docker Desktop is running.

### Updating without the installer

If you set up via the ZIP/script/manual routes above (not
`SPOOL-Installer.dmg`/`.exe`), **don't just download a fresh ZIP into a
new folder** — your actual data (every file, tag, project, print log)
lives in Docker's own storage, not in the SPOOL folder itself, and a new
folder can leave that data behind without any obvious warning. The one
thing that *does* live in the SPOOL folder and matters is `.env` (your
folder paths and database password) — it's never part of any download,
so it has to survive the update in place.

**The clean way — update the same folder instead of making a new one:**

1. Download the new ZIP and extract it anywhere temporary (double-click
   it in Downloads, that's fine).
2. Select everything inside that freshly-extracted folder and drag it
   into your **existing** SPOOL folder — the same one you've been using.
   - **Mac:** Finder will ask *"An item named X already exists — Replace?"*
     — choose **Replace All** (or **Apply to All** + **Replace**).
   - **Windows:** File Explorer will ask to confirm overwriting — choose
     **Replace the files in the destination**.
3. `.env` was never part of the ZIP, so this leaves it completely
   untouched — your paths and password come along automatically.
4. Delete the now-empty temporary extracted folder, then re-run
   `./setup.sh` / `.\setup.ps1` (or just `docker compose up -d --build`)
   from your real SPOOL folder.

(If you set this up with `git clone` instead of a ZIP: `git pull` in
that same folder does the same thing, even more simply.)

**If you (or a fellow tester) do end up extracting a fresh copy into a
new folder anyway** — running the setup script there is designed to
catch this rather than fail silently or confusingly: it checks for an
existing SPOOL database before writing a new `.env`, and if it finds
one sitting there unmatched, it stops and tells you exactly what
happened, offering two options — go find your old `.env` and use the
steps above instead (safe, nothing is touched), or confirm permanently
erasing that old data and starting completely fresh. It never silently
guesses on your behalf either way.

</details>
