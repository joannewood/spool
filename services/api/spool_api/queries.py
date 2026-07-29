import os
import re

from psycopg.rows import dict_row

from common.db import get_connection
from common.project_naming import unique_project_name
from common.text import clean_name, suggest_clean_project_name

# Independently re-reads the same env var (with the same fallback) that
# main.py and common/ingest.py already each define their own copy of,
# rather than importing main.py's THUMBNAILS_DIR here — main.py already
# imports this module, so the reverse import would be circular. Same
# already-established pattern as common/ingest.py's own copy.
THUMBNAILS_DIR = os.environ.get("THUMBNAILS_DIR", "/data/thumbnails")

PAGE_SIZE = 60
# The bulk-review admin pages (suggested projects/relationships, duplicates,
# pending archives) render every row on one page and their "select all" +
# bulk-accept forms submit every visible row in one POST — fine at the
# handful-of-rows scale they were built/tested against, but a real library
# can accumulate thousands of suggestions (confirmed live: 6,246 suggested
# project assignments from one large bulk import made both the page itself
# slow to render and "Accept selected" agonizingly slow, since
# common.db.get_connection() opens a brand-new, unpooled Postgres
# connection for every single row it confirms — 6,246 sequential fresh
# connections, not one bulk statement). Paginating bounds both problems at
# once: a page only ever renders/submits at most this many rows. Once the
# bulk-accept routes batch onto one connection per request (see
# confirm_file_projects_bulk et al.) the connection-count problem is fixed
# regardless of page size, so the page-size *selector* (100/200/500/1000/
# all) is offered mainly to bound how many rows get rendered/submitted at
# once, not because bigger pages are dangerous anymore — 100 stays the
# default. "all" (a string, not a number — every list_* function below
# checks for it explicitly) skips LIMIT/OFFSET entirely; safe now that a
# single-connection bulk-confirm no longer scales with row count, but
# still opt-in rather than the default, since rendering thousands of
# table rows in one response is still real work for the browser.
BULK_REVIEW_PAGE_SIZES = [100, 200, 500, 1000, "all"]
BULK_REVIEW_PAGE_SIZE_DEFAULT = BULK_REVIEW_PAGE_SIZES[0]


def _limit_offset(page, page_size):
    """(sql_fragment, params) for a LIMIT/OFFSET clause, shared by every
    paginated bulk-review list function — empty string/no params when
    page_size is the "all" sentinel, so a query can always interpolate
    this fragment and append these params regardless of whether
    pagination is actually being applied."""
    if page_size == "all":
        return "", ()
    return "LIMIT %s OFFSET %s", (page_size, (page - 1) * page_size)


def count_pending_zips():
    """Cheap COUNT-only query for the admin homepage's summary link — the
    full paginated list_pending_zips() would also work (it returns a total
    alongside its page of rows) but fetching a page of rows just to read
    that total is wasted work for a page that's loaded often and only
    ever wants the number."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM zip_files WHERE status = 'suggested'")
            return cur.fetchone()[0]


def count_duplicate_groups():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT count(*) FROM (
                    SELECT 1 FROM files
                    WHERE status = 'active' AND content_hash IS NOT NULL
                    GROUP BY content_hash HAVING count(*) > 1
                ) g
                """
            )
            return cur.fetchone()[0]


def count_suggested_project_assignments():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM project_files WHERE status = 'suggested'")
            return cur.fetchone()[0]


def count_suggested_relationships():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM relationships WHERE status = 'suggested'")
            return cur.fetchone()[0]


def _attach_project_memberships(cur, rows):
    """Attaches each row's confirmed project memberships as row['projects']
    — one batch query keyed off this result set's file ids, not a
    per-file lookup (get_file_projects is the right shape for a single
    file's own page, the wrong shape for a whole grid of results). Shared
    by every place that renders a grid of file cards (search_files,
    get_project_files) so they show project association identically
    rather than each growing its own slightly-different version."""
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


