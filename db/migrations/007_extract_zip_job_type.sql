-- New job lane for zip extraction (see 008 for the tables it operates on).
-- Split into its own migration because a new enum value can't be used in
-- statements that share a transaction with the ALTER TYPE that added it —
-- same reason 004 (render_step) was its own file.
ALTER TYPE job_type ADD VALUE 'extract_zip';
