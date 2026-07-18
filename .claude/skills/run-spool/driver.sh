#!/usr/bin/env bash
# Drives the SPOOL web UI with a headless browser, from a host that has no
# browser automation tooling of its own (no Node, no Playwright, no
# chromium-cli). Runs a throwaway official Playwright container on the same
# Docker network as the running `api` service and executes a Node/Playwright
# script against it.
#
# Usage:
#   .claude/skills/run-spool/driver.sh <script.mjs> [output-dir]
#
# The script is mounted read-only at /script.mjs inside the container and
# run with `node`. It should write any screenshots to /out/*.png — pass
# output-dir (default: .claude/skills/run-spool/screenshots) to control
# where those land on the host. Talk to the app via http://api:8000 (Compose
# service DNS name), not localhost — the driver container is not on the
# host network.
set -euo pipefail

SCRIPT_PATH="$1"
OUT_DIR="${2:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/screenshots}"
PLAYWRIGHT_IMAGE="mcr.microsoft.com/playwright:v1.48.0-jammy"

mkdir -p "$OUT_DIR"

# The network name defaults to "<project-dir-name>_default" but that's
# fragile to the repo folder being renamed — ask the running api container
# what network it's actually on instead of hardcoding the name.
API_CONTAINER=$(docker compose ps -q api)
if [ -z "$API_CONTAINER" ]; then
  echo "error: api service isn't running — start it first with: docker compose up -d" >&2
  exit 1
fi
NETWORK=$(docker inspect "$API_CONTAINER" --format '{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{end}}')

docker run --rm --network "$NETWORK" \
  -v "$OUT_DIR:/out" \
  -v "$(cd "$(dirname "$SCRIPT_PATH")" && pwd)/$(basename "$SCRIPT_PATH"):/script.mjs:ro" \
  "$PLAYWRIGHT_IMAGE" bash -c '
    cd /tmp && npm init -y >/dev/null 2>&1 && npm install playwright@1.48.0 >/dev/null 2>&1
    # ESM import resolution walks up from the SCRIPT'"'"'s own path looking for
    # node_modules, not cwd — a script mounted at / can'"'"'t see /tmp/node_modules
    # unless it actually lives in /tmp too.
    cp /script.mjs /tmp/script.mjs
    node /tmp/script.mjs
  '
