import json
import os
import urllib.error
import urllib.request

# Docker Desktop for Mac resolves this to the host automatically — no
# extra_hosts/networking config needed (confirmed: a throwaway container's
# `getent hosts host.docker.internal` resolves to the gateway IP).
HOST_HELPER_URL = os.environ.get("HOST_HELPER_URL", "http://host.docker.internal:8100")

# Mirrors host-helper/host_helper.py's APP_MAP — kept in sync by hand (five
# lines, not worth a shared package between a Docker image and a native
# host process). Real installed .app bundle names, not marketing names.
APP_MAP = {
    ".step": "Autodesk Fusion",
    ".stp": "Autodesk Fusion",
    ".f3d": "Autodesk Fusion",
    ".scad": "Autodesk Fusion",
    ".stl": "BambuStudio",
    ".3mf": "BambuStudio",
    ".svg": "BambuStudio",
}

ALL_APPS = sorted(set(APP_MAP.values()))

# Real app icons extracted once from each .app bundle's own .icns
# (services/api/spool_api/static/icons/ — `sips -s format png <bundle>/Contents/
# Resources/<icon>.icns --out <name>.png`), not a live host-helper endpoint:
# these never change short of a reinstall, so there's nothing to gain from
# re-extracting them per request over just checking the PNGs in like
# favicon.svg.
APP_ICONS = {
    "BambuStudio": "bambustudio.png",
    "Autodesk Fusion": "autodesk-fusion.png",
}


def default_app_for_ext(ext):
    return APP_MAP.get(ext.lower())


def _post(route, body):
    """Returns (ok, error_message)."""
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{HOST_HELPER_URL}{route}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5):
            return True, None
    except urllib.error.HTTPError as exc:
        try:
            error = json.loads(exc.read()).get("error", str(exc))
        except (json.JSONDecodeError, AttributeError):
            error = str(exc)
        return False, error
    except urllib.error.URLError as exc:
        return False, f"could not reach host-helper: {exc.reason}"


def request_open(path, app=None):
    """app=None lets host-helper hand off to macOS/LaunchServices' own
    default handler for the file — used for sidecar files (README/PDF/
    preview images) that aren't in APP_MAP, since those aren't CAD files
    with one obvious app to open them in."""
    return _post("/open", {"path": path, "app": app})


def request_delete(path):
    return _post("/delete", {"path": path})
