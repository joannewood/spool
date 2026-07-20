import os
from urllib.parse import urlencode

import psycopg
from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from common.config import MODEL_EXTENSIONS

from . import host_helper_client, queries
from .filters import clean_name, ext_class, format_size, render_error_label, thumb_url

DATABASE_URL = os.environ["DATABASE_URL"]
THUMBNAILS_DIR = os.environ.get("THUMBNAILS_DIR", "/data/thumbnails")
# A curated display order (raw mesh formats, then CAD source, then vector/
# parametric source, then sliced output) rather than MODEL_EXTENSIONS' set
# order, which Python doesn't guarantee stable across runs. The assertion
# is the actual fix, not the ordering — this list previously drifted out
# of sync with MODEL_EXTENSIONS silently (gcode/obj support landed in
# common/config.py without anyone remembering this second, separate list
# existed), so two new formats were invisible in the filter panel despite
# being fully ingested/searchable. Now a mismatch fails loudly at import
# time instead of silently under-listing filters again.
ALL_EXTENSIONS = [".stl", ".3mf", ".obj", ".step", ".stp", ".svg", ".scad", ".gcode"]
assert set(ALL_EXTENSIONS) == MODEL_EXTENSIONS, (
    f"ALL_EXTENSIONS {sorted(ALL_EXTENSIONS)} is out of sync with "
    f"common.config.MODEL_EXTENSIONS {sorted(MODEL_EXTENSIONS)}"
)
INGEST_MODES = ["index_in_place", "relocate_to_dropfolder"]
RELATIONSHIP_TYPES = ["derived_from", "new_version_of", "variant_of", "duplicate_of"]
SORT_OPTIONS = [
    ("newest", "Newest first"),
    ("oldest", "Oldest first"),
    ("name_asc", "Name (A-Z)"),
    ("name_desc", "Name (Z-A)"),
    ("size_desc", "Size (largest)"),
    ("size_asc", "Size (smallest)"),
]

APP_DIR = os.path.dirname(__file__)
os.makedirs(THUMBNAILS_DIR, exist_ok=True)


