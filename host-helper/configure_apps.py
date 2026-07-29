#!/usr/bin/env python3
"""Auto-detects installed CAD/slicer apps and writes host-helper's
APP_MAP (plus its mirror and APP_ICONS in services/api/spool_api/
host_helper_client.py) to match — the automated equivalent of the
manual "find the exact .app bundle name and edit host_helper.py by
hand" step this project started with. Safe to re-run any time; run
standalone (`python3 host-helper/configure_apps.py`) or via setup.sh.

Matches candidate apps by a fuzzy substring check against the REAL
installed .app bundle name in ~/Applications or /Applications, rather
than a hardcoded exact-name guess — bundle names occasionally differ
from marketing names (Autodesk's own app is "Autodesk Fusion.app", not
"Fusion 360.app"; confirmed by `ls`, not assumed), so matching against
what's actually on disk sidesteps needing to already know that.
"""
import os
import plistlib
import re
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOST_HELPER_PY = os.path.join(REPO_ROOT, "host-helper", "host_helper.py")
HOST_HELPER_CLIENT_PY = os.path.join(REPO_ROOT, "services", "api", "spool_api", "host_helper_client.py")
ICONS_DIR = os.path.join(REPO_ROOT, "services", "api", "spool_api", "static", "icons")

APPLICATIONS_DIRS = [os.path.expanduser("~/Applications"), "/Applications"]

# label, extensions handled, keywords fuzzy-matched against installed .app
# names (lowercased substring check). Split into three groups rather than
# a blanket "CAD" / "slicer" pair specifically for .scad — OpenSCAD is a
# distinct, commonly-installed app in its own right, not something anyone
# would expect a generic CAD app to open, even though this project's own
# original default (before this script existed) pointed .scad at Fusion.
GROUPS = [
    ("CAD app (.step / .stp / .f3d)", [".step", ".stp", ".f3d"], ["fusion", "freecad", "solidworks"]),
    ("OpenSCAD (.scad)", [".scad"], ["openscad"]),
    (
        "Slicer app (.stl / .3mf / .svg / .gcode / .obj)",
        [".stl", ".3mf", ".svg", ".gcode", ".obj"],
        ["bambu", "prusa", "orca", "cura", "superslicer", "ideamaker", "simplify3d", "chitubox"],
    ),
]


def find_installed_apps():
    apps = []
    for d in APPLICATIONS_DIRS:
        if not os.path.isdir(d):
            continue
        for name in os.listdir(d):
            if name.endswith(".app"):
                apps.append(name[:-4])
    return apps


# Installers/uninstallers/updaters that ship alongside the real app and
# happen to share its name in their own — confirmed live: this machine's
# own ~/Applications has "Remove Autodesk Fusion" and "Autodesk Fusion
# Service Utility" sitting right next to the real "Autodesk Fusion",
# all three matching the "fusion" keyword equally. Filtered out before
# ever reaching the candidate list, rather than relying on the user to
# pick the right one out of noise every single time this runs.
_NOISE_WORDS = ("uninstall", "remove", "updater", "update", "service utility", "installer", "helper")


def match_candidates(apps, keywords):
    return [
        name
        for name in apps
        if any(k in name.lower() for k in keywords) and not any(n in name.lower() for n in _NOISE_WORDS)
    ]


def prompt_choice(label, candidates):
    print(f"\n{label}:")
    for i, name in enumerate(candidates, 1):
        print(f"  {i}. {name}")
    type_option = len(candidates) + 1
    skip_option = len(candidates) + 2
    print(f"  {type_option}. Type a different app name")
    print(f"  {skip_option}. Skip (no default app for these file types)")
    while True:
        try:
            choice = input("Choose a number: ").strip()
        except EOFError:
            print("(no input available — skipping)")
            return None
        if not choice.isdigit():
            print("Not a valid choice, try again.")
            continue
        idx = int(choice)
        if 1 <= idx <= len(candidates):
            return candidates[idx - 1]
        if idx == type_option:
            typed = input('Exact .app name (without ".app", e.g. "PrusaSlicer"): ').strip()
            if typed:
                return typed
        elif idx == skip_option:
            return None
        print("Not a valid choice, try again.")


