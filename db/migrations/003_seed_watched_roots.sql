-- Phase 01: seed the three roots decided in the spec. Real values for
-- this machine — this is a personal local tool, not meant to be portable.
-- Reassign/add roots later via the admin page (Phase 05).
INSERT INTO watched_roots (host_path, container_path, label, kind, ingest_mode, active) VALUES
    ('/Users/jo/Documents/3DPrintFiles', '/roots/dropfolder', 'Drop folder',           'drop_folder',      'index_in_place',        TRUE),
    ('/Users/jo/Documents/3D Printing',  '/roots/library',    'Library (placeholder)', 'existing_library', 'index_in_place',        TRUE),
    ('/Users/jo/Downloads',              '/roots/downloads',  'Downloads',             'existing_library', 'relocate_to_dropfolder', TRUE);
