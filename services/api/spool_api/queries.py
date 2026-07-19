import re

from psycopg.rows import dict_row

from common.db import get_connection
from common.text import clean_name

PAGE_SIZE = 60


# ---- search / browse ----------------------------------------------------

SORT_CLAUSES = {
    "newest": "first_seen_at DESC",
    "oldest": "first_seen_at ASC",
    "name_asc": "COALESCE(display_name, filename) ASC",
    "name_desc": "COALESCE(display_name, filename) DESC",
    "size_desc": "size_bytes DESC",
    "size_asc": "size_bytes ASC",
}

_NUMBER_RE = re.compile(r"(\d+(?:\.\d+)?)")

# Keyword -> (settings_json key, match tolerance). Bambu's auto-extraction
# (worker/app/bambu_metadata.py) writes these as plain numbers inside
# print_metadata.settings_json — "0.2mm nozzle" or "20% infill" can't match
# via a text ILIKE, since the JSON just holds e.g. "nozzle_diameter_mm": 0.2,
# no "mm"/"nozzle" text anywhere near it. Keyword-presence + nearest-number
# (not strict phrase order) so both "0.2mm nozzle" and "nozzle 0.2mm" work —
# deliberately loose, this is a convenience heuristic, not a full parser.
_STRUCTURED_METADATA_FIELDS = {
    "nozzle": ("nozzle_diameter_mm", 0.005),
    "layer": ("layer_height_mm", 0.005),
    "infill": ("infill_density_pct", 0.5),
}


def _structured_metadata_clauses(q):
    q_lower = q.lower()
    clauses, params = [], []
    for keyword, (json_key, tolerance) in _STRUCTURED_METADATA_FIELDS.items():
        if keyword not in q_lower:
            continue
        match = _NUMBER_RE.search(q_lower)
        if not match:
            continue
        value = float(match.group(1))
        clauses.append(
            f"""id IN (
                SELECT file_id FROM print_metadata
                WHERE settings_json->>'{json_key}' ~ '^\\d+\\.?\\d*$'
                  AND (settings_json->>'{json_key}')::float BETWEEN %s AND %s
            )"""
        )
        params.extend([value - tolerance, value + tolerance])
    return clauses, params


_METADATA_FILTER_COLUMNS = {"material", "printer_profile", "slicer"}


