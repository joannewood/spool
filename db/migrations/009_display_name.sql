-- User-editable display name, separate from the real on-disk filename —
-- for files whose actual filename/path isn't descriptive. NULL means "no
-- override, just show the filename" everywhere it's rendered.
ALTER TABLE files ADD COLUMN display_name TEXT;
