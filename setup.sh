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

# A double-clicked/Platypus-wrapped app doesn't inherit the user's shell
# PATH (that only gets built up by /etc/paths.d, .zshrc, etc. for an
# interactive login shell) -- it gets a minimal LaunchServices default
# that's missing /usr/local/bin and /opt/homebrew/bin, both real install
# locations for Docker Desktop's `docker` CLI depending on the machine.
# Confirmed live: this script reported "Docker isn't installed" on a
# machine where `docker` worked fine from Terminal and Docker Desktop was
# genuinely running -- `command -v docker` simply couldn't see it in the
# PATH this process actually got. Appended, not prepended, so anything
# already legitimately on PATH still wins if it somehow differs.
export PATH="$PATH:/usr/local/bin:/opt/homebrew/bin"

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

# Shown instead of the full folder-setup flow when .env already exists —
# lets someone who just wants to check/restart SPOOL (e.g. re-opening the
# installer app later, the way you'd click Docker Desktop's whale icon)
# do that in one click, without wading through the whole guided setup
# again. Escape/closing the dialog falls through to the same "Exit"
# handling as explicitly clicking it, same reasoning as the other dialogs.
prompt_quick_action() {
  osascript -e 'button returned of (display dialog "SPOOL is already set up in this folder. What would you like to do?" buttons {"Exit", "Re-run Full Setup", "Restart SPOOL"} default button "Restart SPOOL")' 2>/dev/null
}

# Best-effort desktop shortcut — a .webloc file is a native macOS internet
# shortcut (double-click opens the URL in your default browser), the
# simplest reliable equivalent of "add to Dock" that needs no browser-
# specific scripting or extra permissions. Never fatal if the Desktop
# folder is missing/unwritable for some reason — this is a convenience,
# not a requirement, same "best-effort, don't fail the whole script over
# it" treatment as configure_apps.py's icon extraction.
create_desktop_shortcut() {
  cat > "$HOME/Desktop/SPOOL.webloc" 2>/dev/null <<'WEBLOC' || true
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>URL</key>
	<string>http://localhost:8000</string>
</dict>
</plist>
WEBLOC
}

# Postgres identifier/string-literal escaping for values interpolated
# into the SQL text below — real folder paths essentially never contain
# a literal single quote, but this costs nothing and matches the same
# defensive care _as_escape gives AppleScript strings above.
sql_escape() { printf '%s' "${1//\'/\'\'}"; }

# Keeps watched_roots in sync with whatever DROPFOLDER_HOST_PATH/
# LIBRARY_HOST_PATH/DOWNLOADS_HOST_PATH currently say in .env — this is
# what used to require a manual `docker compose exec postgres psql ...
# INSERT` by hand (see README's old "Adding a folder you initially
# skipped" instructions) every time a previously-blank folder was filled
# in, an existing one's path changed, or one was cleared. Safe to call
# every time Step 3 finishes, not just after a reconfigure — it's a
# no-op UPDATE-to-the-same-value when .env hasn't actually changed.
# Deliberately never touches label/kind/ingest_mode on a row that
# already exists, only host_path/active — an admin-page customization
# (e.g. a renamed label) must survive this running again.
reconcile_watched_roots() {
  local dropfolder library downloads sql
  dropfolder=$(sql_escape "$(sed -n 's/^DROPFOLDER_HOST_PATH=//p' .env)")
  library=$(sql_escape "$(sed -n 's/^LIBRARY_HOST_PATH=//p' .env)")
  downloads=$(sql_escape "$(sed -n 's/^DOWNLOADS_HOST_PATH=//p' .env)")

  sql="UPDATE watched_roots SET host_path = '$dropfolder', active = TRUE WHERE container_path = '/roots/dropfolder';"

  if [ -n "$library" ]; then
    sql="$sql
INSERT INTO watched_roots (host_path, container_path, label, kind, ingest_mode, active)
SELECT '$library', '/roots/library', 'Library', 'library', 'index_in_place', TRUE
WHERE NOT EXISTS (SELECT 1 FROM watched_roots WHERE container_path = '/roots/library');
UPDATE watched_roots SET host_path = '$library', active = TRUE WHERE container_path = '/roots/library';"
  else
    sql="$sql
UPDATE watched_roots SET active = FALSE WHERE container_path = '/roots/library';"
  fi

  if [ -n "$downloads" ]; then
    sql="$sql
INSERT INTO watched_roots (host_path, container_path, label, kind, ingest_mode, active)
SELECT '$downloads', '/roots/downloads', 'Downloads', 'downloads', 'relocate_to_dropfolder', TRUE
WHERE NOT EXISTS (SELECT 1 FROM watched_roots WHERE container_path = '/roots/downloads');
UPDATE watched_roots SET host_path = '$downloads', active = TRUE WHERE container_path = '/roots/downloads';"
  else
    sql="$sql
UPDATE watched_roots SET active = FALSE WHERE container_path = '/roots/downloads';"
  fi

  echo "$sql" | docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U spool -d spool >/dev/null
}