def list_print_metadata_values(column):
    """Distinct non-empty values for a print_metadata column — populates
    the filter panel's Material/Printer/Slicer dropdowns with values that
    actually exist, rather than free text (this is a *filter*, picking
    from what's really in the library, not another search box — the main
    search bar already does free-text ILIKE across these same columns).
    `column` must be one of `_METADATA_FILTER_COLUMNS`: interpolated
    directly into the query, so never accept this from raw user input."""
    if column not in _METADATA_FILTER_COLUMNS:
        raise ValueError(f"invalid print_metadata filter column: {column}")
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT DISTINCT {column} FROM print_metadata
                WHERE {column} IS NOT NULL AND {column} != ''
                ORDER BY {column}
                """
            )
            return [row[0] for row in cur.fetchall()]


def search_files(
    q, extensions, tags, page, sort="newest",
    ratings=None, printed=None, material=None, printer_profile=None, slicer=None,
):
    offset = (page - 1) * PAGE_SIZE
    conditions = ["status = 'active'"]
    params = []
    if q:
        q_conditions = [
            """(
                filename ILIKE %s OR display_name ILIKE %s OR id IN (
                    SELECT file_id FROM print_metadata
                    WHERE material ILIKE %s OR printer_profile ILIKE %s
                       OR slicer ILIKE %s OR notes ILIKE %s
                ) OR id IN (
                    SELECT file_id FROM print_log WHERE comments ILIKE %s
                )
            )"""
        ]
        q_params = [f"%{q}%"] * 7

        structured_clauses, structured_params = _structured_metadata_clauses(q)
        q_conditions.extend(structured_clauses)
        q_params.extend(structured_params)

        conditions.append("(" + " OR ".join(q_conditions) + ")")
        params.extend(q_params)
    if extensions:
        conditions.append("ext = ANY(%s)")
        params.append(list(extensions))
    if tags:
        conditions.append(
            "id IN (SELECT file_id FROM file_tags ft JOIN tags t ON t.id = ft.tag_id WHERE t.name = ANY(%s))"
        )
        params.append(list(tags))
    if ratings:
        conditions.append("id IN (SELECT file_id FROM print_log WHERE rating = ANY(%s))")
        params.append(list(ratings))
    if printed == "yes":
        conditions.append("id IN (SELECT file_id FROM print_log WHERE printed = true)")
    elif printed == "no":
        # No print_log row at all counts as "not printed" too, not just an
        # explicit printed=false row — NOT IN a file_id-only subquery
        # handles both the same way.
        conditions.append("id NOT IN (SELECT file_id FROM print_log WHERE printed = true)")
    if material:
        conditions.append("id IN (SELECT file_id FROM print_metadata WHERE material = %s)")
        params.append(material)
    if printer_profile:
        conditions.append("id IN (SELECT file_id FROM print_metadata WHERE printer_profile = %s)")
        params.append(printer_profile)
    if slicer:
        conditions.append("id IN (SELECT file_id FROM print_metadata WHERE slicer = %s)")
        params.append(slicer)
    where = " AND ".join(conditions)
    order_by = SORT_CLAUSES.get(sort, SORT_CLAUSES["newest"])
    order_params = []
    if q:
        # Plain ILIKE says whether a row matched, not how well — an exact
        # or prefix filename match reads as far more "relevant" than a
        # mid-string substring hit or a match that only came from
        # print_metadata/print_log, but without this they all sorted
        # identically (by whatever the sort dropdown said, usually
        # "newest"). Rank by match quality against the name first, then
        # fall back to the user's chosen sort as the tiebreaker within
        # each tier — so "newest" still means something among
        # equally-relevant results, it just isn't the primary key anymore.
        name_expr = "COALESCE(display_name, filename)"
        order_by = f"""
            CASE
                WHEN {name_expr} ILIKE %s THEN 0
                WHEN {name_expr} ILIKE %s THEN 1
                WHEN {name_expr} ILIKE %s THEN 2
                ELSE 3
            END,
            {order_by}
        """
        order_params = [q, f"{q}%", f"%{q}%"]

    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(f"SELECT count(*) AS n FROM files WHERE {where}", params)
            total = cur.fetchone()["n"]

            cur.execute(
                f"""
                SELECT files.id, files.filename, files.display_name, files.ext,
                       files.thumbnail_path, files.render_status, files.is_manifold,
                       files.bbox_x, files.bbox_y, files.bbox_z, files.content_hash,
                       print_log.printed, print_log.rating, print_log.comments
                FROM files
                LEFT JOIN print_log ON print_log.file_id = files.id
                WHERE {where}
                ORDER BY {order_by}
                LIMIT %s OFFSET %s
                """,
                params + order_params + [PAGE_SIZE, offset],
            )
            rows = cur.fetchall()

            # One batch query for just this page's project memberships,
            # rather than N+1 per-file lookups — the whole point is
            # showing when a broad search/filter surfaced several files
            # from the same project, so this needs to run on every
            # search, not just the file detail page's single-file version
            # (get_file_projects).
            file_ids = [r["id"] for r in rows]
            projects_by_file = {file_id: [] for file_id in file_ids}
            if file_ids:
                cur.execute(
                    """
                    SELECT pf.file_id, p.id, p.name
                    FROM project_files pf
                    JOIN projects p ON p.id = pf.project_id
                    WHERE pf.status = 'confirmed' AND pf.file_id = ANY(%s)
                    ORDER BY p.name
                    """,
                    (file_ids,),
                )
                for row in cur.fetchall():
                    projects_by_file[row["file_id"]].append({"id": row["id"], "name": row["name"]})
            for r in rows:
                r["projects"] = projects_by_file[r["id"]]
    return rows, total


def get_file(file_id):
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM files WHERE id = %s", (file_id,))
            return cur.fetchone()


def set_display_name(file_id, display_name):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE files SET display_name = %s WHERE id = %s",
                (display_name or None, file_id),
            )


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
                SELECT f.id, f.filename, f.display_name, f.ext, f.thumbnail_path,
                       f.render_status, f.is_manifold, f.bbox_x, f.bbox_y, f.bbox_z,
                       f.content_hash, print_log.printed, print_log.rating, print_log.comments
                FROM files f
                JOIN project_files pf ON pf.file_id = f.id
                LEFT JOIN print_log ON print_log.file_id = f.id
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


def set_project_name(project_id, name):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE projects SET name = %s WHERE id = %s", (name.strip(), project_id))


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
                "SELECT id, filename, display_name, ext, thumbnail_path, render_status, content_hash FROM files WHERE id = ANY(%s)",
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
                "filename": other["display_name"] or clean_name(other["filename"]),
                "ext": other["ext"],
                "thumbnail_path": other["thumbnail_path"],
                "render_status": other["render_status"],
                "content_hash": other["content_hash"],
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
                SELECT id, filename, display_name, ext FROM files
                WHERE status = 'active' AND id != %s AND (filename ILIKE %s OR display_name ILIKE %s)
                ORDER BY filename LIMIT 10
                """,
                (exclude_file_id, f"%{q}%", f"%{q}%"),
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


