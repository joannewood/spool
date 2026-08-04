# SPOOL

A local, searchable library for your 3D printing files (`.stl`, `.3mf`, `.step`,
`.svg`, `.scad`, `.gcode`, `.obj`). SPOOL watches your folders, hashes and indexes every file
into Postgres, renders a real preview thumbnail for each one, and serves a
searchable web page so you can find and preview a file before opening it in
Fusion or Bambu Studio — no more digging through folders full of
`bracket_v2_final_ACTUAL.stl`.

![SPOOL library view](docs/screenshot-library.png)

> **Looking for the native Mac app?** [spool-swift](https://github.com/joannewood/spool-swift)
> is a from-scratch native macOS rewrite — same idea, no Docker/Postgres, a single
> ordinary Mac app instead. Both are actively maintained.

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
one back later isn't quite as simple as flipping a setting — see
"Changing which folders SPOOL watches" under Known limitations.)

**Download the installer for your OS below, run it, and follow the
prompts** — it handles everything: picking your folders, starting SPOOL,
and setting up "open in" for your CAD/slicer apps. It opens SPOOL
automatically when it's done (in its own window, via the same app as the
Desktop shortcut below); if that doesn't happen, go to
`http://localhost:8000` yourself in a browser (that's a special address
that always means "this same computer," so it works with Wi-Fi off and
nobody outside your machine can reach it — bookmark it once you're there).

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
   double-click it any time to open SPOOL in its own window (not a
   browser tab), complete with a menu-bar icon (Open SPOOL, Restart
   SPOOL, Start at Login, Quit) for quickly getting back to it or
   restarting it if something looks stuck.

Skip ahead to [**Using SPOOL**](#using-spool).

### 🪟 Windows

1. Install [Docker Desktop for Windows](https://www.docker.com/products/docker-desktop/),
   open it from the Start menu, and wait until it says it's running.
   **If Docker Desktop won't start** (an error mentioning virtualization,
   WSL 2, or "Hardware assisted virtualization and data execution
   protection must be enabled in the BIOS") — this means your PC's
   virtualization setting is turned off at the hardware level, which
   Docker needs and Windows can't turn on for you. Restart your PC, enter
   its BIOS/UEFI setup (usually a key like `F2`, `F10`, `Del`, or `Esc`
   pressed right at power-on — check your PC's manual/manufacturer if
   none of those work), and enable the setting usually called
   **Intel VT-x**, **AMD-V**, or **SVM Mode** (exact name and location
   varies by manufacturer). Save and reboot, then Docker Desktop should
   start normally.
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
   double-click it any time to open SPOOL in its own window (not a
   browser tab), complete with a system tray icon (Open SPOOL, Restart
   SPOOL, Start at Login, Quit) for quickly getting back to it or
   restarting it if something looks stuck.

Skip ahead to [**Using SPOOL**](#using-spool).

---

**Prefer a terminal script, or want every step spelled out by hand
instead?** See [**Advanced setup: scripts and manual
installation**](#advanced-setup-scripts-and-manual-installation) at the
very bottom of this page. The vast majority of people should just use the
installer above — the advanced routes exist for troubleshooting, or if
you'd rather understand/control every step yourself.

## If SPOOL looks stopped, or something seems wrong

**Try the Desktop shortcut first.** Since it now opens the real SPOOL
app (not just a browser tab), double-clicking it — or picking **Restart
SPOOL** from its menu-bar/system-tray icon if it's already open — brings
Docker Desktop up if it wasn't running, then brings SPOOL's own
containers back up, no typing or extra steps needed. This fixes most
things: Docker Desktop wasn't running, something crashed, files stopped
being picked up.

**If that doesn't help**, or you're on an install from before this
existed (the shortcut just opens `http://localhost:8000` in your browser
in that case, which can't do anything if SPOOL itself isn't running),
fall back to the installer:

1. Find the **SPOOL Installer** file you downloaded (re-download it from
   the [Releases page](https://github.com/joannewood/spool/releases/latest)
   if you can't find it) and open it again.
2. Since SPOOL is already set up, it now shows a quick menu instead of
   the full setup wizard: **Restart SPOOL**, **Re-run Full Setup**, or
   **Exit**.
3. Choose **Restart SPOOL**. This brings everything back up and opens
   SPOOL in your browser once it's ready — no need to touch your folder
   settings or CAD/slicer configuration again. It also replaces an old
   browser-only Desktop shortcut with the new app-based one, so this
   only needs doing once.

Still not working? Open <http://localhost:8000/admin/status> in your
browser — the small icon in the browser tab, and the "Auto-sync" panel
on that page, both turn amber if the background scanning looks stopped.
If restarting still doesn't fix it, see [**Found a bug, or something
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
searches filenames, tags, project names, and print metadata (material,
printer, slicer, your own notes) all at once, and treats hyphens/
underscores/spaces as interchangeable, so "cake stand" finds
`cake_stand.stl` too. Click
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

The **Projects** tab has its own searchable list/cards view of every
project. From a project's own page you can rename it, merge it into
another project, or move it under a different parent project. If a lot
of your projects ended up with messy auto-generated names, `/projects/
bulk-rename` suggests cleaned-up names for all of them at once, either
one at a time or all together.

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
  reject (ignore it forever). **Nothing is extracted automatically** —
  unless you turn on the **"Automatically extract every new relevant
  archive"** option at the top of this page, which skips the review
  step entirely for anything found from that point on (archives already
  waiting when you turn it on still need a decision).
- **Duplicate files** — groups of files with byte-identical content,
  with a bulk-select-and-delete flow.
- **Suggested projects** / **suggested relationships** — the bulk-review
  pages mentioned above.
- **Rejected archives** — anything you've dismissed, in case you change
  your mind.
- **Watched roots** — edit the label, pause, or reactivate any of your
  three configured folders. Each one's **Kind** (drop folder / library /
  downloads) reflects its fixed role, and **Ingest mode** is only ever
  editable for a library-kind root — the drop folder and Downloads each
  have exactly one mode that makes sense for what they do, so those two
  are shown locked.

The top of `/admin` also shows an at-a-glance summary — auto-sync health
and what's currently processing. For the full picture (recent successes/
failures with the full error for anything that failed, per-folder file
counts, and auto-sync settings), see the **Status** page, its own tab in
the nav.

## Best practices for testers

- **This is a personal, single-user tool, not a shared service.** There's
  no login and no per-user separation — SPOOL is meant to run on *your
  own* computer against *your own* folders.
- **Confirming an archive deletes the original after extracting it.**
  Once you click Confirm on `/admin/pending-archives`, SPOOL extracts the
  contents into your drop folder and removes the original `.zip`/`.7z`/
  `.rar` — there's no undo. If you're not sure yet, click Reject instead
  (you can un-reject it later from `/admin/rejected-archives` with the
  original file untouched) rather than experimenting with Confirm on
  something you care about.
- **Deleting a duplicate is permanent** — it removes the real file from
  disk, not just the SPOOL record of it. The one exception: a copy that
  lives in your read-only Library folder can't be deleted this way at
  all — its checkbox is locked (with an explanation on hover) rather than
  letting you try and fail, since Library is the one root SPOOL
  guarantees it will never write to or delete from. If every copy in a
  duplicate group lives in Library, none of them can be deleted from
  SPOOL — you'd need to remove one yourself in Finder/File Explorer.
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

## Working on SPOOL itself

Running the test suite, the codebase's architecture, and how to build a
release installer all live in [CONTRIBUTING.md](CONTRIBUTING.md) instead
— this README is for using an already-running SPOOL, not developing it.

## Known limitations

- **Windows support is newer than Mac support.** This project was built
  on a Mac, and while the Windows installer/scripts have been tested as
  thoroughly as possible without one, they haven't yet been run on a
  real Windows machine. If something looks or behaves oddly on Windows,
  please [report it](#found-a-bug-or-something-confusing) rather than
  assuming it's supposed to work that way.
- **Windows will show a security warning the first time you run the
  installer** — a blue "Windows protected your PC" screen. This is
  expected, not a sign anything's wrong: click **More info** → **Run
  anyway**. It only appears the first time.
- **App icons on Windows are a plain placeholder for now**, not the
  real app's icon — purely cosmetic, "Open in..." still opens the right
  app either way.
- **The SPOOL desktop app's Windows build is unsigned**, same documented
  tradeoff as the installer itself. It's launched by an already-approved
  installer rather than downloaded directly, so it shouldn't trigger its
  own separate SmartScreen warning — but this hasn't been confirmed on
  real Windows hardware, so please [report it](#found-a-bug-or-something-confusing)
  if it does. The menu-bar/system-tray icon is also a fixed, static icon
  for now — it doesn't yet change color to reflect sync status the way
  `/admin/status`'s own icon does.
- **Changing which folders SPOOL watches (adding one you skipped, or
  pointing it somewhere new)**: just re-run the installer and choose to
  update your setup — no terminal or technical steps needed. The one
  thing that isn't supported this way is going *beyond* the three
  folders the setup flow asks about (drop folder, Library, Downloads);
  if you need a fourth watched folder, see
  [CONTRIBUTING.md](CONTRIBUTING.md).
- **Your Library folder is read-only, on purpose.** SPOOL will index and
  preview everything in it, but will never move, delete, or extract
  anything there — that's deliberate, so it's never at risk of touching
  your existing organization. If you want to extract an archive or
  delete a duplicate that lives in Library, do it yourself outside
  SPOOL, or work from a copy in your drop folder instead.
- **Avoid watching a folder that's also synced by iCloud Drive** (for
  example `~/Documents` or `~/Desktop`, if "Desktop & Documents Folders"
  is turned on) while "Optimize Mac Storage" is enabled. iCloud can
  offload files you haven't opened in a while to save disk space, and
  SPOOL can get stuck waiting on one of those until it's downloaded
  again. Either turn off "Optimize Mac Storage" (System Settings → your
  Apple ID → iCloud → iCloud Drive → Options) so watched files always
  stay fully downloaded, or just keep watched folders outside iCloud
  entirely.
- **A handful of files will never get a thumbnail, and that's expected.**
  A file that fails to render still shows up everywhere else — you can
  still search for it, tag it, add it to a project, and open it in
  Fusion/Bambu Studio — it just shows a small note instead of a preview
  image. This mostly happens for a few known reasons: the file is
  unusually large or has an unusually complex internal structure (some
  very detailed 3MF exports fall into this — SPOOL deliberately skips
  trying to render these rather than risk running out of memory), or the
  file uses a structure a format's preview support doesn't handle yet
  (a small number of 3MF files hit exactly this). None of these mean the
  file itself is broken or corrupted — only its preview image. Hovering
  over the note on a file's page shows the specific reason.

(The technical reasons behind each of these — error messages, code
paths, what was actually tested — are in
[CONTRIBUTING.md](CONTRIBUTING.md#known-technical-limitations) for
anyone digging into the code.)

## License

[GPLv3](LICENSE) — free to use, share, and modify; if you distribute a
modified version, it needs to stay open under the same license. Copyright
© 2026 Jo Wood.

## Credits

<a href="https://www.flaticon.com/free-icons/3d" title="3d icons">3d icons created by Flat-icons-com - Flaticon</a>

<details>
<summary><h2>Advanced setup: scripts and manual installation</h2></summary>

**Most people should use the installer above instead** — everything here
sets up the same SPOOL, just with more steps you run yourself, and
without the installer's bundled native desktop app (no Dock/taskbar
window, no menu-bar/tray icon — SPOOL still runs exactly the same, you'd
just bookmark `http://localhost:8000` in your browser instead). Use this
if the installer didn't work for you, you'd rather not run an unsigned
`.exe` (Windows), or you just want to understand/control every step.

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
docker compose up -d
```

This downloads everything SPOOL needs — the first time, it's a few GB and
can take several minutes (you'll see a lot of text scroll by; that's
normal).
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
docker compose up -d
```

This downloads everything SPOOL needs — the first time, it's a few GB and
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
   `./setup.sh` / `.\setup.ps1` (or just `docker compose up -d`, which
   pulls the latest pre-built images) from your real SPOOL folder.

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
