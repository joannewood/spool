---
name: run-spool
description: Launch, drive, and screenshot the SPOOL web UI (browse/search grid, file detail pages) in a headless browser. Use when asked to run SPOOL, start the app, take a screenshot, verify a UI change, or check the app works end to end. Also covers building/starting the full docker compose stack (postgres, api, watcher, worker, worker-step).
---

Paths below are relative to the repo root (`data-platform/`), not this skill directory.

SPOOL is a Docker Compose app (5 services — see `CLAUDE.md`) with no local
dev-server mode; `api` only runs inside its container. This host has **no
browser automation tooling at all** — no Node, no Playwright, no
chromium-cli — so driving the UI means running a throwaway
`mcr.microsoft.com/playwright` container on the same Docker network as
`api` and controlling it with a Node/Playwright script. That's what
`driver.sh` in this directory does.

## Prerequisites

Docker Desktop running (`docker info` succeeds). Nothing else — the
Playwright image and its browsers are pulled/cached by `driver.sh` itself.

## Build & launch

```bash
docker compose up -d --build
docker compose ps --format '{{.Service}}: {{.Status}}'   # all 5 should be Up
curl -s http://localhost:8000/health                      # {"status":"ok","database":"connected"}
```

## Run (agent path) — this is the one to use

```bash
.claude/skills/run-spool/driver.sh <script.mjs> [output-dir]
```

- `<script.mjs>` is a Playwright script using ESM `import { chromium } from "playwright"`.
  Talk to the app at `http://api:8000` (Compose's internal service DNS) — the
  driver container is on the Compose network, not the host network, so
  `localhost:8000` will NOT work from inside the script.
- Write screenshots to `/out/*.png` inside the script — that's a bind mount
  to `output-dir` (default: `.claude/skills/run-spool/screenshots/`, gitignored).
- `driver.sh` auto-detects the Docker network from the running `api`
  container (`docker inspect`), so it survives the repo folder being
  renamed even though Compose's default network name is derived from it.

A ready-to-use example that exercises the real user flow (browse → search →
open a file) is checked in at `example-flow.mjs`:

```bash
.claude/skills/run-spool/driver.sh .claude/skills/run-spool/example-flow.mjs
# -> {"searchResultCount":1,"detailUrl":"http://api:8000/files/3","consoleErrors":[]}
# screenshots: .claude/skills/run-spool/screenshots/01-index.png, 02-search.png, 03-detail.png
```

For a one-off check, write a small script inline and run it the same way,
e.g. to hit a new route and screenshot it:

```bash
cat > /tmp/check.mjs <<'EOF'
import { chromium } from "playwright";
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
await page.goto("http://api:8000/files/1", { waitUntil: "networkidle" });
await page.screenshot({ path: "/out/check.png", fullPage: true });
await browser.close();
EOF
.claude/skills/run-spool/driver.sh /tmp/check.mjs
```

**Always read the screenshot after taking it** (e.g. with the Read tool on
the PNG) — a 200 response and zero console errors don't prove the page
looks right.

## Run (human path)

Open `http://localhost:8000/` in a real browser once the stack is up. No
build step, no separate frontend process — `api` serves everything.

## Gotchas

- **ESM import resolution is by the script's own file path, not cwd.** A
  script bind-mounted at `/script.mjs` can't see `node_modules` installed
  in `/tmp` even if you `cd /tmp` first — Node walks up from where the
  *file* lives. `driver.sh` copies the script into `/tmp` before running it
  for exactly this reason; don't mount scripts anywhere else if you're
  bypassing the driver.
- **The Playwright image doesn't bundle the `playwright` npm package for
  general use** — it has the browsers and system deps, but you still
  `npm install playwright@1.48.0` inside the container. `driver.sh` does
  this every run (a few seconds, no browser re-download since those are
  already in the image).
- **`localhost:8000` vs `api:8000`** — inside the driver container you're
  on the Compose network, so it's `http://api:8000`, not `localhost:8000`
  (which was the api service's host-mapped port, not reachable from here).
- **htmx search has a 250ms debounce** (`hx-trigger="input changed
  delay:250ms..."` in `index.html`) — `page.fill()` then an immediate
  `waitForLoadState` can race it. Wait at least that long before waiting
  for network idle.
- **`docker compose ps -q api` returns empty if the stack isn't up** —
  `driver.sh` checks this and fails fast with a clear message rather than
  a confusing docker network error.

## Troubleshooting

- `Error [ERR_MODULE_NOT_FOUND]: Cannot find package 'playwright'` — you
  ran `node` on a script that wasn't copied into `/tmp` alongside
  `node_modules`. Use `driver.sh`, not a raw `docker run`.
- `error: api service isn't running` — run `docker compose up -d --build`
  from the repo root first.
- Screenshot is blank/white — almost always means `waitUntil: "networkidle"`
  fired before htmx's swap finished; add a `waitForTimeout` matching the
  debounce, or `waitForSelector` on something the swap introduces.