def list_suggested_relationships_all():
    """Every suggested relationship across the whole library — for the
    bulk review page, so this doesn't have to be done one file's page at
    a time. Label always uses the "out" (from -> to) phrasing, since both
    files are shown side by side here rather than relative to "this" file
    the way the per-file panel works."""
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT r.id, r.type, r.confidence,
                       f1.id AS from_id, f1.filename AS from_filename, f1.display_name AS from_display_name,
                       f1.ext AS from_ext, f1.thumbnail_path AS from_thumbnail_path,
                       f2.id AS to_id, f2.filename AS to_filename, f2.display_name AS to_display_name,
                       f2.ext AS to_ext, f2.thumbnail_path AS to_thumbnail_path
                FROM relationships r
                JOIN files f1 ON f1.id = r.from_file_id
                JOIN files f2 ON f2.id = r.to_file_id
                WHERE r.status = 'suggested'
                ORDER BY r.created_at DESC
                """
            )
            rows = cur.fetchall()
    for r in rows:
        r["label"] = RELATIONSHIP_LABELS[(r["type"], "out")]
    return rows


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


def list_suggested_project_assignments():
    """Every suggested (project, file) pairing across the whole library —
    for the bulk review page, so this doesn't have to be done one file's
    page at a time."""
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT p.id AS project_id, p.name AS project_name,
                       f.id AS file_id, f.filename, f.display_name, f.ext,
                       f.thumbnail_path, f.render_status
                FROM project_files pf
                JOIN projects p ON p.id = pf.project_id
                JOIN files f ON f.id = pf.file_id
                WHERE pf.status = 'suggested'
                ORDER BY p.name, f.filename
                """
            )
            return cur.fetchall()


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


# ---- print log (printed / rating / notes) ------------------------------------

def get_print_log(file_id):
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM print_log WHERE file_id = %s", (file_id,))
            return cur.fetchone()


def set_print_log(file_id, printed, rating, comments):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO print_log (file_id, printed, rating, comments)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (file_id) DO UPDATE SET
                    printed = EXCLUDED.printed, rating = EXCLUDED.rating, comments = EXCLUDED.comments
                """,
                (file_id, printed, rating, comments or None),
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


# ---- pending zip archives -----------------------------------------------

def list_pending_zips():
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT id, filename, path, size_bytes, error FROM zip_files "
                "WHERE status = 'suggested' ORDER BY created_at"
            )
            return cur.fetchall()


def enqueue_zip_extraction(zip_id):
    with get_connection() as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE zip_files SET status = 'confirmed', error = NULL WHERE id = %s",
                    (zip_id,),
                )
                cur.execute(
                    "INSERT INTO jobs (zip_file_id, job_type, status) VALUES (%s, 'extract_zip', 'queued')",
                    (zip_id,),
                )


def reject_zip(zip_id):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE zip_files SET status = 'rejected' WHERE id = %s", (zip_id,))


def list_rejected_zips():
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT id, filename, path, size_bytes, created_at FROM zip_files "
                "WHERE status = 'rejected' ORDER BY created_at DESC"
            )
            return cur.fetchall()


def unreject_zip(zip_id):
    """Moves a rejected zip back to 'suggested' so it reappears in the
    normal Pending archives review flow — the file itself is untouched
    either way, this only changes whether SPOOL is still asking about it."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE zip_files SET status = 'suggested' WHERE id = %s", (zip_id,))


# ---- sidecar files --------------------------------------------------------

def get_project_sidecars(project_id):
    """Sidecar files (README, preview images, etc.) that live in the same
    folder as this project's confirmed member files — projects have no
    stored folder-path column (Phase 06's known name-matching limitation),
    so this derives folder membership from the paths of files already
    linked to the project."""
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                WITH project_dirs AS (
                    SELECT DISTINCT regexp_replace(f.path, '/[^/]+$', '') AS dir
                    FROM files f
                    JOIN project_files pf ON pf.file_id = f.id
                    WHERE pf.project_id = %s AND pf.status = 'confirmed'
                )
                SELECT s.id, s.filename, s.ext, s.size_bytes, s.thumbnail_path
                FROM sidecar_files s
                JOIN project_dirs d ON regexp_replace(s.path, '/[^/]+$', '') = d.dir
                WHERE s.status = 'active'
                ORDER BY s.filename
                """,
                (project_id,),
            )
            return cur.fetchall()


def get_sidecar(sidecar_id):
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT id, path, filename FROM sidecar_files WHERE id = %s", (sidecar_id,))
            return cur.fetchone()


# ---- duplicate files (identical content_hash) --------------------------------

def list_duplicate_groups():
    """Files sharing an identical content_hash — same hash always means
    same render (rendering is a deterministic function of file bytes), so
    there's no separate 'render similarity' check to make."""
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT content_hash, array_agg(id ORDER BY first_seen_at) AS file_ids
                FROM files
                WHERE status = 'active' AND content_hash IS NOT NULL
                GROUP BY content_hash
                HAVING count(*) > 1
                ORDER BY min(first_seen_at) DESC
                """
            )
            groups_raw = cur.fetchall()
            if not groups_raw:
                return []

            all_ids = [fid for g in groups_raw for fid in g["file_ids"]]
            cur.execute(
                """
                SELECT id, filename, display_name, path, size_bytes, thumbnail_path,
                       render_status, first_seen_at, content_hash
                FROM files WHERE id = ANY(%s)
                """,
                (all_ids,),
            )
            files_by_id = {f["id"]: f for f in cur.fetchall()}

    groups = []
    for g in groups_raw:
        files = [files_by_id[fid] for fid in g["file_ids"] if fid in files_by_id]
        if len(files) > 1:
            groups.append({"content_hash": g["content_hash"], "files": files})
    return groups


def delete_file_record(file_id):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM files WHERE id = %s", (file_id,))