def _attach_render_errors(cur, rows):
    """Attaches the most recent failed render job's error text as
    row['render_error'] for any row with render_status == 'failed' — the
    card placeholder shows a short category derived from this (see
    filters.py::render_error_label) instead of the bare word "failed",
    plus the raw text as a hover tooltip. Only queries file ids that are
    actually failed, since most rows in a healthy library never need
    this. Shared by search_files/get_project_files, same reasoning as
    _attach_project_memberships."""
    failed_ids = [r["id"] for r in rows if r.get("render_status") == "failed"]
    errors_by_file = {}
    if failed_ids:
        cur.execute(
            """
            SELECT DISTINCT ON (file_id) file_id, error
            FROM jobs
            WHERE file_id = ANY(%s) AND job_type IN ('render', 'render_step') AND status = 'failed'
            ORDER BY file_id, completed_at DESC NULLS LAST, id DESC
            """,
            (failed_ids,),
        )
        for row in cur.fetchall():
            errors_by_file[row["file_id"]] = row["error"]
    for r in rows:
        r["render_error"] = errors_by_file.get(r["id"])


def get_latest_render_error(file_id):
    """Single-file equivalent of _attach_render_errors, for the file
    detail page (which fetches one row at a time, not a batch)."""
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT error FROM jobs
                WHERE file_id = %s AND job_type IN ('render', 'render_step') AND status = 'failed'
                ORDER BY completed_at DESC NULLS LAST, id DESC
                LIMIT 1
                """,
                (file_id,),
            )
            row = cur.fetchone()
            return row["error"] if row else None


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

# "_"/"-" stand in for a space in most downloaded filenames (a
# Thingiverse/Printables convention, same one common.text.clean_name/
# suggest_clean_project_name already work around for display) — searching
# "cake stand" should still find "cake_stand.stl", not just "cake stand.stl"
# literally. Applied to both the search term (in Python, once per query)
# and every text column it's compared against (in SQL, via _normalized
# wrapping the column expression) so a hyphen/underscore/space anywhere on
# either side of the match are all treated as equivalent.
_SEPARATOR_RUN_RE = re.compile(r"[-_]+")


def _normalize_search_term(q):
    return _SEPARATOR_RUN_RE.sub(" ", q)


def _normalized(column_expr):
    return f"regexp_replace({column_expr}, '[-_]+', ' ', 'g')"

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
        q_normalized = _normalize_search_term(q)
        q_conditions = [
            f"""(
                {_normalized('filename')} ILIKE %s OR {_normalized('display_name')} ILIKE %s OR id IN (
                    SELECT file_id FROM print_metadata
                    WHERE {_normalized('material')} ILIKE %s OR {_normalized('printer_profile')} ILIKE %s
                       OR {_normalized('slicer')} ILIKE %s OR {_normalized('notes')} ILIKE %s
                ) OR id IN (
                    SELECT file_id FROM print_log WHERE {_normalized('comments')} ILIKE %s
                )
            )"""
        ]
        q_params = [f"%{q_normalized}%"] * 7

        # Structured metadata matching (e.g. "0.2mm nozzle") works off
        # keyword presence in the raw query, not a substring match against
        # a column — separator normalization doesn't apply to it.
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
        name_expr = _normalized("COALESCE(display_name, filename)")
        order_by = f"""
            CASE
                WHEN {name_expr} ILIKE %s THEN 0
                WHEN {name_expr} ILIKE %s THEN 1
                WHEN {name_expr} ILIKE %s THEN 2
                ELSE 3
            END,
            {order_by}
        """
        order_params = [q_normalized, f"{q_normalized}%", f"%{q_normalized}%"]

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
            _attach_project_memberships(cur, rows)
            _attach_render_errors(cur, rows)
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


def _get_project_files_by_status(project_id, status):
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
                WHERE pf.project_id = %s AND pf.status = %s
                ORDER BY f.filename
                """,
                (project_id, status),
            )
            rows = cur.fetchall()
            # Same file-card component as the library grid (see
            # _attach_project_memberships) — a file can belong to more
            # than one project, so this page should be able to show that
            # too, not just assume "none, we're already on its project."
            _attach_project_memberships(cur, rows)
            _attach_render_errors(cur, rows)
            return rows


def get_project_files(project_id):
    return _get_project_files_by_status(project_id, "confirmed")


def get_project_suggested_files(project_id):
    """Files the worker's folder-grouping heuristic proposed for this
    project but nobody has confirmed or rejected yet — shown in their own
    section on the project page (see project_detail.html) so a suggestion
    doesn't require navigating to the file's own detail page to review."""
    return _get_project_files_by_status(project_id, "suggested")


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


def count_projects_needing_name_cleanup():
    _, total = list_projects_needing_name_cleanup(page_size="all")
    return total


