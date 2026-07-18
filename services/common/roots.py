from dataclasses import dataclass


@dataclass
class WatchedRoot:
    id: int
    host_path: str
    container_path: str
    label: str
    kind: str
    ingest_mode: str
    active: bool


_COLUMNS = "id, host_path, container_path, label, kind, ingest_mode, active"


def fetch_active_roots(conn):
    with conn.cursor() as cur:
        cur.execute(f"SELECT {_COLUMNS} FROM watched_roots WHERE active = TRUE ORDER BY id")
        rows = cur.fetchall()
    return [WatchedRoot(*row) for row in rows]


def fetch_root_by_id(conn, root_id):
    with conn.cursor() as cur:
        cur.execute(f"SELECT {_COLUMNS} FROM watched_roots WHERE id = %s", (root_id,))
        row = cur.fetchone()
    return WatchedRoot(*row) if row else None


def fetch_dropfolder_root(conn):
    for root in fetch_active_roots(conn):
        if root.kind == "drop_folder":
            return root
    raise RuntimeError("no active drop_folder root configured")
