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
- **Open in your CAD/slicer app** — a small native helper (macOS and
  Windows both supported) launches Fusion, Bambu Studio, or whatever you
  use directly from the file's page — the one piece that isn't Docker,
  since a Linux container can't launch a GUI app on your actual machine.

## Requirements

- macOS or Windows (the "open in your CAD/slicer app" and "delete a
  duplicate" pieces need a small native helper program specific to each —
  everything else is just Docker, so both platforms get the exact same
  web app)
- Docker Desktop (free — see step 1 below). **Install and open this
  before running the setup script** — the script checks for it and will
  stop and point you to the download page if it's missing, so it's
  smoother to just get it out of the way first. SPOOL runs inside
  Docker, which keeps everything it needs (the database, the web
  server, etc.) neatly contained instead of installed loose on your
  computer — this is why every setup guide below starts by installing
  it. **It needs to be open and running every time you use SPOOL** — if
  you restart your computer and SPOOL doesn't seem to be working, check
  that Docker Desktop is open first before anything else.
- Python 3 — **optional**. (macOS usually already has this; Windows
  needs a separate install — see the Windows section below, itself an
  optional step there.) Used by the setup script to auto-detect your
  CAD/slicer apps, and separately to run the automated test suite.
  Neither of those is required to actually use SPOOL day to day — if
  Python isn't there, setup just skips the app auto-detection step with
  a note, and you can configure that part by hand later (or skip the
  test suite entirely, most people setting this up just to use it never
  need it).

Setup below is split into four self-contained guides (a quick script and
a full manual walkthrough for each OS) — expand whichever one matches
you. (The Windows path is newer and has seen less real-world use than
the macOS one — if something looks off, the "Known limitations" section
has a couple of Windows-specific notes.)

## Setting up on your own machine

Every path below (script or manual, Mac or Windows) ends up asking about
the same three folders, so here's what they mean, once, up front:

- **Drop folder** — SPOOL's main working folder. It's read-write, and
  it's where you'd put a new kit you've downloaded and unzipped, or
  where files land after being auto-moved out of Downloads (see below).
  **This one's required** — it's the folder SPOOL is built around, and
  the only one it can't run without.
- **Library** — your *existing*, already-organized collection of 3D
  print files, if you have one (e.g. years of files sitting in a folder
  from before you had SPOOL). It's mounted **read-only** — SPOOL only
  looks at what's already there to index and search it; it will never
  move, rename, or delete anything inside it. **Optional** — if you
  don't have an existing library, just leave this one out and SPOOL will
  only watch your drop folder.
- **Downloads** — normally your computer's actual Downloads folder.
  SPOOL watches it specifically for new 3D-print files and
  **automatically moves them into your drop folder** the moment they
  finish downloading, so Downloads doesn't just become another pile of
  clutter. **Optional** — leave it out if you'd rather manage Downloads
  yourself and just drop files into your drop folder directly.

**Only the drop folder is required.** Leaving Library and/or Downloads
out means SPOOL simply won't have that feature active — nothing breaks,
there's just one less (or two less) folder(s) being watched. One thing
worth knowing if you skip one now and want it later: adding it isn't as
simple as updating a setting and restarting (the same is true of adding
any watched folder after first setup) — see "Adding a folder you
initially skipped" under Known limitations for the extra step involved.

**Starting SPOOL and opening it**: every guide below ends the same way —
building and starting everything (`docker compose up -d --build`, either
run for you by a setup script or typed by hand), which takes several
minutes the first time you ever do it (a lot of text scrolls by; that's
normal) and is much faster every time after. The setup scripts then open
SPOOL for you automatically in your default browser. If you're setting
up by hand instead, or the automatic open doesn't happen, open any
browser (Safari, Chrome, Firefox, Edge — whatever you normally use) and
go to `http://localhost:8000` yourself — this isn't a real website out
on the internet, "localhost" is a special address that always means
"the thing running on this same computer," so it works fine even with
Wi-Fi off and nobody outside your own computer can reach it. Once it's
loaded, bookmark it (the star icon in the address bar) so you can get
back without retyping the address — you'll come back to this same one
every time you use SPOOL.

Four self-contained setup guides follow — expand whichever matches you.
Each one gets you all the way to a running SPOOL; there's no need to
read the others first (or at all).

<details>
<summary><h2>🍎 Mac setup</h2></summary>

These steps assume you've never used Terminal or Docker before — if you
already have, skip ahead freely. The recommended path below (Steps 1-2)
never needs Terminal at all; it's only the alternate Terminal-based
script and the Manual setup guide further down that use it.

### Step 1: Install Docker Desktop