def list_projects_needing_name_cleanup(page=1, page_size=BULK_REVIEW_PAGE_SIZE_DEFAULT):
    """Every project whose name suggest_clean_project_name() would actually
    change, for the bulk-rename review page — most project names come
    straight from a downloaded kit's own folder name (hyphens/underscores,
    a "model_files" container suffix, a long asset id), which is exactly
    what that heuristic targets. The suggestion is computed in Python, not
    SQL, so filtering/pagination happens here rather than in the query —
    fine at this app's scale (a couple thousand projects, one cheap query)."""
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT id, name FROM projects ORDER BY name")
            rows = cur.fetchall()
    suggestions = [
        {"id": row["id"], "name": row["name"], "suggested_name": suggested}
        for row in rows
        for suggested in [suggest_clean_project_name(row["name"])]
        if suggested and suggested != row["name"]
    ]
    total = len(suggestions)
    if page_size == "all":
        return suggestions, total
    start = (page - 1) * page_size
    return suggestions[start : start + page_size], total


def rename_projects_bulk(renames):
    """`renames` is a list of (project_id, new_name) pairs — one connection
    for the whole batch, same reasoning as confirm_file_projects_bulk. A
    blank/whitespace-only new_name is a silent no-op per row (mirrors
    set_project_name's own boundary-only-validation style) rather than a
    hard failure for the whole batch.

    Runs every new name through unique_project_name — confirmed live this
    was a real gap: two different projects can clean up to the identical
    suggested name (e.g. the same kit's "-model_files"/"-print_files"
    folder pair, both cleaning to the same string), and this function
    previously just set the name with no collision check at all, able to
    create two projects with the exact same name (there's no database
    constraint preventing it either)."""
    if not renames:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            for project_id, new_name in renames:
                new_name = new_name.strip()
                if not new_name:
                    continue
                cur.execute("SELECT source_folder_path FROM projects WHERE id = %s", (project_id,))
                row = cur.fetchone()
                directory = row[0] if row else None
                unique_name = unique_project_name(cur, new_name, directory=directory, exclude_id=project_id)
                cur.execute("UPDATE projects SET name = %s WHERE id = %s", (unique_name, project_id))


def rename_all_projects_needing_cleanup():
    """Applies suggest_clean_project_name's suggestion to *every* project
    that needs it, in one server-side action — no per-row id list for the
    client to render/submit at all (same reasoning as confirm_all_
    suggested_project_assignments). Disambiguates through the same
    unique_project_name path rename_projects_bulk uses, which matters
    more here than anywhere else: confirmed live, 10 of the current
    cleanup suggestions collide pairwise (the same kit's "-model_files"/
    "-print_files" folders both cleaning to the same string), so blindly
    accepting everything without this would immediately create duplicate
    project names."""
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT id, name, source_folder_path FROM projects ORDER BY name")
            rows = cur.fetchall()
            for row in rows:
                suggested = suggest_clean_project_name(row["name"])
                if not suggested or suggested == row["name"]:
                    continue
                unique_name = unique_project_name(cur, suggested, directory=row["source_folder_path"], exclude_id=row["id"])
                cur.execute("UPDATE projects SET name = %s WHERE id = %s", (unique_name, row["id"]))


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


def _delete_project_if_empty_and_auto_created(cur, project_id):
    """A project auto-created by suggest_folder_project (source_folder_path
    NOT NULL) that's lost its last project_files row — via a manual
    removal here, or via delete_files_bulk cascading one away — is dead
    weight: nothing links to it and nothing will ever re-suggest it back
    (matching by source_folder_path means a *new* file discovered in that
    same folder later would just recreate an equivalent row anyway, no
    suggestion is lost by removing the empty shell). Confirmed live this
    was already happening silently: 349 real orphaned projects had
    accumulated, mostly from duplicate-file cleanup deleting the only
    file in a project created for what turned out to be a duplicate
    download's folder. A manually-created project (source_folder_path
    NULL) is deliberately never auto-deleted this way, even if empty —
    the user made it on purpose and might want it waiting for files."""
    cur.execute(
        """
        DELETE FROM projects
        WHERE id = %s AND source_folder_path IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM project_files WHERE project_id = %s)
        """,
        (project_id, project_id),
    )


