-- Phase 01: a file is discovered (path, size) before it's hashed, so
-- content_hash can't be required at insert time — the worker fills it
-- in once the ingest job runs.
ALTER TABLE files ALTER COLUMN content_hash DROP NOT NULL;

-- container_path is where watcher/worker see this root mounted inside
-- their own containers; host_path (already on the table) is the real
-- macOS path stored on every file and used outside Docker (host-helper,
-- you). Ingestion code translates between the two.
ALTER TABLE watched_roots ADD COLUMN container_path TEXT NOT NULL;