class CachedStaticFiles(StaticFiles):
    """A thumbnail's filename is stable (`{file_id}.png`, overwritten in
    place on re-render), so this is only safe to use behind a cache-buster
    — see filters.py::thumb_url, which appends a ?v=<content_hash> query
    param so a real content change always produces a new URL. Not used
    for the /static mount, since CSS/JS/icons there change during active
    development without any equivalent versioning scheme; caching those
    aggressively would serve stale assets after every deploy."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


app = FastAPI(title="SPOOL API")
app.mount("/static", StaticFiles(directory=os.path.join(APP_DIR, "static")), name="static")
app.mount("/thumbnails", CachedStaticFiles(directory=THUMBNAILS_DIR), name="thumbnails")

templates = Jinja2Templates(directory=os.path.join(APP_DIR, "templates"))
templates.env.filters["filesizeformat"] = format_size
templates.env.filters["ext_class"] = ext_class
templates.env.filters["clean_name"] = clean_name
templates.env.filters["render_error_label"] = render_error_label
templates.env.globals["thumb_url"] = thumb_url


@app.get("/health")
def health():
    try:
        with psycopg.connect(DATABASE_URL, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"database unreachable: {exc}")
    return {"status": "ok", "database": "connected"}


# ---- browse / search --------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    q: str = "",
    ext: list[str] = Query(default=[]),
    tag: list[str] = Query(default=[]),
    rating: list[int] = Query(default=[]),
    printed: str = "",
    material: str = "",
    printer_profile: str = "",
    slicer: str = "",
    sort: str = "newest",
    page: int = 1,
):
    page = max(page, 1)
    if sort not in queries.SORT_CLAUSES:
        sort = "newest"
    if printed not in ("", "yes", "no"):
        printed = ""
    files, total = queries.search_files(
        q, ext, tag, page, sort,
        ratings=rating, printed=printed, material=material, printer_profile=printer_profile, slicer=slicer,
    )
    total_pages = max(1, -(-total // queries.PAGE_SIZE))  # ceil division

    qs_params = (
        ([("q", q)] if q else [])
        + [("ext", e) for e in ext]
        + [("tag", t) for t in tag]
        + [("rating", r) for r in rating]
        + ([("printed", printed)] if printed else [])
        + ([("material", material)] if material else [])
        + ([("printer_profile", printer_profile)] if printer_profile else [])
        + ([("slicer", slicer)] if slicer else [])
        + ([("sort", sort)] if sort != "newest" else [])
    )
    base_qs = urlencode(qs_params)

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "files": files,
            "total": total,
            "q": q,
            "all_extensions": ALL_EXTENSIONS,
            "selected_extensions": set(ext),
            "all_tags": queries.list_all_tags(),
            "selected_tags": set(tag),
            "selected_ratings": set(rating),
            "selected_printed": printed,
            "all_materials": queries.list_print_metadata_values("material"),
            "all_printers": queries.list_print_metadata_values("printer_profile"),
            "all_slicers": queries.list_print_metadata_values("slicer"),
            "selected_material": material,
            "selected_printer": printer_profile,
            "selected_slicer": slicer,
            "sort": sort,
            "sort_options": SORT_OPTIONS,
            "page": page,
            "total_pages": total_pages,
            "base_qs": base_qs,
        },
    )


@app.get("/files/{file_id}", response_class=HTMLResponse)
def file_detail(request: Request, file_id: int):
    file = queries.get_file(file_id)
    if file is None:
        raise HTTPException(status_code=404, detail="file not found")
    return templates.TemplateResponse(
        request,
        "file_detail.html",
        {
            "file": file,
            "render_error": (
                queries.get_latest_render_error(file_id) if file["render_status"] == "failed" else None
            ),
            "tags": queries.get_file_tags(file_id),
            "projects": queries.get_file_projects(file_id),
            "suggested_projects": queries.get_suggested_file_projects(file_id),
            "all_projects": queries.list_projects(),
            "print_metadata": queries.get_print_metadata(file_id),
            "print_log": queries.get_print_log(file_id),
            "relationships": queries.get_file_relationships(file_id),
            "suggested_relationships": queries.get_suggested_relationships(file_id),
            "relationship_types": RELATIONSHIP_TYPES,
            "all_apps": host_helper_client.ALL_APPS,
            "default_app": host_helper_client.default_app_for_ext(file["ext"]),
            "app_icons": host_helper_client.APP_ICONS,
            "open_status": request.query_params.get("open_status", ""),
        },
    )


# ---- display name -----------------------------------------------------------

@app.post("/files/{file_id}/name")
def update_display_name(file_id: int, display_name: str = Form("")):
    queries.set_display_name(file_id, display_name.strip())
    return RedirectResponse(f"/files/{file_id}", status_code=303)


# ---- tags -------------------------------------------------------------------

@app.post("/files/{file_id}/tags")
def add_tag(file_id: int, name: str = Form(...)):
    queries.add_tag_to_file(file_id, name)
    return RedirectResponse(f"/files/{file_id}", status_code=303)


@app.delete("/files/{file_id}/tags/{tag_id}", response_class=HTMLResponse)
def remove_tag(file_id: int, tag_id: int):
    queries.remove_tag_from_file(file_id, tag_id)
    return HTMLResponse("")


# ---- projects -----------------------------------------------------------------

def _build_project_tree(rows):
    by_id = {r["id"]: {**r, "children": []} for r in rows}
    roots = []
    for r in rows:
        node = by_id[r["id"]]
        parent_id = r["parent_project_id"]
        if parent_id and parent_id in by_id:
            by_id[parent_id]["children"].append(node)
        else:
            roots.append(node)
    return roots


@app.get("/projects", response_class=HTMLResponse)
def projects_index(request: Request):
    projects = queries.list_projects()
    return templates.TemplateResponse(
        request, "projects.html", {"projects": projects, "tree": _build_project_tree(projects)}
    )


@app.post("/projects")
def create_project(name: str = Form(...), description: str = Form(""), parent_project_id: str = Form("")):
    parent_id = int(parent_project_id) if parent_project_id else None
    project_id = queries.create_project(name, description, parent_id)
    return RedirectResponse(f"/projects/{project_id}", status_code=303)


@app.get("/projects/{project_id}", response_class=HTMLResponse)
def project_detail(request: Request, project_id: int, open_status: str = ""):
    project = queries.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    files = queries.get_project_files(project_id)
    # The file card shows every confirmed project a file belongs to (same
    # component as the library grid) — but repeating *this* project's own
    # name on every card of its own page is pure noise, not information;
    # only other memberships (a file that's also in a second project) are
    # worth showing here.
    for f in files:
        f["projects"] = [p for p in f["projects"] if p["id"] != project_id]
    return templates.TemplateResponse(
        request,
        "project_detail.html",
        {
            "project": project,
            "children": queries.get_project_children(project_id),
            "files": files,
            "parent": queries.get_project(project["parent_project_id"]) if project["parent_project_id"] else None,
            "sidecars": queries.get_project_sidecars(project_id),
            "open_status": open_status,
        },
    )


@app.post("/projects/{project_id}/name")
def update_project_name(project_id: int, name: str = Form(...)):
    queries.set_project_name(project_id, name)
    return RedirectResponse(f"/projects/{project_id}", status_code=303)


@app.post("/files/{file_id}/projects")
def add_to_project(file_id: int, project_id: str = Form(...), new_project_name: str = Form("")):
    # "+ create new project…" is an option in the same <select> as picking
    # an existing one (see file_detail.html's add-project-toggle) rather
    # than a separate persistent link — creates the project inline instead
    # of navigating away to /projects and back.
    if project_id == "__new__":
        name = new_project_name.strip()
        if name:
            project_id = queries.create_project(name, "", None)
            queries.add_file_to_project(file_id, project_id)
    else:
        queries.add_file_to_project(file_id, int(project_id))
    return RedirectResponse(f"/files/{file_id}", status_code=303)


@app.delete("/files/{file_id}/projects/{project_id}", response_class=HTMLResponse)
def remove_from_project(file_id: int, project_id: int):
    queries.remove_file_from_project(file_id, project_id)
    return HTMLResponse("")


@app.post("/files/{file_id}/projects/{project_id}/confirm")
def confirm_suggested_project(file_id: int, project_id: int):
    queries.confirm_file_project(file_id, project_id)
    return RedirectResponse(f"/files/{file_id}", status_code=303)


@app.post("/files/{file_id}/projects/{project_id}/reject")
def reject_suggested_project(file_id: int, project_id: int):
    queries.reject_file_project(file_id, project_id)
    return RedirectResponse(f"/files/{file_id}", status_code=303)


# ---- relationships --------------------------------------------------------------

@app.get("/files/{file_id}/relationships/search", response_class=HTMLResponse)
def search_relationship_targets(request: Request, file_id: int, q: str = ""):
    results = queries.search_files_for_relationship(q, file_id) if q.strip() else []
    return templates.TemplateResponse(
        request, "_relationship_search_results.html", {"results": results, "q": q}
    )


@app.post("/files/{file_id}/relationships")
def add_relationship(file_id: int, type: str = Form(...), to_file_id: int = Form(...)):
    if type not in RELATIONSHIP_TYPES:
        raise HTTPException(status_code=400, detail="unknown relationship type")
    queries.add_relationship(file_id, to_file_id, type)
    return RedirectResponse(f"/files/{file_id}", status_code=303)


@app.post("/files/{file_id}/relationships/{rel_id}/confirm")
def confirm_relationship(file_id: int, rel_id: int):
    queries.confirm_relationship(rel_id)
    return RedirectResponse(f"/files/{file_id}", status_code=303)


@app.post("/files/{file_id}/relationships/{rel_id}/reject")
def reject_relationship(file_id: int, rel_id: int):
    queries.reject_relationship(rel_id)
    return RedirectResponse(f"/files/{file_id}", status_code=303)


@app.delete("/files/{file_id}/relationships/{rel_id}", response_class=HTMLResponse)
def remove_relationship(file_id: int, rel_id: int):
    queries.remove_relationship(rel_id)
    return HTMLResponse("")


# ---- print metadata -----------------------------------------------------------

@app.post("/files/{file_id}/print-metadata")
def update_print_metadata(
    file_id: int,
    material: str = Form(""),
    printer_profile: str = Form(""),
    slicer: str = Form(""),
    notes: str = Form(""),
):
    queries.set_manual_print_metadata(file_id, material, printer_profile, slicer, notes)
    return RedirectResponse(f"/files/{file_id}", status_code=303)


@app.post("/files/{file_id}/print-log")
def update_print_log(file_id: int, printed: str = Form(""), rating: str = Form(""), comments: str = Form("")):
    queries.set_print_log(file_id, printed == "on", int(rating) if rating else None, comments.strip())
    return RedirectResponse(f"/files/{file_id}", status_code=303)


# ---- open in app (host-helper) ---------------------------------------------

@app.post("/files/{file_id}/open")
def open_file(file_id: int, app: str = Form("")):
    file = queries.get_file(file_id)
    if file is None:
        raise HTTPException(status_code=404, detail="file not found")

    chosen_app = app or host_helper_client.default_app_for_ext(file["ext"])
    if not chosen_app:
        status = f"error:no app mapped for {file['ext']}"
    else:
        ok, error = host_helper_client.request_open(file["path"], chosen_app)
        status = "ok" if ok else f"error:{error}"

    qs = urlencode({"open_status": status})
    return RedirectResponse(f"/files/{file_id}?{qs}", status_code=303)


@app.post("/projects/{project_id}/sidecars/{sidecar_id}/open")
def open_sidecar(project_id: int, sidecar_id: int):
    sidecar = queries.get_sidecar(sidecar_id)
    if sidecar is None:
        raise HTTPException(status_code=404, detail="sidecar file not found")

    # No app argument — sidecars (README/PDF/preview images) aren't CAD
    # files with one obvious app, so host-helper hands off to macOS's own
    # default handler for whatever this file type is.
    ok, error = host_helper_client.request_open(sidecar["path"])
    status = "ok" if ok else f"error:{error}"

    qs = urlencode({"open_status": status})
    return RedirectResponse(f"/projects/{project_id}?{qs}", status_code=303)


# ---- admin: watched roots -------------------------------------------------

@app.get("/admin", response_class=HTMLResponse)
def admin(request: Request):
    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "roots": queries.list_watched_roots(),
            "ingest_modes": INGEST_MODES,
            "pending_zip_count": len(queries.list_pending_zips()),
            "duplicate_count": len(queries.list_duplicate_groups()),
            "suggested_project_count": len(queries.list_suggested_project_assignments()),
            "suggested_relationship_count": len(queries.list_suggested_relationships_all()),
        },
    )


@app.get("/admin/pending-archives", response_class=HTMLResponse)
def admin_pending_archives(request: Request):
    return templates.TemplateResponse(
        request, "admin_pending_archives.html", {"zips": queries.list_pending_zips()}
    )


@app.post("/admin/roots/{root_id}")
def admin_update_root(
    root_id: int,
    label: str = Form(...),
    ingest_mode: str = Form(...),
    active: str = Form(""),
):
    queries.update_watched_root(root_id, label, ingest_mode, active == "on")
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/zips/{zip_id}/confirm")
def confirm_zip(zip_id: int):
    queries.enqueue_zip_extraction(zip_id)
    return RedirectResponse("/admin/pending-archives", status_code=303)


@app.post("/admin/zips/{zip_id}/reject")
def reject_zip(zip_id: int):
    queries.reject_zip(zip_id)
    return RedirectResponse("/admin/pending-archives", status_code=303)


@app.get("/admin/rejected-archives", response_class=HTMLResponse)
def admin_rejected_archives(request: Request):
    return templates.TemplateResponse(
        request, "admin_rejected_archives.html", {"zips": queries.list_rejected_zips()}
    )


@app.post("/admin/zips/{zip_id}/unreject")
def unreject_zip(zip_id: int):
    queries.unreject_zip(zip_id)
    return RedirectResponse("/admin/rejected-archives", status_code=303)


# ---- admin: bulk review of suggestions -------------------------------------

@app.get("/admin/suggested-projects", response_class=HTMLResponse)
def admin_suggested_projects(request: Request):
    return templates.TemplateResponse(
        request,
        "admin_suggested_projects.html",
        {"assignments": queries.list_suggested_project_assignments()},
    )


@app.post("/admin/suggested-projects/{project_id}/{file_id}/confirm")
def admin_confirm_project_assignment(project_id: int, file_id: int):
    queries.confirm_file_project(file_id, project_id)
    return RedirectResponse("/admin/suggested-projects", status_code=303)


@app.post("/admin/suggested-projects/{project_id}/{file_id}/reject")
def admin_reject_project_assignment(project_id: int, file_id: int):
    queries.reject_file_project(file_id, project_id)
    return RedirectResponse("/admin/suggested-projects", status_code=303)


@app.post("/admin/suggested-projects/accept-bulk")
def admin_accept_project_assignments_bulk(pairs: list[str] = Form([])):
    for pair in pairs:
        project_id_str, file_id_str = pair.split(":")
        queries.confirm_file_project(int(file_id_str), int(project_id_str))
    return RedirectResponse("/admin/suggested-projects", status_code=303)


@app.get("/admin/suggested-relationships", response_class=HTMLResponse)
def admin_suggested_relationships(request: Request):
    return templates.TemplateResponse(
        request,
        "admin_suggested_relationships.html",
        {"relationships": queries.list_suggested_relationships_all()},
    )


@app.post("/admin/suggested-relationships/{rel_id}/confirm")
def admin_confirm_relationship(rel_id: int):
    queries.confirm_relationship(rel_id)
    return RedirectResponse("/admin/suggested-relationships", status_code=303)


@app.post("/admin/suggested-relationships/{rel_id}/reject")
def admin_reject_relationship(rel_id: int):
    queries.reject_relationship(rel_id)
    return RedirectResponse("/admin/suggested-relationships", status_code=303)


@app.post("/admin/suggested-relationships/accept-bulk")
def admin_accept_relationships_bulk(rel_ids: list[int] = Form([])):
    for rel_id in rel_ids:
        queries.confirm_relationship(rel_id)
    return RedirectResponse("/admin/suggested-relationships", status_code=303)


# ---- admin: duplicate files ------------------------------------------------

@app.get("/admin/duplicates", response_class=HTMLResponse)
def admin_duplicates(request: Request):
    return templates.TemplateResponse(
        request,
        "admin_duplicates.html",
        {
            "groups": queries.list_duplicate_groups(),
            "delete_errors": request.query_params.get("delete_errors", ""),
        },
    )


@app.post("/admin/duplicates/delete")
def delete_duplicates(file_ids: list[int] = Form([])):
    errors = []
    for file_id in file_ids:
        file = queries.get_file(file_id)
        if file is None:
            continue
        ok, error = host_helper_client.request_delete(file["path"])
        if ok:
            queries.delete_file_record(file_id)
        else:
            errors.append(f"{file['filename']}: {error}")

    qs = urlencode({"delete_errors": "; ".join(errors)}) if errors else ""
    return RedirectResponse(f"/admin/duplicates{'?' + qs if qs else ''}", status_code=303)
