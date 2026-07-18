-- Phase 07: cheap drift signal for periodic rescan — stat a file (fast)
-- before deciding whether it needs re-hashing (slow). NULL on existing rows
-- deliberately reads as "changed" to the rescan's drift check, so the first
-- pass after this migration re-hashes everything once (confirms hashes
-- still match) and then settles into only hashing files that actually
-- changed size or mtime.
ALTER TABLE files ADD COLUMN mtime TIMESTAMPTZ;