1. Go to <https://www.docker.com/products/docker-desktop/> and download
   Docker Desktop for Mac (pick Apple Silicon or Intel — if you're not
   sure which, click the Apple logo top-left → "About This Mac" and check
   the chip listed there).
2. Open the downloaded file and drag Docker into Applications, same as
   any other Mac app.
3. Open Docker Desktop from Applications. The first launch asks for a
   few permissions — accept them. Wait until the little whale icon in
   your menu bar (top of the screen) stops animating and Docker Desktop's
   own window says it's running.

### Step 2: Download and run the SPOOL Installer (recommended)

This is the easiest path — no Terminal, no typing commands.

1. Go to this project's GitHub **Releases** page and download
   `SPOOL-Installer.dmg` (the latest release).
2. Double-click the downloaded file to mount it, then double-click
   **SPOOL Installer** inside the window that opens.
3. The first time you open it, macOS shows a one-time "'SPOOL Installer'
   was downloaded from the internet — are you sure you want to open it?"
   confirmation — click **Open**. SPOOL Installer is signed and
   notarized by Apple, so that's the only prompt you'll see; you won't
   hit the scarier "can't be opened because the developer cannot be
   verified" block some downloaded apps trigger.
4. A window opens and walks you through the same folder questions
   described above, using native Yes/No dialogs and Finder folder
   pickers instead of typed answers — just read each one and click a
   button. It installs SPOOL to `~/Applications/SPOOL`, starts it, sets
   up "open in" for your CAD/slicer apps, and opens SPOOL in your
   browser when it's done.

**Safe to run again later** — download and re-run a newer
`SPOOL-Installer.dmg` any time to update; it finds your existing
`.env` and offers to keep it, so re-running never undoes your
configuration.

