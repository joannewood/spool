from common.settings import get_app_settings


def test_get_app_settings_returns_seeded_defaults(conn):
    settings = get_app_settings(conn)
    assert settings == {"rescan_enabled": True, "rescan_interval_seconds": 300}


def test_get_app_settings_reflects_updates(conn):
    with conn.cursor() as cur:
        cur.execute("UPDATE app_settings SET rescan_enabled = false, rescan_interval_seconds = 60 WHERE id = 1")
    assert get_app_settings(conn) == {"rescan_enabled": False, "rescan_interval_seconds": 60}
