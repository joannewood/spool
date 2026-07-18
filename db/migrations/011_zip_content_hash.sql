-- A rejected zip should only stay rejected for that exact content, not
-- forever for that path — a common filename like "Archive.zip" gets reused
-- for genuinely different downloads over time (old one deleted, new one
-- dropped in with the same name). Uniqueness moves from path alone to
-- (path, content_hash): the same content at the same path still won't be
-- re-asked about, but different content at a previously-used path gets a
-- fresh row and a fresh 'suggested' status.
ALTER TABLE zip_files ADD COLUMN content_hash TEXT;
ALTER TABLE zip_files DROP CONSTRAINT zip_files_path_key;
ALTER TABLE zip_files ADD CONSTRAINT zip_files_path_hash_key UNIQUE (path, content_hash);
