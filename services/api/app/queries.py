from psycopg.rows import dict_row

from common.db import get_connection

PAGE_SIZE = 60


# ---- search / browse ----------------------------------------------------

def search_files(q, extensions, tags, page):
    offset = (page - 1) * PAGE_SIZE
    conditions = ["status = 'active'"]
    params = []
    if q:
        conditions.append("filename ILIKE %s")
        params.append(f"%{q}%")
    if extensions:
        conditions.append("ext = ANY(%s)")
        params.append(list(extensions))
    if tags:
        conditions.append(
            "id IN (SELECT file_id FROM file_tags ft JOIN tags t ON t.id = ft.tag_id WHERE t.name = ANY(%s))"
        )
        params.append(list(tags))
    where = " AND ".join(conditions)

    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(f"SELECT count(*) AS n FROM files WHERE {where}", params)
            total = cur.fetchone()["n"]

            cur.execute(
                f"""
                SELECT id, filename, ext, thumbnail_path, render_status, is_manifold
                FROM files
                WHERE {where}
                ORDER BY first_seen_at DESC
                LIMIT %s OFFSET %s
                """,
                params + [PAGE_SIZE, offset],
            )
            rows = cur.fetchall()
    return rows, total


def get_file(file_id):
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM files WHERE id = %s", (file_id,))
            return cur.fetchone()


# ---- tags -----------------------------------------------------------------

def list_all_tags():
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT id, name FROM tags ORDER BY name")
            return cur.fetchall()


def get_file_tags(file_id):
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT t.id, t.name FROM tags t
                JOIN file_tags ft ON ft.tag_id = t.id
                WHERE ft.file_id = %s
                ORDER BY t.name
                """,
                (file_id,),
            )
            return cur.fetchall()


def add_tag_to_file(file_id, name):
    name = name.strip().lower()
    if not name:
        return
    with get_connection() as conn:
        with conn.transaction():
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "INSERT INTO tags (name) VALUES (%s) ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id",
                    (name,),
                )
                tag_id = cur.fetchone()["id"]
                cur.execute(
                    "INSERT INTO file_tags (file_id, tag_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (file_id, tag_id),
                )


def remove_tag_from_file(file_id, tag_id):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM file_tags WHERE file_id = %s AND tag_id = %s", (file_id, tag_id))


# ---- projects ---------------------------------------------------------------

def list_projects():
    """All projects with their parent + a member-file count, for the tree page."""
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT p.id, p.name, p.description, p.parent_project_id,
                       count(pf.file_id) FILTER (WHERE pf.status = 'confirmed') AS file_count
                FROM projects p
                LEFT JOIN project_files pf ON pf.project_id = p.id
                GROUP BY p.id
                ORDER BY p.name
                """
            )
            return cur.fetchall()


def get_project(project_id):
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM projects WHERE id = %s", (project_id,))
            return cur.fetchone()


def get_project_children(project_id):
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT id, name FROM projects WHERE parent_project_id = %s ORDER BY name", (project_id,))
            return cur.fetchall()


def get_project_files(project_id):
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT f.id, f.filename, f.ext, f.thumbnail_path, f.render_status, f.is_manifold
                FROM files f
                JOIN project_files pf ON pf.file_id = f.id
                WHERE pf.project_id = %s AND pf.status = 'confirmed'
                ORDER BY f.filename
                """,
                (project_id,),
            )
            return cur.fetchall()


def get_file_projects(file_id):
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT p.id, p.name FROM projects p
                JOIN project_files pf ON pf.project_id = p.id
                WHERE pf.file_id = %s AND pf.status = 'confirmed'
                ORDER BY p.name
                """,
                (file_id,),
            )
            return cur.fetchall()


def create_project(name, description, parent_project_id):
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "INSERT INTO projects (name, description, parent_project_id) VALUES (%s, %s, %s) RETURNING id",
                (name.strip(), description.strip() or None, parent_project_id or None),
            )
            return cur.fetchone()["id"]


