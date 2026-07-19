#!/bin/bash
# Phase 01: seed the three watched roots — driven by environment variables
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
set -euo pipefail

: "${DROPFOLDER_HOST_PATH:?DROPFOLDER_HOST_PATH must be set — copy .env.example to .env and fill in your real paths}"
: "${LIBRARY_HOST_PATH:?LIBRARY_HOST_PATH must be set — copy .env.example to .env and fill in your real paths}"
: "${DOWNLOADS_HOST_PATH:?DOWNLOADS_HOST_PATH must be set — copy .env.example to .env and fill in your real paths}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    INSERT INTO watched_roots (host_path, container_path, label, kind, ingest_mode, active) VALUES
        ('$DROPFOLDER_HOST_PATH', '/roots/dropfolder', 'Drop folder', 'drop_folder',      'index_in_place',        TRUE),
        ('$LIBRARY_HOST_PATH',    '/roots/library',    'Library',     'existing_library', 'index_in_place',        TRUE),
        ('$DOWNLOADS_HOST_PATH',  '/roots/downloads',  'Downloads',   'existing_library', 'relocate_to_dropfolder', TRUE);
EOSQL
