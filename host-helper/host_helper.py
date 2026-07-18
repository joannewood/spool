#!/usr/bin/env python3
"""SPOOL host-helper — the one piece of SPOOL that isn't Docker.

Runs natively on macOS (launchd agent, see install.sh) because a Linux
container can't launch a macOS GUI app. Listens on loopback only; the `api`
container reaches it via Docker Desktop's `host.docker.internal` DNS name,
which routes to loopback-bound host services.

Deliberately stdlib-only (http.server + subprocess) — this is a one-route
job, and a framework would just mean a venv to create and keep in sync on
the host, which is exactly the operational overhead a native launchd agent
should avoid.
"""
import json
import os
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = "127.0.0.1"
PORT = 8100

# ext -> real installed .app bundle name. Not the marketing name — `open -a`
# matches the actual bundle, and these differ from both the spec's casual
# wording and Autodesk's old branding: Autodesk dropped "360" from the name,
# and Bambu Studio's bundle has no space in it.
APP_MAP = {
    ".step": "Autodesk Fusion",
    ".stp": "Autodesk Fusion",
    ".f3d": "Autodesk Fusion",
    ".scad": "Autodesk Fusion",
    ".stl": "BambuStudio",
    ".3mf": "BambuStudio",
    ".svg": "BambuStudio",
}
ALLOWED_APPS = set(APP_MAP.values())

# Real deletion requires real OS-level filesystem access, which is exactly
# what the api/worker containers don't reliably have (Library is mounted
# :ro in Docker regardless of the real OS permissions) — host-helper runs
# natively, so it can. Deletion is irreversible, so — unlike /open, which
# only ever launches a GUI app — this endpoint independently re-validates
# that the path falls under a known watched root rather than trusting the
# caller entirely, even though the api container only ever sources paths
# from real `files.path` DB rows. Hardcoded to match this machine, same as
# the seed migration's watched roots (personal tool, not portable).
ALLOWED_DELETE_ROOTS = [
    "/Users/jo/Documents/3DPrintFiles",
    "/Users/jo/Documents/3D Printing",
    "/Users/jo/Downloads",
]


def _under_allowed_root(path):
    return any(os.path.commonpath([path, root]) == root for root in ALLOWED_DELETE_ROOTS)


class Handler(BaseHTTPRequestHandler):
    def _send(self, status, body):
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length))

    def do_POST(self):
        if self.path == "/open":
            self._handle_open()
        elif self.path == "/delete":
            self._handle_delete()
        else:
            self._send(404, {"error": "not found"})

    def _handle_open(self):
        try:
            data = self._read_json()
        except json.JSONDecodeError:
            self._send(400, {"error": "invalid json"})
            return

        path = data.get("path")
        app = data.get("app")

        if not path or not os.path.isfile(path):
            self._send(404, {"error": "file not found on disk"})
            return

        # Never trust the caller's app name into subprocess, even though
        # subprocess.run's list form isn't shell-injectable — constrain to
        # known installed apps regardless of what the api container sends.
        if app not in ALLOWED_APPS:
            self._send(400, {"error": f"app not allowed: {app}"})
            return

        try:
            subprocess.run(["open", "-a", app, path], check=True)
        except subprocess.CalledProcessError as exc:
            self._send(500, {"error": str(exc)})
            return

        self._send(200, {"status": "ok"})

    def _handle_delete(self):
        try:
            data = self._read_json()
        except json.JSONDecodeError:
            self._send(400, {"error": "invalid json"})
            return

        path = data.get("path")

        if not path or not os.path.isfile(path):
            self._send(404, {"error": "file not found on disk"})
            return

        if not _under_allowed_root(path):
            self._send(400, {"error": "path is outside known watched roots"})
            return

        try:
            os.remove(path)
        except OSError as exc:
            self._send(500, {"error": str(exc)})
            return

        self._send(200, {"status": "ok"})


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"[host-helper] listening on {HOST}:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
