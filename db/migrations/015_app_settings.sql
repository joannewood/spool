CREATE TABLE app_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    rescan_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    rescan_interval_seconds INTEGER NOT NULL DEFAULT 300,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO app_settings (id) VALUES (1);
