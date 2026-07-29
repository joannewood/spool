#!/usr/bin/env python3
"""Auto-detects installed CAD/slicer apps and writes host-helper's
APP_MAP (plus its mirror in services/api/spool_api/host_helper_client.py,
and on macOS, APP_ICONS too) to match — the automated equivalent of the
manual "find the exact app and edit host_helper.py by hand" step this
project started with. Safe to re-run any time; run standalone
(`python3 host-helper/configure_apps.py`) or via setup.sh / setup.ps1.

On macOS: matches candidates by a fuzzy substring check against the REAL
installed .app bundle name in ~/Applications or /Applications, rather
than a hardcoded exact-name guess — bundle names occasionally differ
from marketing names (Autodesk's own app is "Autodesk Fusion.app", not
"Fusion 360.app"; confirmed by `ls`, not assumed), so matching against
what's actually on disk sidesteps needing to already know that. Writes
host_helper.py's APP_MAP directly (a bundle name doubles as both the
display label and the thing `open -a` launches).

On Windows: same fuzzy-match idea, but against .exe files found by
scanning Program Files-style directories (bounded depth — Windows has no
single "Applications folder" convention, and some real installs nest
several levels deep, e.g. Autodesk's own webdeploy layout). Windows has
no bundle-name-to-launch-command resolution, so this writes two things
to host_helper_windows.py: APP_MAP (ext -> a friendly label) and
APP_PATHS (that label -> the actual .exe path on this machine) — and
still writes the label-only APP_MAP to host_helper_client.py, same as
macOS, since that side never needs to know the real exe path. Icon
extraction is macOS-only for now (sips + a bundle's Info.plist); a
Windows app with no extracted icon just falls back to the UI's existing
plain two-letter badge, never a broken image.

NOTE: the Windows path in this script has not been exercised against
real Windows hardware — read the comments and double-check the result
(printed at the end) if something looks off, and use the "type it in
yourself" option freely if auto-detection guesses wrong.
"""
import os
import platform
import plistlib
import re
import subprocess
import sys

IS_WINDOWS = platform.system() == "Windows"

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOST_HELPER_CLIENT_PY = os.path.join(REPO_ROOT, "services", "api", "spool_api", "host_helper_client.py")
ICONS_DIR = os.path.join(REPO_ROOT, "services", "api", "spool_api", "static", "icons")

if IS_WINDOWS:
    HOST_HELPER_TARGET = os.path.join(REPO_ROOT, "host-helper", "host_helper_windows.py")
else:
    HOST_HELPER_TARGET = os.path.join(REPO_ROOT, "host-helper", "host_helper.py")

APPLICATIONS_DIRS = [os.path.expanduser("~/Applications"), "/Applications"]
# Deep enough to reach Autodesk's own webdeploy layout (confirmed against
# a real install path: "...\Autodesk\webdeploy\production\<hash>\Autodesk
# Fusion.exe" is 3 levels below the %LOCALAPPDATA%\Autodesk scan root
# itself), while still bounded so scanning Program Files doesn't wander
# arbitrarily far into some other app's deeply-nested data directory.
_WINDOWS_SCAN_MAX_DEPTH = 4

# label, extensions handled, keywords fuzzy-matched against an installed
# app's name (lowercased substring check). Split into three groups rather
# than a blanket "CAD" / "slicer" pair specifically for .scad — OpenSCAD is
# a distinct, commonly-installed app in its own right, not something
# anyone would expect a generic CAD app to open, even though this
# project's own original default (before this script existed) pointed
# .scad at Fusion.
GROUPS = [
    ("CAD app (.step / .stp / .f3d)", [".step", ".stp", ".f3d"], ["fusion", "freecad", "solidworks"]),
    ("OpenSCAD (.scad)", [".scad"], ["openscad"]),
    (
        "Slicer app (.stl / .3mf / .svg / .gcode / .obj)",
        [".stl", ".3mf", ".svg", ".gcode", ".obj"],
        ["bambu", "prusa", "orca", "cura", "superslicer", "ideamaker", "simplify3d", "chitubox"],
    ),
]

