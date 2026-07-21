import os

from common.text import suggest_clean_project_name


def unique_project_name(cur, name, directory=None, exclude_id=None):
    """Project names should be unique — a second, unrelated real folder
    that happens to produce the same cleaned name (e.g. two different
    "Root" board game kits' "Woodland Alliance" faction folders, a
    generic piece name like "Bed" reused across two different dollhouse
    kits, or two projects' names both cleaning up to the same string via
    suggest_clean_project_name) gets disambiguated with its parent
    folder's name in parentheses instead of silently colliding with an
    existing, unrelated project of the same name. Checked against every
    project regardless of how it was created — a manually-created
    project with the same name is just as real a collision as an
    auto-created one. Falls back to a numeric suffix if there's no
    `directory` to derive a parent-folder qualifier from (a manually
    created project has no source_folder_path), or in the
    practically-never-happens case where even the parent-qualified name
    collides too.

    Shared by the worker (naming a brand-new project at creation time)
    and the API (the bulk project-rename page) — both need the exact
    same guarantee, so this lives in `common` rather than being
    duplicated in each service.

    `exclude_id` excludes a project from the collision check — needed
    when *renaming* an existing project, so it never collides with its
    own current name (which is only actually a problem right up until
    the caller's own UPDATE changes it)."""

    def taken(candidate):
        if exclude_id is not None:
            cur.execute("SELECT 1 FROM projects WHERE lower(name) = lower(%s) AND id != %s", (candidate, exclude_id))
        else:
            cur.execute("SELECT 1 FROM projects WHERE lower(name) = lower(%s)", (candidate,))
        return cur.fetchone() is not None

    if not taken(name):
        return name

    base_candidate = None
    if directory:
        # suggest_clean_project_name, not just clean_name — the qualifier
        # reads inconsistently next to an already-cleaned name otherwise
        # (confirmed live: "Other (ikea-mini-kallax-collection-model_
        # files)" instead of "Other (Ikea Mini Kallax Collection)").
        parent_name = suggest_clean_project_name(os.path.basename(os.path.dirname(directory)))
        base_candidate = f"{name} ({parent_name})"
        if not taken(base_candidate):
            return base_candidate

    suffix = 2
    while True:
        candidate = f"{base_candidate} ({suffix})" if base_candidate else f"{name} ({suffix})"
        if not taken(candidate):
            return candidate
        suffix += 1
