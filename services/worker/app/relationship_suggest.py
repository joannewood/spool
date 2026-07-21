import os
import re

from psycopg.rows import dict_row

from common.config import MODEL_EXTENSIONS
from common.text import clean_name

STEP_EXTS = (".step", ".stp")

# "widget_v2", "widget-v12", "widget v3" -> base "widget", version 2/12/3.
# Same-extension only — a version bump is meaningful within one file format.
_VERSION_RE = re.compile(r"^(?P<base>.+?)[ _-]v(?P<ver>\d+)$", re.IGNORECASE)

# Folder names too generic to serve as a project's identity on their own —
# "<ProjectName>/files/widget.stl" is a common download/export convention,
# and naming the project "files" after that container folder means every
# unrelated project using the same convention collides into one project.
# A per-format export folder ("STL", "3MF Files", "STL", "STP"...) is the
# exact same problem, just spelled with the format name instead of the word
# "files" — confirmed live: 36 real projects named nothing but a bare
# format (7x "STL Files", 7x "STL", 7x "3MF Files", 5x "3MF", 4x
# "STEP Files"...), each a genuinely different kit's export folder but all
# sharing the same unhelpful name. Derived from MODEL_EXTENSIONS rather
# than hardcoded so a new format added there is automatically covered here
# too, the same reasoning as the ALL_EXTENSIONS/MODEL_EXTENSIONS assert-
# sync gotcha elsewhere in this app. "cad"/"cad files" isn't a file
# extension but is the exact same bare-descriptor pattern — confirmed
# live: two unrelated kits ("cardboard-gridfinity-bins",
# "cardboard-skadis-bins") each have their own "cad_files" subfolder.
# Both singular and plural ("3mf file" and "3mf files") count — a folder
# with just one file inside is exactly as generic a container as one
# with several, so there's no reason the singular form should slip
# through.
_GENERIC_CONTAINER_NAMES = {"files", "file", "cad", "cad file", "cad files"} | {
    ext.lstrip(".") for ext in MODEL_EXTENSIONS
} | {f"{ext.lstrip('.')} file" for ext in MODEL_EXTENSIONS} | {f"{ext.lstrip('.')} files" for ext in MODEL_EXTENSIONS}
# The multi-word entries above ("3mf files", "cad files"...) assume a
# space between the two words, but a real folder just as often spells it
# "3mf_files" or "3MF-Files" — normalize runs of underscore/hyphen to a
# single space before checking membership, so all three spellings match
# the same set entry (confirmed live: a real "cad_files" folder used the
# underscore form and was missed until this normalization was added).
_SEPARATOR_TO_SPACE_RE = re.compile(r"[_\-]+")


def _stem(filename):
    return os.path.splitext(filename)[0]


def _unique_project_name(cur, name, directory):
    """Project names should be unique — a second, unrelated real folder
    that happens to produce the same cleaned name (e.g. two different
    "Root" board game kits' "Woodland Alliance" faction folders, or a
    generic piece name like "Bed" reused across two different dollhouse
    kits) gets disambiguated with its parent folder's name in parentheses
    instead of silently colliding with an existing, unrelated project of
    the same name. Confirmed live this resolves every real duplicate name
    in the library as of writing (25 distinct names, all disambiguated by
    their immediate parent folder alone). Checked against every project
    regardless of how it was created — a manually-created project with
    the same name is just as real a collision as an auto-created one.
    Falls back to a numeric suffix in the practically-never-happens case
    where even the disambiguated name collides too."""
    cur.execute("SELECT 1 FROM projects WHERE lower(name) = lower(%s)", (name,))
    if cur.fetchone() is None:
        return name
    parent_name = clean_name(os.path.basename(os.path.dirname(directory)))
    candidate = f"{name} ({parent_name})"
    suffix = 2
    while True:
        cur.execute("SELECT 1 FROM projects WHERE lower(name) = lower(%s)", (candidate,))
        if cur.fetchone() is None:
            return candidate
        candidate = f"{name} ({parent_name}) ({suffix})"
        suffix += 1


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

    Matching is by the folder's real, absolute path (`projects.
    source_folder_path`), not by name — two unrelated leaf folders that
    happen to share a name (e.g. two different "misc" dumps) each get
    their own project instead of silently merging into one. A project
    created any other way (the manual "+ new project" form) has a NULL
    `source_folder_path`, so it's never a candidate for this matching —
    only projects this function itself created can be reused by it. This
    also means renaming an auto-created project later (the pencil-edit
    UI) doesn't break future matching for that folder, since the lookup
    key is the path, not whatever the name currently is.

    Sibling detection stays scoped to the file's actual immediate
    directory even when that directory's name is too generic to use as
    the project's identity (see `_GENERIC_CONTAINER_NAMES`) — the path
    used for matching/creating the project falls back to the parent
    folder in that case too, so "<ProjectName>/files/widget.stl" still
    groups with its real siblings in that same `files` folder, just under
    a project keyed to the "<ProjectName>" folder and named after it
    instead of "files".
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

    match_directory = directory
    folder_name = os.path.basename(directory)
    if _SEPARATOR_TO_SPACE_RE.sub(" ", folder_name).lower() in _GENERIC_CONTAINER_NAMES:
        parent_directory = os.path.dirname(directory)
        if os.path.normpath(parent_directory) != os.path.normpath(root.host_path):
            match_directory = parent_directory
            folder_name = os.path.basename(parent_directory)
        # else: the generic-named folder sits directly in the watched root,
        # so there's no more-meaningful parent to fall back to — keep it.
    match_directory = os.path.normpath(match_directory)
    folder_name = clean_name(folder_name)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT id FROM projects WHERE source_folder_path = %s",
            (match_directory,),
        )
        row = cur.fetchone()
        project_id = row["id"] if row else None
        if project_id is None:
            unique_name = _unique_project_name(cur, folder_name, match_directory)
            cur.execute(
                "INSERT INTO projects (name, source_folder_path) VALUES (%s, %s) RETURNING id",
                (unique_name, match_directory),
            )
            project_id = cur.fetchone()["id"]

        for sibling in siblings:
            cur.execute(
                """
                INSERT INTO project_files (project_id, file_id, status) VALUES (%s, %s, 'suggested')
                ON CONFLICT (project_id, file_id) DO NOTHING
                """,
                (project_id, sibling["id"]),
            )
