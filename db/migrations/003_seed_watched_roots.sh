#!/bin/bash
# Phase 01: seed the watched roots — driven by environment variables
# (set in docker-compose.yml's postgres service from the repo's .env)
# instead of one person's literal host paths, so a fresh clone seeds
# against whatever folders the new user configured. This used to be a
# static .sql INSERT with hardcoded /Users/jo/... values; a .sh file is
# used specifically so this step can read the environment (Postgres's
# docker-entrypoint-initdb.d runs .sh scripts with the container's env
# intact, same as any other init file — .sql files can't do variable
# substitution on their own). Runs once, same as every other file in this
# directory (docker-entrypoint-initdb.d only executes on a truly empty
# pgdata volume) — reassign/add roots later via the admin page.
#
# DROPFOLDER_HOST_PATH is required — SPOOL is built around having a real
# working folder. LIBRARY_HOST_PATH/DOWNLOADS_HOST_PATH are each optional:
# left blank in .env, no row is seeded for that one at all (not seeded-
# but-inactive — it simply doesn't exist, same as if this were the only
# root anyone had ever configured), for someone who just wants SPOOL
# watching one folder rather than an existing library and/or a Downloads
# auto-relocate. docker-compose.yml's bind mounts for these two fall back
# to a harmless local placeholder directory when blank, since a Docker
# bind mount source can't itself be empty — but that placeholder is never
# referenced by anything once there's no DB row pointing at it.
set -euo pipefail

: "${DROPFOLDER_HOST_PATH:?DROPFOLDER_HOST_PATH must be set — copy .env.example to .env and fill in your real paths}"

VALUES="('$DROPFOLDER_HOST_PATH', '/roots/dropfolder', 'Drop folder', 'drop_folder', 'index_in_place', TRUE)"

if [ -n "${LIBRARY_HOST_PATH:-}" ]; then
  VALUES="$VALUES,
        ('$LIBRARY_HOST_PATH', '/roots/library', 'Library', 'existing_library', 'index_in_place', TRUE)"
fi

if [ -n "${DOWNLOADS_HOST_PATH:-}" ]; then
  VALUES="$VALUES,
        ('$DOWNLOADS_HOST_PATH', '/roots/downloads', 'Downloads', 'existing_library', 'relocate_to_dropfolder', TRUE)"
fi

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    INSERT INTO watched_roots (host_path, container_path, label, kind, ingest_mode, active) VALUES
        $VALUES;
EOSQL