def remove_file_from_project(file_id, project_id):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM project_files WHERE file_id = %s AND project_id = %s", (file_id, project_id))
            _delete_project_if_empty_and_auto_created(cur, project_id)


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
    q_normalized = _normalize_search_term(q)
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                SELECT id, filename, display_name, ext FROM files
                WHERE status = 'active' AND id != %s
                  AND ({_normalized('filename')} ILIKE %s OR {_normalized('display_name')} ILIKE %s)
                ORDER BY filename LIMIT 10
                """,
                (exclude_file_id, f"%{q_normalized}%", f"%{q_normalized}%"),
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


def confirm_relationships_bulk(rel_ids):
    """Same effect as calling confirm_relationship once per id, but one
    connection for the whole batch — see confirm_file_projects_bulk's
    docstring for why that matters at scale."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            for rel_id in rel_ids:
                cur.execute("UPDATE relationships SET status = 'confirmed' WHERE id = %s", (rel_id,))


def confirm_all_suggested_relationships():
    """Same reasoning as confirm_all_suggested_project_assignments — one
    plain SQL UPDATE, no per-row id list for the client to render/submit
    at all."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE relationships SET status = 'confirmed' WHERE status = 'suggested'")


def list_suggested_relationships_all(page=1, page_size=BULK_REVIEW_PAGE_SIZE_DEFAULT):
    """Every suggested relationship across the whole library — for the
    bulk review page, so this doesn't have to be done one file's page at
    a time. Label always uses the "out" (from -> to) phrasing, since both
    files are shown side by side here rather than relative to "this" file
    the way the per-file panel works. Paginated for the same reason as
    list_suggested_project_assignments. Returns (rows, total)."""
    limit_sql, limit_params = _limit_offset(page, page_size)
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT count(*) AS n FROM relationships WHERE status = 'suggested'")
            total = cur.fetchone()["n"]
            cur.execute(
                f"""
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
                {limit_sql}
                """,
                limit_params,
            )
            rows = cur.fetchall()
    for r in rows:
        r["label"] = RELATIONSHIP_LABELS[(r["type"], "out")]
    return rows, total


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


def confirm_file_projects_bulk(pairs):
    """Same effect as calling confirm_file_project once per pair, but one
    connection for the *whole* batch — get_connection() opens a brand-new,
    unpooled Postgres connection every call, and doing that per row is
    exactly what made bulk-accepting thousands of suggestions painfully
    slow (confirmed live: 6,246 real suggested rows, each needing its own
    fresh connect/auth round-trip). `pairs` is a list of (file_id,
    project_id) tuples."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            for file_id, project_id in pairs:
                cur.execute(
                    "UPDATE project_files SET status = 'confirmed' WHERE file_id = %s AND project_id = %s",
                    (file_id, project_id),
                )


def confirm_all_suggested_project_assignments():
    """"Confirm everything" as one plain SQL UPDATE, no per-row id list
    involved at all — the page-based bulk-select flow (confirm_file_
    projects_bulk) requires the browser to actually render every row's
    checkbox/hidden fields and submit all of them back in one POST body,
    which for a genuinely large suggestion count (confirmed live: 9,720
    real rows) is exactly what brought the whole app down while trying to
    do this from a phone. This needs the client to send nothing but the
    button click itself."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE project_files SET status = 'confirmed' WHERE status = 'suggested'")


def list_suggested_project_assignments(page=1, page_size=BULK_REVIEW_PAGE_SIZE_DEFAULT):
    """Every suggested (project, file) pairing across the whole library —
    for the bulk review page, so this doesn't have to be done one file's
    page at a time. Paginated since a real library can accumulate
    thousands of these from one large import — both rendering all of them
    at once and the "select all" + bulk-accept flow submitting all of
    them at once become impractically slow well before that scale.
    Returns (rows, total), same shape as search_files."""
    limit_sql, limit_params = _limit_offset(page, page_size)
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT count(*) AS n FROM project_files WHERE status = 'suggested'")
            total = cur.fetchone()["n"]
            cur.execute(
                f"""
                SELECT p.id AS project_id, p.name AS project_name,
                       f.id AS file_id, f.filename, f.display_name, f.ext,
                       f.thumbnail_path, f.render_status
                FROM project_files pf
                JOIN projects p ON p.id = pf.project_id
                JOIN files f ON f.id = pf.file_id
                WHERE pf.status = 'suggested'
                ORDER BY p.name, f.filename
                {limit_sql}
                """,
                limit_params,
            )
            return cur.fetchall(), total


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


# ---- processing status dashboard -------------------------------------------
# Backs /admin/status — a live view of the ingestion pipeline (job queue,
# what's running right now, recent activity, per-root progress) built after
# a session of manually re-deriving this exact picture via ad hoc `psql`
# queries and `docker compose logs` while chasing a real incident (a worker
# crash-loop, then a large bulk-import backlog). Same data, just surfaced in
# the app itself instead of typed out fresh each time.

def get_job_queue_summary():
    """job_type x status counts for the two *live* statuses only (queued,
    running) — jobs rows are never deleted once done/failed (only ever
    CASCADEd away if their file/zip is later deleted), so a done/failed
    count here would be an ever-growing lifetime total, not a snapshot of
    current queue state, and isn't actually useful on a live dashboard
    (confirmed via direct user feedback: the numbers "don't make sense"
    for exactly this reason). Recent activity (get_recent_job_activity)
    is the right place to look at done/failed jobs, since it shows the
    actual target/error per job rather than a bare cumulative count."""
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT job_type, status, count(*) AS n
                FROM jobs
                WHERE status IN ('queued', 'running')
                GROUP BY job_type, status
                ORDER BY job_type, status
                """
            )
            return cur.fetchall()


