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
    ".stl": "BambuStudio",
    ".3mf": "BambuStudio",
}

ALL_APPS = sorted(set(APP_MAP.values()))


def default_app_for_ext(ext):
    return APP_MAP.get(ext.lower())


def request_open(path, app):
    """Returns (ok, error_message)."""
    body = json.dumps({"path": path, "app": app}).encode()
    req = urllib.request.Request(
        f"{HOST_HELPER_URL}/open",
        data=body,
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
