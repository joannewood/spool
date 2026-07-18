from psycopg.rows import dict_row

from common.db import get_connection

PAGE_SIZE = 60


def search_files(q, extensions, page):
    offset = (page - 1) * PAGE_SIZE
    conditions = ["status = 'active'"]
    params = []
    if q:
        conditions.append("filename ILIKE %s")
        params.append(f"%{q}%")
    if extensions:
        conditions.append("ext = ANY(%s)")
        params.append(list(extensions))
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
