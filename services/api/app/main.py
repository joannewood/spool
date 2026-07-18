import os
from urllib.parse import urlencode

import psycopg
from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import queries
from .filters import format_size

DATABASE_URL = os.environ["DATABASE_URL"]
THUMBNAILS_DIR = os.environ.get("THUMBNAILS_DIR", "/data/thumbnails")
ALL_EXTENSIONS = [".stl", ".3mf", ".step", ".stp"]
INGEST_MODES = ["index_in_place", "relocate_to_dropfolder"]

APP_DIR = os.path.dirname(__file__)
os.makedirs(THUMBNAILS_DIR, exist_ok=True)

app = FastAPI(title="SPOOL API")
app.mount("/static", StaticFiles(directory=os.path.join(APP_DIR, "static")), name="static")
app.mount("/thumbnails", StaticFiles(directory=THUMBNAILS_DIR), name="thumbnails")

templates = Jinja2Templates(directory=os.path.join(APP_DIR, "templates"))
templates.env.filters["filesizeformat"] = format_size


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
    page: int = 1,
):
    page = max(page, 1)
    files, total = queries.search_files(q, ext, tag, page)
    total_pages = max(1, -(-total // queries.PAGE_SIZE))  # ceil division

    qs_params = ([("q", q)] if q else []) + [("ext", e) for e in ext] + [("tag", t) for t in tag]
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
            "all_projects": queries.list_projects(),
            "print_metadata": queries.get_print_metadata(file_id),
        },
    )


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


# ---- admin: watched roots -------------------------------------------------

@app.get("/admin", response_class=HTMLResponse)
def admin(request: Request):
    return templates.TemplateResponse(
        request, "admin.html", {"roots": queries.list_watched_roots(), "ingest_modes": INGEST_MODES}
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
