-- SPOOL initial schema (Phase 00)
-- Applied automatically by the postgres image on first container start
-- via /docker-entrypoint-initdb.d — see docker-compose.yml.

CREATE TYPE root_kind AS ENUM ('existing_library', 'drop_folder');
CREATE TYPE root_ingest_mode AS ENUM ('index_in_place', 'relocate_to_dropfolder');
CREATE TYPE file_status AS ENUM ('active', 'missing');
CREATE TYPE file_render_status AS ENUM ('pending', 'rendering', 'done', 'failed');
CREATE TYPE relationship_type AS ENUM ('derived_from', 'new_version_of', 'variant_of', 'duplicate_of');
CREATE TYPE suggestion_status AS ENUM ('suggested', 'confirmed', 'rejected');
CREATE TYPE metadata_source AS ENUM ('manual', 'auto_extracted_3mf', 'auto_extracted_gcode');
CREATE TYPE job_type AS ENUM ('ingest', 'render', 'rescan');
CREATE TYPE job_status AS ENUM ('queued', 'running', 'done', 'failed');

CREATE TABLE watched_roots (
    id               SERIAL PRIMARY KEY,
    host_path        TEXT NOT NULL UNIQUE,
    label            TEXT NOT NULL,
    kind             root_kind NOT NULL,
    ingest_mode      root_ingest_mode NOT NULL DEFAULT 'index_in_place',
    active           BOOLEAN NOT NULL DEFAULT TRUE,
    last_scanned_at  TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE files (
    id               SERIAL PRIMARY KEY,
    watched_root_id  INTEGER NOT NULL REFERENCES watched_roots(id) ON DELETE CASCADE,
    path             TEXT NOT NULL UNIQUE,
    filename         TEXT NOT NULL,
    ext              TEXT NOT NULL,
    size_bytes       BIGINT NOT NULL,
    content_hash     TEXT NOT NULL,
    bbox_x           REAL,
    bbox_y           REAL,
    bbox_z           REAL,
    volume_mm3       REAL,
    tri_count        INTEGER,
    is_manifold      BOOLEAN,
    units            TEXT,
    thumbnail_path   TEXT,
    render_status    file_render_status NOT NULL DEFAULT 'pending',
    status           file_status NOT NULL DEFAULT 'active',
    first_seen_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_files_content_hash ON files(content_hash);
CREATE INDEX idx_files_watched_root ON files(watched_root_id);

CREATE TABLE tags (
    id    SERIAL PRIMARY KEY,
    name  TEXT NOT NULL UNIQUE
);

CREATE TABLE file_tags (
    file_id  INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    tag_id   INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (file_id, tag_id)
);

CREATE TABLE projects (
    id                 SERIAL PRIMARY KEY,
    name               TEXT NOT NULL,
    description        TEXT,
    parent_project_id  INTEGER REFERENCES projects(id) ON DELETE SET NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_projects_parent ON projects(parent_project_id);

CREATE TABLE project_files (
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    file_id     INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    status      suggestion_status NOT NULL DEFAULT 'confirmed',
    PRIMARY KEY (project_id, file_id)
);

CREATE TABLE print_metadata (
    file_id          INTEGER PRIMARY KEY REFERENCES files(id) ON DELETE CASCADE,
    material         TEXT,
    printer_profile  TEXT,
    slicer           TEXT,
    settings_json    JSONB,
    notes            TEXT,
    source           metadata_source NOT NULL DEFAULT 'manual'
);

CREATE TABLE relationships (
    id            SERIAL PRIMARY KEY,
    from_file_id  INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    to_file_id    INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    type          relationship_type NOT NULL,
    status        suggestion_status NOT NULL DEFAULT 'suggested',
    confidence    REAL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (from_file_id <> to_file_id)
);
CREATE INDEX idx_relationships_from ON relationships(from_file_id);
CREATE INDEX idx_relationships_to ON relationships(to_file_id);

CREATE TABLE jobs (
    id            SERIAL PRIMARY KEY,
    file_id       INTEGER REFERENCES files(id) ON DELETE CASCADE,
    job_type      job_type NOT NULL,
    status        job_status NOT NULL DEFAULT 'queued',
    error         TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at  TIMESTAMPTZ
);
CREATE INDEX idx_jobs_status ON jobs(status);