def get_running_jobs():
    """Job(s) currently claimed (status='running') — normally 0 or 1 per
    lane (worker/worker-step each process one job at a time), but not
    assumed to be exactly one: a job orphaned by a crash sits at 'running'
    until the next startup's requeue_orphaned_jobs runs, so more than one
    showing here (or one stuck for a long time — see started_at) is itself
    a useful signal, not just "what's active right now."""
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT j.id, j.job_type, j.created_at,
                       COALESCE(f.filename, z.filename) AS target_name
                FROM jobs j
                LEFT JOIN files f ON f.id = j.file_id
                LEFT JOIN zip_files z ON z.id = j.zip_file_id
                WHERE j.status = 'running'
                ORDER BY j.created_at
                """
            )
            return cur.fetchall()


def get_recent_job_activity(page=1, page_size=BULK_REVIEW_PAGE_SIZE_DEFAULT, q="", status="", job_type=""):
    """Most recently finished jobs (done or failed), newest first, with a
    human-readable target name and the raw error text for failures — the
    live "what just happened" feed. `q` matches against the target's
    filename (ILIKE substring, same convention as the main library
    search); `status`/`job_type` narrow to an exact value when set,
    otherwise every done/failed job is eligible — this is the filtering
    the /admin/status page's search bar drives. Paginated the same way as
    the other bulk-review lists (page/page_size, `count(*) OVER()` for the
    total) — this feed grows unbounded over a library's lifetime, so a
    fixed `limit=100` with no way to look further back doesn't scale."""
    conditions = ["j.status IN ('done', 'failed')"]
    params = []
    if status:
        conditions = ["j.status = %s"]
        params.append(status)
    if job_type:
        conditions.append("j.job_type = %s")
        params.append(job_type)
    if q:
        conditions.append("COALESCE(f.filename, z.filename) ILIKE %s")
        params.append(f"%{q}%")
    where = " AND ".join(conditions)
    limit_sql, limit_params = _limit_offset(page, page_size)

    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                SELECT j.id, j.job_type, j.status, j.error, j.completed_at,
                       COALESCE(f.filename, z.filename) AS target_name,
                       count(*) OVER() AS total_count
                FROM jobs j
                LEFT JOIN files f ON f.id = j.file_id
                LEFT JOIN zip_files z ON z.id = j.zip_file_id
                WHERE {where}
                ORDER BY j.completed_at DESC NULLS LAST, j.id DESC
                {limit_sql}
                """,
                (*params, *limit_params),
            )
            rows = cur.fetchall()
            total = rows[0]["total_count"] if rows else 0
            return rows, total


def get_ingestion_totals():
    """Library-wide counts across the hash/render pipeline — the same
    numbers checked by hand via `SELECT count(*) FROM files WHERE
    content_hash IS NULL` etc. during the bulk-import incident."""
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT
                    count(*) AS total_files,
                    count(*) FILTER (WHERE content_hash IS NULL) AS unhashed,
                    count(*) FILTER (WHERE render_status = 'pending') AS render_pending,
                    count(*) FILTER (WHERE render_status = 'done') AS render_done,
                    count(*) FILTER (WHERE render_status = 'failed') AS render_failed
                FROM files
                WHERE status = 'active'
                """
            )
            return cur.fetchone()


