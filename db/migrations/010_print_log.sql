-- Separate from print_metadata (which tracks settings used to slice/print,
-- with its own auto-extraction source-tracking) — this is the user's own
-- record of whether they've actually printed a file, how it went, and any
-- notes to refer back to later. Deliberately its own table so marking
-- "printed" can never interact with print_metadata's source column (which
-- gates whether auto-extraction is allowed to overwrite manual settings).
-- Named "comments", not "notes", specifically to avoid a duplicate form
-- field name colliding with print_metadata.notes on the same page.
CREATE TABLE print_log (
    file_id   INTEGER PRIMARY KEY REFERENCES files(id) ON DELETE CASCADE,
    printed   BOOLEAN NOT NULL DEFAULT FALSE,
    rating    SMALLINT CHECK (rating BETWEEN 1 AND 5),
    comments  TEXT
);
