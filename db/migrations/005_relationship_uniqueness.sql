-- Phase 06: one row per (from_file_id, to_file_id, type) triple. Lets both
-- the worker's auto-suggestion inserts (ON CONFLICT ... DO NOTHING, so a
-- rejected suggestion doesn't get silently re-suggested on the next rescan)
-- and a manual "add relationship" (ON CONFLICT ... DO UPDATE SET
-- status = 'confirmed', so linking a pair that was already suggested just
-- confirms it rather than duplicating it) use ON CONFLICT.
ALTER TABLE relationships
    ADD CONSTRAINT relationships_from_to_type_uniq UNIQUE (from_file_id, to_file_id, type);