# ---- pending zip archives -----------------------------------------------

def list_pending_zips(page=1, page_size=BULK_REVIEW_PAGE_SIZE_DEFAULT):
    """Paginated for consistency with the other bulk-review pages, even
    though pending archives rarely reach the scale that made this matter
    for suggested projects — see BULK_REVIEW_PAGE_SIZES' comment. Returns
    (rows, total)."""
    limit_sql, limit_params = _limit_offset(page, page_size)
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT count(*) AS n FROM zip_files WHERE status = 'suggested'")
            total = cur.fetchone()["n"]
            cur.execute(
                f"SELECT id, filename, path, size_bytes, error FROM zip_files "
                f"WHERE status = 'suggested' ORDER BY created_at {limit_sql}",
                limit_params,
            )
            return cur.fetchall(), total


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


def enqueue_zip_extractions_bulk(zip_ids):
    """Same effect as calling enqueue_zip_extraction once per id, but one
    connection for the whole batch — see confirm_file_projects_bulk's
    docstring for why that matters at scale."""
    with get_connection() as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                for zip_id in zip_ids:
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

# Same value host-helper's own ALLOWED_DELETE_ROOTS exclusion reads (see
# host-helper/host_helper.py) — read once at import time, same convention
# already used for THUMBNAILS_DIR elsewhere in this file.
_LIBRARY_HOST_PATH = os.environ.get("LIBRARY_HOST_PATH", "")


def _is_undeletable_path(path):
    """True if `path` falls under the read-only Library root, mirroring
    host-helper's own delete-allowlist exclusion — lets the duplicate-
    files admin page know a copy can't be deleted *before* offering to
    delete it, rather than only finding out when host-helper rejects the
    request. Never raises on a malformed/relative path (real `files.path`
    rows are always absolute, but this guards against the empty-string
    "no Library configured" case and any future surprise)."""
    if not _LIBRARY_HOST_PATH:
        return False
    try:
        return os.path.commonpath([path, _LIBRARY_HOST_PATH]) == os.path.normpath(_LIBRARY_HOST_PATH)
    except ValueError:
        return False


def list_duplicate_groups(page=1, page_size=BULK_REVIEW_PAGE_SIZE_DEFAULT):
    """Files sharing an identical content_hash — same hash always means
    same render (rendering is a deterministic function of file bytes), so
    there's no separate 'render similarity' check to make. Paginated by
    *group* (not by individual file row), for the same reason as the
    other bulk-review pages. `count(*) OVER()` gets the total group count
    in the same query as the page of groups, rather than a separate
    COUNT(*) round trip. Returns (groups, total).

    Each file gets `undeletable` (in the read-only Library root) and
    `delete_default` (should this copy be pre-selected for deletion)
    flags — a Library copy is never `delete_default`, since deletion
    there would just fail anyway (see host_helper.py's
    ALLOWED_DELETE_ROOTS). Three cases per group: no Library copy at all
    -> original rule, keep the oldest and delete every other copy; at
    least one Library copy -> it's the forced "keeper" (nothing else can
    make that choice), so *every* deletable copy defaults to selected,
    regardless of age, leaving just the Library copy/copies surviving;
    every copy is in Library -> nothing is touchable, `all_undeletable =
    True` on the group so the UI can say so plainly instead of offering
    a doomed delete."""
    limit_sql, limit_params = _limit_offset(page, page_size)
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                SELECT content_hash, array_agg(id ORDER BY first_seen_at) AS file_ids,
                       count(*) OVER() AS total_groups
                FROM files
                WHERE status = 'active' AND content_hash IS NOT NULL
                GROUP BY content_hash
                HAVING count(*) > 1
                ORDER BY min(first_seen_at) DESC
                {limit_sql}
                """,
                limit_params,
            )
            groups_raw = cur.fetchall()
            total = groups_raw[0]["total_groups"] if groups_raw else 0
            if not groups_raw:
                return [], total

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
        # file_ids is already oldest-first (array_agg ORDER BY first_seen_at).
        files = [files_by_id[fid] for fid in g["file_ids"] if fid in files_by_id]
        if len(files) <= 1:
            continue
        for f in files:
            f["undeletable"] = _is_undeletable_path(f["path"])
        deletable = [f for f in files if not f["undeletable"]]
        if not deletable:
            # Every copy is in Library — nothing here is touchable at all.
            for f in files:
                f["delete_default"] = False
        elif len(deletable) == len(files):
            # No Library copy in this group — original rule: keep the
            # oldest, delete every other copy (files is oldest-first).
            keep_id = files[0]["id"]
            for f in files:
                f["delete_default"] = f["id"] != keep_id
        else:
            # At least one Library copy exists — it's the forced
            # "keeper" (nothing else can make that choice), so every
            # deletable copy is redundant and safe to remove, regardless
            # of age. Leaves exactly the Library copy/copies surviving,
            # same "down to one true copy" goal as the no-Library case.
            for f in files:
                f["delete_default"] = not f["undeletable"]
        groups.append({
            "content_hash": g["content_hash"],
            "files": files,
            "all_undeletable": not deletable,
        })
    return groups, total


def has_deletable_duplicate():
    """Cheap existence check for whether "Delete all extra copies"
    (delete_all_duplicates route — always operates across every group,
    not just the current page) would actually do anything. Lets the
    admin page hide that button entirely when every duplicate group
    happens to be all-Library-copies (list_duplicate_groups' all_undeletable
    case) instead of showing an active-looking button that's a guaranteed
    no-op. Only fetches paths, not the full thumbnail/filename/etc. join
    list_duplicate_groups does, since this only needs a yes/no answer."""
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT array_agg(path) AS paths
                FROM files
                WHERE status = 'active' AND content_hash IS NOT NULL
                GROUP BY content_hash
                HAVING count(*) > 1
                """
            )
            for row in cur.fetchall():
                if any(not _is_undeletable_path(p) for p in row["paths"]):
                    return True
    return False


