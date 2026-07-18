import os

import psycopg
from fastapi import FastAPI, HTTPException

DATABASE_URL = os.environ["DATABASE_URL"]

app = FastAPI(title="SPOOL API")


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