# Installers/uninstallers/updaters that ship alongside the real app and
# happen to share its name in their own — confirmed live on macOS: a real
# ~/Applications had "Remove Autodesk Fusion" and "Autodesk Fusion Service
# Utility" sitting right next to the real "Autodesk Fusion", all three
# matching the "fusion" keyword equally. Filtered out before ever reaching
# the candidate list, rather than relying on the user to pick the right
# one out of noise every single time this runs. Applies equally on
# Windows, where the same kind of noise shows up as e.g. an "Uninstall
# PrusaSlicer" folder.
_NOISE_WORDS = ("uninstall", "remove", "updater", "update", "service utility", "installer", "helper")


def find_installed_apps():
    """Returns a list of (label, identifier) pairs. On macOS `identifier`
    is identical to `label` (the .app bundle name, directly usable by
    `open -a`). On Windows `identifier` is the full path to a matched
    .exe; `label` is just its install folder's name, for display and for
    the APP_MAP written to host_helper_client.py."""
    if IS_WINDOWS:
        return _find_installed_apps_windows()
    return _find_installed_apps_macos()


def _find_installed_apps_macos():
    apps = []
    for d in APPLICATIONS_DIRS:
        if not os.path.isdir(d):
            continue
        for name in os.listdir(d):
            if name.endswith(".app"):
                label = name[:-4]
                apps.append((label, label))
    return apps


def _windows_scan_dirs():
    local_appdata = os.environ.get("LOCALAPPDATA")
    dirs = [
        os.environ.get("ProgramFiles", r"C:\Program Files"),
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
    ]
    if local_appdata:
        # %LOCALAPPDATA%\Programs is where a lot of modern per-user
        # installers (not needing admin rights) land; %LOCALAPPDATA%\Autodesk
        # specifically because Fusion's own installer uses a "webdeploy"
        # layout nested under there rather than Program Files.
        dirs.append(os.path.join(local_appdata, "Programs"))
        dirs.append(os.path.join(local_appdata, "Autodesk"))
    return dirs


# A version number ("23.1.1.100") or a hex build hash ("abc123def456") as
# an exe's immediate parent folder name — confirmed against Autodesk's
# own real webdeploy layout, where the actual .exe sits in exactly such a
# folder. Using that as the app's label would show something meaningless
# in SPOOL's UI, so it's rejected in favor of falling back to the exe's
# own filename (e.g. "Autodesk Fusion.exe" -> "Autodesk Fusion") instead
# of the useless hash.
_MEANINGLESS_FOLDER_RE = re.compile(r"^[0-9a-fA-F]{6,}$|^[\d.]+$")


def _label_for_windows_exe(dirpath, exe_filename):
    # Climbing further than the immediate parent was tried and reverted:
    # it recovers a nicer label for a version-numbered subfolder
    # ("OrcaSlicer/2.1.0/orca-slicer.exe"), but actively breaks the real,
    # already-confirmed Autodesk Fusion case — its grandparent folder is
    # literally named "production", a real word that isn't caught by
    # _MEANINGLESS_FOLDER_RE but is exactly as meaningless as a hash here.
    # No reliable way to tell those two situations apart with only a
    # folder name to go on, so this stops at one level: a slightly less
    # polished label (falling back to the exe's own filename) beats a
    # confidently wrong one.
    parent = os.path.basename(dirpath)
    if parent and not _MEANINGLESS_FOLDER_RE.match(parent):
        return parent
    return os.path.splitext(exe_filename)[0]


def _find_installed_apps_windows():
    apps = []
    seen_exes = set()
    for root_dir in _windows_scan_dirs():
        if not root_dir or not os.path.isdir(root_dir):
            continue
        base_depth = os.path.normpath(root_dir).count(os.sep)
        for dirpath, dirnames, filenames in os.walk(root_dir):
            depth = os.path.normpath(dirpath).count(os.sep) - base_depth
            if depth >= _WINDOWS_SCAN_MAX_DEPTH:
                dirnames[:] = []  # don't descend any further from here
                continue
            for name in filenames:
                if not name.lower().endswith(".exe"):
                    continue
                # Unlike a macOS .app bundle, an uninstaller/updater .exe
                # on Windows very often sits in the exact same install
                # folder as the real app (confirmed by simulation: a real
                # "Bambu Studio" folder holds both "bambu-studio.exe" and
                # "Uninstall Bambu Studio.exe") — so the folder-derived
                # label alone can't tell them apart the way it can on
                # macOS. Filter on the exe's own filename here, in
                # addition to the label-based filter in match_candidates
                # (which still matters for an uninstaller living in its
                # *own*, separately-named folder).
                if any(n in name.lower() for n in _NOISE_WORDS):
                    continue
                exe_path = os.path.join(dirpath, name)
                if exe_path in seen_exes:
                    continue
                seen_exes.add(exe_path)
                label = _label_for_windows_exe(dirpath, name)
                apps.append((label, exe_path))
    return apps