Skip ahead to [**Using SPOOL**](#using-spool) once it says you're done.

Prefer working in Terminal yourself, or don't see a release download
yet? Read on for the Terminal-based script instead, or see **Manual
setup (Mac)** below to control every step by hand.

<details>
<summary>Terminal-based script instead (equivalent to the installer above)</summary>

#### Get the SPOOL code onto your Mac

If you were sent a link to this project's GitHub page: click the green
**Code** button, then **Download ZIP**. Once it downloads, double-click the
ZIP file in your Downloads folder to unzip it, then drag the resulting
folder somewhere you'll remember (your Documents folder is a good choice).

(If you're comfortable with git instead: `git clone <the repo URL>`
creates the folder directly — skip ahead either way.)

#### Open Terminal

Terminal is the app you'll paste commands into for the rest of this.
Open it with **Spotlight**: press `Cmd + Space`, type `Terminal`, press
Return. A window with a text prompt appears — that's it, that's
Terminal. Leave it open; every command from here on gets typed (or
pasted) there.

Now tell it to work inside the SPOOL folder you just downloaded — type
`cd ` (with a trailing space), then drag that folder itself from Finder
into the Terminal window (this pastes its full path in automatically),
then press Return. Your prompt should now show the folder's name,
confirming you're "in" it.

#### Run the setup script

The rest of setup — telling SPOOL which folders to watch, starting it,
and wiring up "open in" for your CAD/slicer apps — is one script:

```bash
./setup.sh
```

It asks for your **drop folder** (required — your main working folder,
the one that actually needs real files in it), then asks whether you
have an **existing library** to index too and whether you want
**Downloads** auto-managed, popping up a native Yes/No dialog and a
Finder window for either one you say yes to and leaving it out of your
setup entirely if you say no (see the folder explanations above for
what each one means). Rather than making you hand-edit a config file,
it generates a database password for you so there's nothing to
remember, waits for each step to actually finish before moving to the
next, and tells you plainly if something didn't work. It also looks at
what's in your `~/Applications`/`/Applications` folder and tries to
guess your CAD program and slicer automatically, asking you to confirm
or pick from a list rather than requiring you to know the exact `.app`
file name up front.

**It's completely safe to run more than once** — if it finds a `.env` you
already set up, it asks whether to keep it before touching anything, so
re-running it later (say, after downloading an updated copy of SPOOL) to
pick up changes won't undo your configuration.

Follow the prompts it prints, and skip ahead to
[**Using SPOOL**](#using-spool) once it says you're done. If anything
about it fails, or you'd rather understand/control every step yourself,
the **Manual setup (Mac)** guide below does exactly the same thing by
hand.

</details>

</details>

<details>
<summary><h2>🛠️ Manual setup (Mac)</h2></summary>

Full control over every step, or a fallback if `./setup.sh` above hit a
snag — everything here uses macOS commands and apps (Terminal, Finder,
TextEdit). On Windows? See **Manual setup (Windows)** further down
instead.

### Step 1: Tell SPOOL which folders to watch

See "Setting up on your own machine" above for what the drop folder,
Library, and Downloads each actually do, and which are required —
here's just the mechanics of setting them.

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

### Step 2: Start SPOOL

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
`http://localhost:8000` in your browser (see "Starting SPOOL and opening
it" above if you skipped straight here) — you should see SPOOL's search
page, currently empty or nearly so. Your folders from `.env` start being
indexed automatically in the background — if they contain a lot of
files, thumbnails will keep appearing over the next while as SPOOL works
through them; there's nothing else you need to click or run for that to
happen, just wait and refresh the page occasionally.

*(If you ever change a folder path in `.env` later, editing the file
alone won't update an already-running SPOOL — go to the `/admin` page in
the browser and edit the path there instead.)*

### Step 3: Install the host-helper (lets SPOOL open files in Fusion/Bambu Studio)

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

### Step 4: One-time permission for deleting duplicate files

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

</details>

<details>
<summary><h2>🪟 Windows setup</h2></summary>

The underlying app (Docker, Postgres, the web page) is identical to the
Mac version above — the only thing that's genuinely different per OS is
the small native helper that lets SPOOL open a file in Fusion/Bambu
Studio and delete duplicates, since that needs real access to your
actual machine, not just a container.

1. **Install Docker Desktop** from
   <https://www.docker.com/products/docker-desktop/> — download it, run
   the installer, then open Docker Desktop from the Start menu and wait
   until it says it's running (see the Requirements section above for
   why this needs to stay open).
2. **Install Python (optional)** from
   <https://www.python.org/downloads/> if you don't already have it —
   during setup, check the box that says **"Add python.exe to PATH"**.
   This step is only used to auto-detect your CAD/slicer apps; it's
   fine to skip it entirely and either configure those apps by hand
   later, or come back and install Python then if you change your
   mind.
3. **Get the SPOOL code**: click the green **Code** button on this
   project's GitHub page, then **Download ZIP**, and unzip it (or
   `git clone` if you're comfortable with git) — then open it: right-click
   the folder in File Explorer and choose **"Open in Terminal"** (or
   **PowerShell**).
4. **Run the setup script**:

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
   auto-managed, popping up a folder picker for either one you say yes to
   (see the folder explanations near the top of this section for what
   these mean). It also generates a database password for you, starts
   everything, and tries to auto-detect your CAD/slicer apps the same way
   the macOS script does (scanning `Program Files` and similar folders
   for a recognizable install, asking you to confirm or type the exact
   path if it's not sure). Right at the end it opens SPOOL for you
   automatically in your default web browser — that's how you'll know it
   worked, no need to type any address in yourself. It's safe to run this
   whole script more than once. One genuine difference from macOS:
   there's no separate permission step needed for deleting duplicate
   files — Windows' own normal file permissions already cover that, so
   setup finishes in one fewer step.

5. Once it says you're done, skip up to [**Using SPOOL**](#using-spool)
   — everything from there on is identical regardless of which OS you
   set up on.

If anything above fails, or you'd rather understand/control every step
yourself, see **Manual setup (Windows)** below — it does exactly the
same thing by hand.

</details>

<details>
<summary><h2>🛠️ Manual setup (Windows)</h2></summary>

Full control over every step, or a fallback if `.\setup.ps1` above hit a
snag — everything here uses Windows commands and apps (PowerShell,
File Explorer, Notepad). On a Mac? See **Manual setup (Mac)** above
instead.

### Step 1: Tell SPOOL which folders to watch

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

### Step 2: Start SPOOL

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
`http://localhost:8000` in your browser (see "Starting SPOOL and opening
it" near the top of this page if you skipped straight here) — you
should see SPOOL's search page, currently empty or nearly so. Your
folders from `.env` start being indexed automatically in the
background — if they contain a lot of files, thumbnails will keep
appearing over the next while as SPOOL works through them; there's
nothing else you need to click or run for that to happen, just wait and
refresh the page occasionally.

*(If you ever change a folder path in `.env` later, editing the file
alone won't update an already-running SPOOL — go to the `/admin` page in
the browser and edit the path there instead.)*

### Step 3: Install the host-helper (lets SPOOL open files in Fusion/Bambu Studio)

Everything above runs inside Docker, which — deliberately, for safety —
can't reach out and open another app on your actual PC. One small
separate helper program handles just that piece; it's not Docker, it's a
tiny program that starts automatically in the background whenever you
log in.

Easiest path (needs Python — **optional**, see Requirements above; if
you don't have it and would rather not install it just for this, skip
straight to the "by hand" alternative below) — let it look at what's
installed and ask you to confirm:

```powershell
python host-helper\configure_apps.py
```

It scans common install folders (`Program Files`, etc.), guesses your
CAD app and slicer, and asks you to pick from a numbered list if it
finds more than one candidate (or if it finds none, lets you type the
exact `.exe` path yourself). This is exactly what `.\setup.ps1` already
ran for you if you used the setup script instead of this manual guide —
running it again re-asks and overwrites the previous choice, so it's
fine to change your mind later.

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

</details>

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

**If you set up using SPOOL Installer (the `.dmg`, Mac only):** updating
is just downloading the newer `SPOOL-Installer.dmg` and running it again
— it always installs to the same `~/Applications/SPOOL`, finds your
existing `.env` there, and offers to keep it, so nothing about your
configuration is lost. None of the steps below apply to you; they're for
the ZIP/git-based setup paths.

When a new version comes out, **don't just download a fresh ZIP into a
new folder** — your actual data (every file, tag, project, print log)
lives in Docker's own storage, not in the SPOOL folder itself, and a
new folder can leave that data behind without any obvious warning. The
one thing that *does* live in the SPOOL folder and matters is `.env`
(your folder paths and database password) — it's never part of any
download, so it has to survive the update in place.

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
steps above instead (safe, nothing is touched), or type `delete` to
confirm permanently erasing that old data and starting completely
fresh. It never silently guesses on your behalf either way.

## Day-to-day operations

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

## Known limitations

- **The Windows path is newer and hasn't been exercised on real Windows
  hardware** the way the macOS path has (this project was built on a
  Mac) — the app-detection logic in `configure_apps.py` was validated
  against synthetic test cases for real installer layouts (including
  Autodesk's own deeply-nested one), but if `setup.ps1` or the Windows
  host-helper hits something unexpected on your machine, please report
  it rather than assuming it's supposed to work that way.
- **No automatic app icons on Windows yet.** macOS extracts each
  configured app's real icon from its `.icns`; Windows apps don't have an
  equivalent step wired up yet, so a Windows-configured app just shows a
  plain two-letter badge next to a file instead of its real icon —
  cosmetic only, "Open in..." still works normally.
- **Adding a folder you initially skipped isn't a single click** — this
  covers both "I left Library/Downloads blank at setup and want it now"
  and "I want a genuinely new, fourth watched folder." The admin page
  can only edit/pause roots that already have a database row; it can't
  create one.
  - If you left **Library or Downloads blank** at setup: their bind
    mounts already exist in `docker-compose.yml` (pointed at a harmless
    placeholder folder while blank), so you just need to (1) set the
    real path in `.env`, (2) run `docker compose up -d --build` to
    remount it there, then (3) add the row yourself, since the one-time
    seed script won't retroactively do it:
    ```bash
    docker compose exec postgres psql -U spool -d spool -c \
      "INSERT INTO watched_roots (host_path, container_path, label, kind, ingest_mode, active) VALUES ('/real/path/here', '/roots/library', 'Library', 'existing_library', 'index_in_place', TRUE)"
    ```
    (swap `/roots/library`/`'Library'`/`'index_in_place'` for
    `/roots/downloads`/`'Downloads'`/`'relocate_to_dropfolder'` if it's
    Downloads you're adding.)
  - For a genuinely new **fourth** folder beyond these three: Docker
    can't attach a brand-new bind mount to an already-running container
    at all, so you'd first need to add one to `docker-compose.yml`
    yourself, then `docker compose up -d --build`, then the same manual
    `INSERT` as above.
- **Changing a path in `.env` after first setup doesn't re-seed the
  database** — the seed only runs once, against a brand-new `pgdata`
  volume. Update the path on the `/admin` page instead (and re-run
  `host-helper/install.sh` if it's one of the delete-allowlist paths).
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
on someone else's Mac or Windows machine via a single guided `./setup.sh`
/ `.\setup.ps1` — watched-root paths and CAD/slicer app choices are both
configured interactively rather than hardcoded (see setup instructions
above), with the fully manual, step-by-step path still available for
anyone who wants it. The Windows path is newer and less battle-tested
than the macOS one (see Known limitations).

## License

[GPLv3](LICENSE) — free to use, share, and modify; if you distribute a
modified version, it needs to stay open under the same license. Copyright
© 2026 Jo Wood.

## Credits

<a href="https://www.flaticon.com/free-icons/3d" title="3d icons">3d icons created by Flat-icons-com - Flaticon</a>