def find_bundle_path(app_name):
    for d in APPLICATIONS_DIRS:
        candidate = os.path.join(d, f"{app_name}.app")
        if os.path.isdir(candidate):
            return candidate
    return None


def extract_icon(app_name):
    """Best-effort .icns -> PNG extraction (sips + the bundle's own
    Info.plist, both already on every Mac) — mirrors the one-time manual
    step already used for this project's own Fusion/BambuStudio icons.
    Never fatal on failure: the UI already falls back to a plain
    two-letter badge for any app with no extracted icon."""
    bundle = find_bundle_path(app_name)
    if bundle is None:
        return None
    try:
        with open(os.path.join(bundle, "Contents", "Info.plist"), "rb") as f:
            plist = plistlib.load(f)
        icon_file = plist.get("CFBundleIconFile", "")
        if not icon_file:
            return None
        if not icon_file.endswith(".icns"):
            icon_file += ".icns"
        icns_path = os.path.join(bundle, "Contents", "Resources", icon_file)
        if not os.path.isfile(icns_path):
            return None
        slug = re.sub(r"[^a-z0-9]+", "-", app_name.lower()).strip("-")
        os.makedirs(ICONS_DIR, exist_ok=True)
        out_path = os.path.join(ICONS_DIR, f"{slug}.png")
        # -Z 64 matches this project's existing hand-extracted app icons
        # (and the printed-status icon) — a source .icns is often 512px+,
        # and the button that displays this is a fraction of that size
        # (CSS scales it down either way, but there's no reason to ship
        # 20x the needed bytes to every page load).
        subprocess.run(
            ["sips", "-s", "format", "png", "-Z", "64", icns_path, "--out", out_path],
            check=True, capture_output=True,
        )
        return f"{slug}.png"
    except Exception:
        return None


def replace_block(path, marker, new_body):
    with open(path) as f:
        text = f.read()
    pattern = re.compile(rf"# {marker}:BEGIN.*?# {marker}:END", re.DOTALL)
    if not pattern.search(text):
        raise RuntimeError(f"marker {marker} not found in {path} — was it edited by hand into a different shape?")
    replacement = (
        f"# {marker}:BEGIN (auto-generated by host-helper/configure_apps.py — "
        f"edit here directly, or just re-run that script)\n{new_body}\n# {marker}:END"
    )
    text = pattern.sub(replacement, text, count=1)
    with open(path, "w") as f:
        f.write(text)


def _quote(s):
    # Matches this codebase's double-quote convention — plain repr() would
    # emit single quotes instead.
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def format_dict(var_name, mapping):
    lines = [f"{var_name} = {{"]
    for key, value in mapping.items():
        lines.append(f"    {_quote(key)}: {_quote(value)},")
    lines.append("}")
    return "\n".join(lines)


def main():
    apps = find_installed_apps()
    app_map = {}
    chosen_apps = []

    for label, extensions, keywords in GROUPS:
        candidates = match_candidates(apps, keywords)
        if len(candidates) == 1:
            chosen = candidates[0]
            print(f"{label}: found {chosen}")
        else:
            chosen = prompt_choice(label, candidates)
        if chosen:
            chosen_apps.append(chosen)
            for ext in extensions:
                app_map[ext] = chosen

    if not app_map:
        print(
            "\nNo apps configured — 'Open in...' buttons won't do anything until "
            "you edit host-helper/host_helper.py's APP_MAP by hand, or re-run this script."
        )
        return 0

    app_icons = {}
    for app in sorted(set(chosen_apps)):
        icon_filename = extract_icon(app)
        if icon_filename:
            app_icons[app] = icon_filename

    replace_block(HOST_HELPER_PY, "APP_MAP", format_dict("APP_MAP", app_map))
    replace_block(HOST_HELPER_CLIENT_PY, "APP_MAP", format_dict("APP_MAP", app_map))
    replace_block(HOST_HELPER_CLIENT_PY, "APP_ICONS", format_dict("APP_ICONS", app_icons))

    print("\nConfigured:")
    for ext, app in app_map.items():
        print(f"  {ext} -> {app}")
    print(
        "\nRe-run host-helper/install.sh and rebuild the api container "
        "(docker compose up -d --build api) to pick this up."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
