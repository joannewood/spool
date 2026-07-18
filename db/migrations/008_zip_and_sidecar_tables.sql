-- Zip files worth reviewing (peeked and found to contain a recognized
-- model file) and the non-model "sidecar" files (README, preview images,
-- etc.) that live alongside model files in a project folder.

CREATE TABLE zip_files (
    id               SERIAL PRIMARY KEY,
    watched_root_id  INTEGER NOT NULL REFERENCES watched_roots(id) ON DELETE CASCADE,
    path             TEXT NOT NULL UNIQUE,
    filename         TEXT NOT NULL,
    size_bytes       BIGINT NOT NULL,
    status           suggestion_status NOT NULL DEFAULT 'suggested',
    error            TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- A rejected row is kept forever — ON CONFLICT (path) DO NOTHING on
-- rediscovery means a declined zip is never re-asked-about on a later scan.

CREATE TABLE sidecar_files (
    id               SERIAL PRIMARY KEY,
    watched_root_id  INTEGER NOT NULL REFERENCES watched_roots(id) ON DELETE CASCADE,
    path             TEXT NOT NULL UNIQUE,
    filename         TEXT NOT NULL,
    ext              TEXT NOT NULL,
    size_bytes       BIGINT NOT NULL,
    first_seen_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_sidecar_files_root ON sidecar_files(watched_root_id);

ALTER TABLE jobs ADD COLUMN zip_file_id INTEGER REFERENCES zip_files(id) ON DELETE CASCADE;
