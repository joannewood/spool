import os
from urllib.parse import urlencode

import psycopg
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import queries
from .filters import format_size

DATABASE_URL = os.environ["DATABASE_URL"]
THUMBNAILS_DIR = os.environ.get("THUMBNAILS_DIR", "/data/thumbnails")
ALL_EXTENSIONS = [".stl", ".3mf", ".step", ".stp"]

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


@app.get("/", response_class=HTMLResponse)
def index(request: Request, q: str = "", ext: list[str] = Query(default=[]), page: int = 1):
    page = max(page, 1)
    files, total = queries.search_files(q, ext, page)
    total_pages = max(1, -(-total // queries.PAGE_SIZE))  # ceil division

    qs_params = ([("q", q)] if q else []) + [("ext", e) for e in ext]
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
    return templates.TemplateResponse(request, "file_detail.html", {"file": file})
