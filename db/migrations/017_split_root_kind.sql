-- The old two-kind model (existing_library / drop_folder) lumped the
-- Library root (read-only, index-in-place) and the Downloads root
-- (read-write, auto-relocates new files into the drop folder) under one
-- generic "existing_library" label -- so `kind` alone couldn't tell you
-- a root's actual read-only-vs-read-write mount behavior, even though
-- docker-compose.yml already hardcodes exactly three distinct mounts
-- (dropfolder:rw, library:ro, downloads:rw). Splitting into three kinds
-- makes `kind` map 1:1 onto those three real mounts. `ingest_mode` stays
-- a separate, independently-editable column (unchanged) -- it was never
-- redundant with kind, since the admin page already lets you set either
-- ingest_mode on any root regardless of kind.
--
-- ADD VALUE can't be used in the same transaction that adds it (a
-- Postgres restriction on enum values generally), so the ADD VALUE
-- statement below must commit before the UPDATE that uses 'downloads'
-- runs -- true here since docker-entrypoint-initdb.d / a manual
-- `psql -f` run executes each top-level statement in its own implicit
-- transaction, not the whole file as one block.
ALTER TYPE root_kind RENAME VALUE 'existing_library' TO 'library';
ALTER TYPE root_kind ADD VALUE 'downloads';