def get_files_bulk(file_ids):
    """Same shape as calling get_file once per id, but one connection for
    the whole batch — see confirm_file_projects_bulk's docstring for why
    that matters at scale. Returns a dict keyed by id (only ids that
    actually still exist) rather than a list, so a caller doing per-id
    work afterward (e.g. a host-helper delete request per file — that
    part genuinely can't be batched, host-helper's API is one file at a
    time) can look each one up directly."""
    if not file_ids:
        return {}
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM files WHERE id = ANY(%s)", (file_ids,))
            return {row["id"]: row for row in cur.fetchall()}


def delete_files_bulk(file_ids):
    """Deletes every one of these files rows *and* their rendered
    thumbnails, in one connection for the whole batch — the only place a
    files row is ever actually removed (duplicate-file deletion), and
    until this fix never cleaned up the thumbnails it left behind
    (confirmed live: thousands of orphaned thumbnails had accumulated
    over the feature's whole history) nor batched its connections
    (confirmed live: the exact same N-fresh-connections problem already
    fixed for the bulk-review suggestion pages, just not yet triggered
    here since duplicate counts are typically much smaller). The DB
    delete happens first — thumbnail removal is best-effort afterward
    (wrapped so a filesystem hiccup can't undo an otherwise-successful
    delete; a missed thumbnail is just a leftover orphan, recoverable by
    re-sweeping, not a correctness problem).

    Also cleans up any project left with zero files as a result — a
    deleted file was often the sole member of an auto-created project for
    what turned out to be a duplicate download's own folder (confirmed
    live: this exact pattern accounts for the bulk of 349 real orphaned
    empty projects found in the wild). project_files rows CASCADE away
    with the file, so the affected project ids have to be captured
    *before* the delete, not after."""
    if not file_ids:
        return
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT thumbnail_path FROM files WHERE id = ANY(%s)", (file_ids,))
            thumbnail_paths = [row["thumbnail_path"] for row in cur.fetchall() if row["thumbnail_path"]]
            cur.execute("SELECT DISTINCT project_id FROM project_files WHERE file_id = ANY(%s)", (file_ids,))
            affected_project_ids = [row["project_id"] for row in cur.fetchall()]
            cur.execute("DELETE FROM files WHERE id = ANY(%s)", (file_ids,))
            for project_id in affected_project_ids:
                _delete_project_if_empty_and_auto_created(cur, project_id)

    for thumbnail_path in thumbnail_paths:
        try:
            os.remove(os.path.join(THUMBNAILS_DIR, thumbnail_path))
        except OSError:
            pass