def add_file_to_project(file_id, project_id):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO project_files (project_id, file_id, status) VALUES (%s, %s, 'confirmed')
                ON CONFLICT (project_id, file_id) DO UPDATE SET status = 'confirmed'
                """,
                (project_id, file_id),
            )


def remove_file_from_project(file_id, project_id):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM project_files WHERE file_id = %s AND project_id = %s", (file_id, project_id))


# ---- relationships ------------------------------------------------------------

# Label shown on the *near* file's page for a relationship it's part of —
# depends on which end of the (directional) row this file is on. E.g. for
# A -[derived_from]-> B, A's page reads "derived from" (pointing at B) and
# B's page reads "source for" (pointing at A).
RELATIONSHIP_LABELS = {
    ("derived_from", "out"): "derived from",
    ("derived_from", "in"): "source for",
    ("new_version_of", "out"): "new version of",
    ("new_version_of", "in"): "older version of",
    ("variant_of", "out"): "variant of",
    ("variant_of", "in"): "has variant",
    ("duplicate_of", "out"): "duplicate of",
    ("duplicate_of", "in"): "duplicated by",
}


def _fetch_relationships(file_id, status):
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT r.id, r.type, r.confidence,
                       CASE WHEN r.from_file_id = %(fid)s THEN 'out' ELSE 'in' END AS direction,
                       CASE WHEN r.from_file_id = %(fid)s THEN r.to_file_id ELSE r.from_file_id END AS other_id
                FROM relationships r
                WHERE (r.from_file_id = %(fid)s OR r.to_file_id = %(fid)s) AND r.status = %(status)s
                """,
                {"fid": file_id, "status": status},
            )
            rels = cur.fetchall()
            if not rels:
                return []
            cur.execute(
                "SELECT id, filename, ext, thumbnail_path, render_status FROM files WHERE id = ANY(%s)",
                ([r["other_id"] for r in rels],),
            )
            files_by_id = {f["id"]: f for f in cur.fetchall()}

    result = []
    for r in rels:
        other = files_by_id.get(r["other_id"])
        if other is None:
            continue
        result.append(
            {
                "id": r["id"],
                "type": r["type"],
                "confidence": r["confidence"],
                "other_id": r["other_id"],
                "label": RELATIONSHIP_LABELS[(r["type"], r["direction"])],
                "filename": other["filename"],
                "ext": other["ext"],
                "thumbnail_path": other["thumbnail_path"],
                "render_status": other["render_status"],
            }
        )
    return result


def get_file_relationships(file_id):
    return _fetch_relationships(file_id, "confirmed")


def get_suggested_relationships(file_id):
    return _fetch_relationships(file_id, "suggested")


def search_files_for_relationship(q, exclude_file_id):
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT id, filename, ext FROM files
                WHERE status = 'active' AND id != %s AND filename ILIKE %s
                ORDER BY filename LIMIT 10
                """,
                (exclude_file_id, f"%{q}%"),
            )
            return cur.fetchall()


def add_relationship(from_file_id, to_file_id, type):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO relationships (from_file_id, to_file_id, type, status)
                VALUES (%s, %s, %s, 'confirmed')
                ON CONFLICT (from_file_id, to_file_id, type) DO UPDATE SET status = 'confirmed'
                """,
                (from_file_id, to_file_id, type),
            )


def confirm_relationship(rel_id):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE relationships SET status = 'confirmed' WHERE id = %s", (rel_id,))


def reject_relationship(rel_id):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE relationships SET status = 'rejected' WHERE id = %s", (rel_id,))


def remove_relationship(rel_id):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM relationships WHERE id = %s", (rel_id,))


# ---- suggested project membership (folder-based auto-grouping) --------------

def get_suggested_file_projects(file_id):
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT p.id, p.name FROM projects p
                JOIN project_files pf ON pf.project_id = p.id
                WHERE pf.file_id = %s AND pf.status = 'suggested'
                ORDER BY p.name
                """,
                (file_id,),
            )
            return cur.fetchall()


def confirm_file_project(file_id, project_id):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE project_files SET status = 'confirmed' WHERE file_id = %s AND project_id = %s",
                (file_id, project_id),
            )


def reject_file_project(file_id, project_id):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE project_files SET status = 'rejected' WHERE file_id = %s AND project_id = %s",
                (file_id, project_id),
            )


# ---- print metadata ---------------------------------------------------------

def get_print_metadata(file_id):
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM print_metadata WHERE file_id = %s", (file_id,))
            return cur.fetchone()


def set_manual_print_metadata(file_id, material, printer_profile, slicer, notes):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO print_metadata (file_id, material, printer_profile, slicer, notes, source)
                VALUES (%s, %s, %s, %s, %s, 'manual')
                ON CONFLICT (file_id) DO UPDATE SET
                    material = EXCLUDED.material,
                    printer_profile = EXCLUDED.printer_profile,
                    slicer = EXCLUDED.slicer,
                    notes = EXCLUDED.notes,
                    source = 'manual'
                """,
                (file_id, material or None, printer_profile or None, slicer or None, notes or None),
            )


# ---- admin: watched roots -----------------------------------------------

def list_watched_roots():
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT r.id, r.label, r.host_path, r.container_path, r.kind, r.ingest_mode,
                       r.active, r.last_scanned_at, count(f.id) AS file_count
                FROM watched_roots r
                LEFT JOIN files f ON f.watched_root_id = r.id AND f.status = 'active'
                GROUP BY r.id
                ORDER BY r.id
                """
            )
            return cur.fetchall()


def update_watched_root(root_id, label, ingest_mode, active):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE watched_roots SET label = %s, ingest_mode = %s, active = %s WHERE id = %s",
                (label.strip(), ingest_mode, active, root_id),
            )