def match_candidates(apps, keywords):
    return [
        (label, identifier)
        for label, identifier in apps
        if any(k in label.lower() for k in keywords) and not any(n in label.lower() for n in _NOISE_WORDS)
    ]


def _prompt_manual_entry():
    if IS_WINDOWS:
        raw = input('Full path to the .exe (e.g. "C:\\Program Files\\PrusaSlicer\\prusa-slicer.exe"): ').strip()
        path = raw.strip('"')
        if not path:
            return None
        default_label = os.path.basename(os.path.dirname(path)) or os.path.splitext(os.path.basename(path))[0]
        label = input(f'Name to show in SPOOL (leave blank for "{default_label}"): ').strip()
        return (label or default_label, path)
    typed = input('Exact .app name (without ".app", e.g. "PrusaSlicer"): ').strip()
    if not typed:
        return None
    return (typed, typed)


def prompt_choice(group_label, candidates):
    print(f"\n{group_label}:")
    for i, (label, _identifier) in enumerate(candidates, 1):
        print(f"  {i}. {label}")
    type_option = len(candidates) + 1
    skip_option = len(candidates) + 2
    print(f"  {type_option}. Type it in yourself")
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
            return _prompt_manual_entry()
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
    """macOS only. Best-effort .icns -> PNG extraction (sips + the
    bundle's own Info.plist, both already on every Mac) — mirrors the
    one-time manual step already used for this project's own Fusion/
    BambuStudio icons. Never fatal on failure: the UI already falls back
    to a plain two-letter badge for any app with no extracted icon."""
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
    app_map = {}  # ext -> label
    app_identifiers = {}  # label -> identifier (bundle name on macOS, .exe path on Windows)

    for group_label, extensions, keywords in GROUPS:
        candidates = match_candidates(apps, keywords)
        if len(candidates) == 1:
            chosen = candidates[0]
            print(f"{group_label}: found {chosen[0]}")
        else:
            chosen = prompt_choice(group_label, candidates)
        if chosen:
            label, identifier = chosen
            app_identifiers[label] = identifier
            for ext in extensions:
                app_map[ext] = label

    if not app_map:
        target_name = os.path.basename(HOST_HELPER_TARGET)
        print(
            f"\nNo apps configured — 'Open in...' buttons won't do anything until "
            f"you edit host-helper/{target_name}'s APP_MAP by hand, or re-run this script."
        )
        return 0

    replace_block(HOST_HELPER_CLIENT_PY, "APP_MAP", format_dict("APP_MAP", app_map))
    replace_block(HOST_HELPER_TARGET, "APP_MAP", format_dict("APP_MAP", app_map))

    if IS_WINDOWS:
        replace_block(HOST_HELPER_TARGET, "APP_PATHS", format_dict("APP_PATHS", app_identifiers))
        print("\n(Icons aren't auto-extracted on Windows yet — any app here without one "
              "just shows a plain two-letter badge in the UI instead of a broken image.)")
    else:
        app_icons = {}
        for label in sorted(app_identifiers):
            icon_filename = extract_icon(label)
            if icon_filename:
                app_icons[label] = icon_filename
        replace_block(HOST_HELPER_CLIENT_PY, "APP_ICONS", format_dict("APP_ICONS", app_icons))

    print("\nConfigured:")
    for ext, label in app_map.items():
        print(f"  {ext} -> {label}")

    if IS_WINDOWS:
        print(
            "\nRe-run host-helper/install_windows.ps1 and rebuild the api container "
            "(docker compose up -d --build api) to pick this up."
        )
    else:
        print(
            "\nRe-run host-helper/install.sh and rebuild the api container "
            "(docker compose up -d --build api) to pick this up."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
