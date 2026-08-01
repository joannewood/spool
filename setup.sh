#!/bin/bash
# Interactive, guided setup for SPOOL — the automated equivalent of the
# "Setting up on your own machine" steps in README.md. Safe to re-run any
# time (e.g. after a `git pull`): it detects an existing .env and offers to
# keep it rather than clobbering your configuration. The manual, step-by-
# step process in the README still works exactly as documented if you'd
# rather do this by hand, or need to debug a step this script glossed over.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

BOLD=$(tput bold 2>/dev/null || true)
DIM=$(tput dim 2>/dev/null || true)
RESET=$(tput sgr0 2>/dev/null || true)

step() { echo; echo "${BOLD}==> $1${RESET}"; }
note() { echo "${DIM}    $1${RESET}"; }

# Native Yes/No dialogs instead of reading stdin — this script never reads
# input from the terminal at all now, so it works identically whether run
# from a Terminal window or from inside a wrapped/double-clicked installer
# app (e.g. a Platypus "Text Window" app, which only displays output —
# forwarding keystrokes back into the script's stdin isn't something to
# depend on). Escape/closing the dialog is treated as "No" either way,
# since osascript's own "user canceled" error just leaves $answer empty.
# A bare ASCII double quote inside a prompt string would otherwise close the
# AppleScript string literal early and break the dialog (confirmed live:
# an un-escaped embedded quote produced a real "Expected "," but found
# identifier" syntax error from osascript) — escape any that show up so a
# future edit to a message can't reintroduce that bug.
_as_escape() { printf '%s' "${1//\"/\\\"}"; }

confirm_yes_default() {  # [Y/n]
  local prompt answer
  prompt=$(_as_escape "$1")
  answer=$(osascript -e "button returned of (display dialog \"$prompt\" buttons {\"No\", \"Yes\"} default button \"Yes\")" 2>/dev/null)
  [ "$answer" = "Yes" ]
}

confirm_no_default() {  # [y/N]
  local prompt answer
  prompt=$(_as_escape "$1")
  answer=$(osascript -e "button returned of (display dialog \"$prompt\" buttons {\"No\", \"Yes\"} default button \"No\")" 2>/dev/null)
  [ "$answer" = "Yes" ]
}

# For the one destructive prompt — default button stays the safe choice, and
# the affirmative one is spelled out rather than a bare "Yes" so the dialog
# alone (without reading the surrounding text) makes the stakes clear.
confirm_destructive() {
  local prompt answer
  prompt=$(_as_escape "$1")
  answer=$(osascript -e "button returned of (display dialog \"$prompt\" buttons {\"Cancel\", \"Delete Everything\"} default button \"Cancel\" with icon caution)" 2>/dev/null)
  [ "$answer" = "Delete Everything" ]
}

# ---- Step 1: Docker Desktop -------------------------------------------

step "Checking for Docker Desktop"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker isn't installed."
  note "Download Docker Desktop for Mac from https://www.docker.com/products/docker-desktop/"
  note "then run this script again."
  open "https://www.docker.com/products/docker-desktop/" 2>/dev/null || true
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "Docker Desktop isn't running — starting it now..."
  open -a Docker 2>/dev/null || true
  printf "Waiting for Docker to be ready"
  for _ in $(seq 1 60); do
    if docker info >/dev/null 2>&1; then
      echo " ready."
      break
    fi
    printf "."
    sleep 2
  done
  if ! docker info >/dev/null 2>&1; then
    echo
    echo "Docker Desktop still isn't responding after two minutes."
    note "Open Docker Desktop from Applications yourself, wait for the whale icon"
    note "in your menu bar to stop animating, then run this script again."
    exit 1
  fi
else
  echo "Docker is running."
fi

# ---- Step 2: .env -------------------------------------------------------

step "Configuring your folders"

RECONFIGURE=1
if [ -f .env ]; then
  echo "Found an existing .env file."
  if confirm_yes_default "Found an existing .env file. Keep it as-is?"; then
    RECONFIGURE=0
    echo "Keeping your existing .env — skipping folder setup."
  fi
fi

pick_folder() {
  # $1 = prompt text, $2 = fallback path if the picker is cancelled/unavailable
  local prompt="$1" fallback="$2" result
  if result=$(osascript -e "POSIX path of (choose folder with prompt \"$prompt\")" 2>/dev/null); then
    echo "${result%/}"
  else
    echo "$fallback"
  fi
}

