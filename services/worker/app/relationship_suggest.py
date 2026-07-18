import os
import re

from psycopg.rows import dict_row

STEP_EXTS = (".step", ".stp")

# "widget_v2", "widget-v12", "widget v3" -> base "widget", version 2/12/3.
# Same-extension only — a version bump is meaningful within one file format.
_VERSION_RE = re.compile(r"^(?P<base>.+?)[ _-]v(?P<ver>\d+)$", re.IGNORECASE)


def _stem(filename):
    return os.path.splitext(filename)[0]


def _parse_version(stem):
    m = _VERSION_RE.match(stem)
    if not m:
        return None
    return m.group("base").strip().lower(), int(m.group("ver"))


def _suggest(conn, from_id, to_id, rel_type, confidence):
    """Idempotent: a prior manual confirm/reject on this exact pair+type
    (enforced by the relationships_from_to_type_uniq constraint) is left
    alone — only inserts if this exact triple has never been suggested."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO relationships (from_file_id, to_file_id, type, status, confidence)
            VALUES (%s, %s, %s, 'suggested', %s)
            ON CONFLICT (from_file_id, to_file_id, type) DO NOTHING
            """,
            (from_id, to_id, rel_type, confidence),
        )


def suggest_for_file(conn, file_id, filename, ext):
    """Runs once per newly-hashed file, comparing it against files already
    indexed (called from both the live ingest path and backfill, which
    processes files one at a time — so by the time file B is processed,
    any earlier file A it matches is already in the table; the pair gets
    caught the first time either member is the "new" one)."""
    stem = _stem(filename)
    ext = ext.lower()

    with conn.cursor(row_factory=dict_row) as cur:
        # Exact content match -> duplicate_of, regardless of filename/location.
        cur.execute(
            """
            SELECT other.id FROM files this, files other
            WHERE this.id = %s AND other.id != this.id AND other.status = 'active'
              AND this.content_hash IS NOT NULL AND other.content_hash = this.content_hash
            """,
            (file_id,),
        )
        for row in cur.fetchall():
            newer, older = sorted((file_id, row["id"]))
            _suggest(conn, newer, older, "duplicate_of", 1.0)

        # Same basename, different extension -> the non-STEP file was
        # (probably) exported from the STEP source.
        cur.execute(
            """
            SELECT id, ext FROM files
            WHERE status = 'active' AND id != %s
              AND lower(regexp_replace(filename, '\\.[^.]+$', '')) = %s
            """,
            (file_id, stem.lower()),
        )
        for row in cur.fetchall():
            other_id, other_ext = row["id"], row["ext"].lower()
            if other_ext in STEP_EXTS and ext not in STEP_EXTS:
                _suggest(conn, file_id, other_id, "derived_from", 0.6)
            elif ext in STEP_EXTS and other_ext not in STEP_EXTS:
                _suggest(conn, other_id, file_id, "derived_from", 0.6)

        # "name_v2" vs "name_v1" (same extension) -> new_version_of, newer -> older.
        parsed = _parse_version(stem)
        if parsed is not None:
            base, ver = parsed
            cur.execute(
                "SELECT id, filename FROM files WHERE status = 'active' AND id != %s AND ext = %s",
                (file_id, ext),
            )
            for row in cur.fetchall():
                other_parsed = _parse_version(_stem(row["filename"]))
                if other_parsed is not None and other_parsed[0] == base and other_parsed[1] != ver:
                    newer, older = (file_id, row["id"]) if ver > other_parsed[1] else (row["id"], file_id)
                    _suggest(conn, newer, older, "new_version_of", 0.8)


def suggest_folder_project(conn, file_id, host_path, root):
    """Flat, per-leaf-folder grouping: any indexed file sitting in a
    meaningful subfolder (even alone) gets a suggested project named after
    that folder — a lone file today just means a project of one, ready to
    pick up siblings later. Deliberately does NOT mirror the whole
    directory tree — a folder two levels deep still becomes one flat
    project, not a chain of nested ones.

    Known simplification: matching is by folder *name* only (projects have
    no folder-path column), so two same-named leaf folders in unrelated
    parts of the library merge into one project. Acceptable for a personal
    library; would need a schema change to fix properly.
    """
    directory = os.path.dirname(host_path)
    if os.path.normpath(directory) == os.path.normpath(root.host_path):
        return  # sits directly in the watched root — not a meaningful group

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT id, path FROM files WHERE status = 'active' AND path LIKE %s",
            (directory + os.sep + "%",),
        )
        siblings = [r for r in cur.fetchall() if os.path.dirname(r["path"]) == directory]
    if not siblings:
        return

    folder_name = os.path.basename(directory)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT id FROM projects WHERE parent_project_id IS NULL AND lower(name) = lower(%s)",
            (folder_name,),
        )
        row = cur.fetchone()
        project_id = row["id"] if row else None
        if project_id is None:
            cur.execute("INSERT INTO projects (name) VALUES (%s) RETURNING id", (folder_name,))
            project_id = cur.fetchone()["id"]

        for sibling in siblings:
            cur.execute(
                """
                INSERT INTO project_files (project_id, file_id, status) VALUES (%s, %s, 'suggested')
                ON CONFLICT (project_id, file_id) DO NOTHING
                """,
                (project_id, sibling["id"]),
            )
