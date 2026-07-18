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
    ".stl": "BambuStudio",
    ".3mf": "BambuStudio",
}
ALLOWED_APPS = set(APP_MAP.values())


class Handler(BaseHTTPRequestHandler):
    def _send(self, status, body):
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        if self.path != "/open":
            self._send(404, {"error": "not found"})
            return

        length = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(length))
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


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"[host-helper] listening on {HOST}:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