if [ "$RECONFIGURE" -eq 1 ]; then
  # Safety net for the most likely way to lose data without realizing it:
  # docker-compose.yml pins the project name to "spool" (see its own
  # comment) specifically so your database survives a downloaded update
  # landing in a differently-named folder — but that only helps if this
  # fresh setup doesn't also generate a *new* database password that
  # can't authenticate against that already-existing database. Detected
  # by checking for the volume before writing anything.
  if docker volume inspect spool_pgdata >/dev/null 2>&1; then
    echo
    echo "⚠ Found an existing SPOOL database from a previous setup, but there's"
    echo "  no .env in this folder yet to match it. This usually means you're"
    echo "  running setup fresh after downloading an update into a new folder."
    echo
    echo "  If you want to keep your existing library: stop now, and see"
    echo "  \"Updating SPOOL\" in README.md instead — copying your old .env into"
    echo "  this folder keeps everything. Generating a new one here instead"
    echo "  cannot connect to that existing database (the password won't match),"
    echo "  and continuing anyway means permanently deleting it first."
    echo
    if confirm_destructive "Found an existing SPOOL database from a previous setup, but there's no .env in this folder yet to match it.\n\nIf you want to keep your existing library, stop now and see “Updating SPOOL” in README.md instead. Continuing here permanently deletes that existing database."; then
      echo "Removing the old database..."
      docker volume rm spool_pgdata spool_thumbnails >/dev/null 2>&1 || true
      echo "Done — continuing with a fresh setup."
    else
      echo "Stopping — nothing has been changed. See README.md's \"Updating SPOOL\" section."
      exit 1
    fi
  fi

  cp -n .env.example .env 2>/dev/null || true

  echo
  echo "A Finder window will pop up for each folder below — navigate to (or use"
  echo "Finder's \"New Folder\" button to create) the right one, then click Choose."
  echo

  note "1 of 3 — your drop folder (where new downloads/exports land to be indexed)"
  echo "This one's required — it's SPOOL's main working folder."
  DEFAULT_DROP="$HOME/Documents/3DPrintFiles"
  DROPFOLDER_HOST_PATH=$(pick_folder "Choose your SPOOL drop folder" "$DEFAULT_DROP")
  mkdir -p "$DROPFOLDER_HOST_PATH"

  note "2 of 3 — your existing 3D print library (optional; read-only, SPOOL only indexes it)"
  LIBRARY_HOST_PATH=""
  if confirm_no_default "Do you have an existing 3D print library folder you'd like SPOOL to index too?"; then
    LIBRARY_HOST_PATH=$(pick_folder "Choose your existing 3D print library folder" "$HOME/Documents/3D Printing")
  else
    echo "    skipping — SPOOL will only watch your drop folder for now. You can add"
    echo "    this later; see \"Known limitations\" in README.md for how."
  fi

  note "3 of 3 — your Downloads folder (optional; new model files here get moved into your drop folder)"
  DOWNLOADS_HOST_PATH=""
  if confirm_yes_default "Auto-move new 3D-print files out of your Downloads folder into your drop folder?"; then
    DOWNLOADS_HOST_PATH="$HOME/Downloads"
    echo "    using $DOWNLOADS_HOST_PATH"
  else
    echo "    skipping — you can add this later; see \"Known limitations\" in README.md for how."
  fi

  PGPASSWORD_GENERATED=$(openssl rand -hex 16 2>/dev/null || echo "spool-$(date +%s)")

  # sed, not `source .env` — a plain source word-splits unquoted values, and
  # a real path like "/Users/you/Documents/3D Printing" (unquoted, same as
  # docker-compose's own tolerant .env parsing already expects) would break
  # immediately (same reasoning as host-helper/install.sh's read_env_var).
  sed -i '' \
    -e "s#^DROPFOLDER_HOST_PATH=.*#DROPFOLDER_HOST_PATH=$DROPFOLDER_HOST_PATH#" \
    -e "s#^LIBRARY_HOST_PATH=.*#LIBRARY_HOST_PATH=$LIBRARY_HOST_PATH#" \
    -e "s#^DOWNLOADS_HOST_PATH=.*#DOWNLOADS_HOST_PATH=$DOWNLOADS_HOST_PATH#" \
    -e "s#^POSTGRES_PASSWORD=.*#POSTGRES_PASSWORD=$PGPASSWORD_GENERATED#" \
    .env

  echo "Wrote .env — a random database password was generated for you (nothing to remember)."
fi

# ---- Step 3: bring up the stack -----------------------------------------

step "Starting SPOOL (this can take several minutes the first time)"

docker compose up -d --build

printf "Waiting for the web app to respond"
READY=0
for _ in $(seq 1 60); do
  if curl -sf http://localhost:8000/health >/dev/null 2>&1; then
    READY=1
    break
  fi
  printf "."
  sleep 2
done
echo
if [ "$READY" -eq 1 ]; then
  echo "SPOOL is up: http://localhost:8000"
else
  echo "SPOOL didn't respond within two minutes — check what's happening with:"
  note "docker compose ps"
  note "docker compose logs api"
fi

# ---- Step 4: host-helper (Open in Fusion/Bambu Studio/etc.) -------------

step "Setting up 'Open in...' for your CAD/slicer apps"

if confirm_yes_default "Auto-detect your installed CAD/slicer apps now?"; then
  if command -v python3 >/dev/null 2>&1; then
    python3 host-helper/configure_apps.py
  else
    echo "python3 isn't available — skipping. Edit host-helper/host_helper.py's"
    note "APP_MAP by hand instead (see README.md), or install python3 and re-run this script."
  fi
else
  note "Skipped — 'Open in...' buttons won't work until you run"
  note "python3 host-helper/configure_apps.py (or edit host_helper.py by hand) later."
fi

host-helper/install.sh

# ---- Done -----------------------------------------------------------------

step "All set"

echo "SPOOL is running at http://localhost:8000"
open "http://localhost:8000" 2>/dev/null || true
echo
echo "One thing that still needs a one-time manual click: deleting a"
echo "duplicate file needs Full Disk Access, which macOS won't let any"
echo "script grant on your behalf."
if confirm_yes_default "Open that Settings page now?"; then
  open "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles" 2>/dev/null || true
  echo "Add /usr/bin/python3 there (click +, press Cmd+Shift+G, type /usr/bin, select python3)."
fi
echo
echo "See README.md's \"Using SPOOL\" section for a walkthrough, and"
echo "\"Known limitations\" / \"Gotchas and best practices\" before you dive in."
