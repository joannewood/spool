import os
from urllib.parse import urlencode

import psycopg
from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import host_helper_client, queries
from .filters import ext_class, format_size

DATABASE_URL = os.environ["DATABASE_URL"]
THUMBNAILS_DIR = os.environ.get("THUMBNAILS_DIR", "/data/thumbnails")
ALL_EXTENSIONS = [".stl", ".3mf", ".step", ".stp", ".svg", ".scad"]
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

app = FastAPI(title="SPOOL API")
app.mount("/static", StaticFiles(directory=os.path.join(APP_DIR, "static")), name="static")
app.mount("/thumbnails", StaticFiles(directory=THUMBNAILS_DIR), name="thumbnails")

templates = Jinja2Templates(directory=os.path.join(APP_DIR, "templates"))
templates.env.filters["filesizeformat"] = format_size
templates.env.filters["ext_class"] = ext_class


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
    sort: str = "newest",
    page: int = 1,
):
    page = max(page, 1)
    if sort not in queries.SORT_CLAUSES:
        sort = "newest"
    files, total = queries.search_files(q, ext, tag, page, sort)
    total_pages = max(1, -(-total // queries.PAGE_SIZE))  # ceil division

    qs_params = (
        ([("q", q)] if q else [])
        + [("ext", e) for e in ext]
        + [("tag", t) for t in tag]
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
def project_detail(request: Request, project_id: int):
    project = queries.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return templates.TemplateResponse(
        request,
        "project_detail.html",
        {
            "project": project,
            "children": queries.get_project_children(project_id),
            "files": queries.get_project_files(project_id),
            "parent": queries.get_project(project["parent_project_id"]) if project["parent_project_id"] else None,
            "sidecars": queries.get_project_sidecars(project_id),
        },
    )


@app.post("/files/{file_id}/projects")
def add_to_project(file_id: int, project_id: int = Form(...)):
    queries.add_file_to_project(file_id, project_id)
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


# ---- admin: watched roots -------------------------------------------------

@app.get("/admin", response_class=HTMLResponse)
def admin(request: Request):
    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "roots": queries.list_watched_roots(),
            "ingest_modes": INGEST_MODES,
            "pending_zips": queries.list_pending_zips(),
        },
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
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/zips/{zip_id}/reject")
def reject_zip(zip_id: int):
    queries.reject_zip(zip_id)
    return RedirectResponse("/admin", status_code=303)


@app.get("/admin/rejected-archives", response_class=HTMLResponse)
def admin_rejected_archives(request: Request):
    return templates.TemplateResponse(
        request, "admin_rejected_archives.html", {"zips": queries.list_rejected_zips()}
    )


@app.post("/admin/zips/{zip_id}/unreject")
def unreject_zip(zip_id: int):
    queries.unreject_zip(zip_id)
    return RedirectResponse("/admin/rejected-archives", status_code=303)


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
