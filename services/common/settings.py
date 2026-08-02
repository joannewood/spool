def get_app_settings(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT rescan_enabled, rescan_interval_seconds FROM app_settings WHERE id = 1")
        rescan_enabled, rescan_interval_seconds = cur.fetchone()
    return {"rescan_enabled": rescan_enabled, "rescan_interval_seconds": rescan_interval_seconds}