# Shared by the fast "Restart SPOOL" path above and the full setup flow's
# own Step 3 below, so re-running the whole guided setup doesn't need a
# second, duplicate copy of this.
start_and_wait() {
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
    reconcile_watched_roots
    create_desktop_shortcut
  else
    echo "SPOOL didn't respond within two minutes — check what's happening with:"
    note "docker compose ps"
    note "docker compose logs api"
  fi
}

# ---- Step 1: Docker Desktop -------------------------------------------

step "Checking for Docker Desktop"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker isn't installed."
  note "Download Docker Desktop for Mac from https://www.docker.com/products/docker-desktop/"
  note "then open SPOOL Installer again."
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
    note "in your menu bar to stop animating, then open SPOOL Installer again."
    exit 1
  fi
else
  echo "Docker is running."
fi

# ---- Step 2: .env -------------------------------------------------------

step "Configuring your folders"

# Tracked before anything below touches the filesystem — the wipe-check
# further down (a fresh .env that doesn't match an already-provisioned
# database) only makes sense when .env genuinely didn't exist yet at the
# start of this run. Reconfiguring folders on an *already* set-up install
# (the "Re-run Full Setup" -> "no, reconfigure" path) also sets
# RECONFIGURE=1 below, but there .env already exists with a real,
# working POSTGRES_PASSWORD — that path preserves it instead (see the
# password-generation step further down) rather than needing the wipe
# warning at all.
ENV_EXISTED_BEFORE=0
[ -f .env ] && ENV_EXISTED_BEFORE=1

RECONFIGURE=1
if [ -f .env ]; then
  echo "Found an existing .env file — SPOOL looks like it's already set up here."
  ACTION=$(prompt_quick_action)
  case "$ACTION" in
    "Restart SPOOL")
      step "Restarting SPOOL"
      start_and_wait
      open "http://localhost:8000" 2>/dev/null || true
      exit 0
      ;;
    "Re-run Full Setup")
      if confirm_yes_default "Keep your existing folder configuration as-is?"; then
        RECONFIGURE=0
        echo "Keeping your existing .env — skipping folder setup."
      fi
      ;;
    *)
      echo "Exiting — nothing has been changed."
      exit 0
      ;;
  esac
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
  # can't authenticate against that already-existing database. Only
  # meaningful when .env didn't exist yet at the start of this run — if
  # it did, we're reconfiguring an already-set-up install and preserve
  # its real POSTGRES_PASSWORD below regardless, so there's no mismatch
  # risk to warn about here.
  if [ "$ENV_EXISTED_BEFORE" -eq 0 ] && docker volume inspect spool_pgdata >/dev/null 2>&1; then
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

  # Preserve an existing real password rather than generating a new one
  # that can't authenticate against an already-provisioned database —
  # a real bug this used to have: reconfiguring folders on an already
  # set-up install (.env existed, with a real password matching the live
  # Postgres volume) silently regenerated POSTGRES_PASSWORD every time,
  # breaking every service's connection to that same database. Only
  # generate fresh when .env is genuinely new or still has the unfilled
  # "changeme" placeholder from .env.example.
  EXISTING_PGPASSWORD=$(sed -n 's/^POSTGRES_PASSWORD=//p' .env)
  if [ -n "$EXISTING_PGPASSWORD" ] && [ "$EXISTING_PGPASSWORD" != "changeme" ]; then
    PGPASSWORD_GENERATED="$EXISTING_PGPASSWORD"
    KEPT_EXISTING_PASSWORD=1
  else
    PGPASSWORD_GENERATED=$(openssl rand -hex 16 2>/dev/null || echo "spool-$(date +%s)")
    KEPT_EXISTING_PASSWORD=0
  fi

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

  if [ "$KEPT_EXISTING_PASSWORD" -eq 1 ]; then
    echo "Wrote .env — kept your existing database password."
  else
    echo "Wrote .env — a random database password was generated for you (nothing to remember)."
  fi
fi

# ---- Step 3: bring up the stack -----------------------------------------

step "Starting SPOOL (this can take several minutes the first time)"

start_and_wait

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
echo "A SPOOL shortcut has been added to your Desktop — double-click it any time to open SPOOL."
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
