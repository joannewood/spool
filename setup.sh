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
  read -r -p "Keep it as-is? [Y/n] " keep_env
  if [[ ! "$keep_env" =~ ^[Nn] ]]; then
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
  cp -n .env.example .env 2>/dev/null || true

  echo
  echo "A Finder window will pop up for each folder below — navigate to (or use"
  echo "Finder's \"New Folder\" button to create) the right one, then click Choose."
  echo

  note "1 of 3 — your drop folder (where new downloads/exports land to be indexed)"
  DEFAULT_DROP="$HOME/Documents/3DPrintFiles"
  DROPFOLDER_HOST_PATH=$(pick_folder "Choose your SPOOL drop folder" "$DEFAULT_DROP")
  mkdir -p "$DROPFOLDER_HOST_PATH"

  note "2 of 3 — your existing 3D print library (read-only; SPOOL only indexes it)"
  LIBRARY_HOST_PATH=$(pick_folder "Choose your existing 3D print library folder" "$HOME/Documents/3D Printing")
  mkdir -p "$LIBRARY_HOST_PATH"

  note "3 of 3 — your Downloads folder (new model files here get moved into your drop folder)"
  DOWNLOADS_HOST_PATH="$HOME/Downloads"
  echo "    using $DOWNLOADS_HOST_PATH"

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

read -r -p "Auto-detect your installed CAD/slicer apps now? [Y/n] " do_apps
if [[ ! "$do_apps" =~ ^[Nn] ]]; then
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
read -r -p "Open that Settings page now? [Y/n] " do_privacy
if [[ ! "$do_privacy" =~ ^[Nn] ]]; then
  open "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles" 2>/dev/null || true
  echo "Add /usr/bin/python3 there (click +, press Cmd+Shift+G, type /usr/bin, select python3)."
fi
echo
echo "See README.md's \"Using SPOOL\" section for a walkthrough, and"
echo "\"Known limitations\" / \"Gotchas and best practices\" before you dive in."
