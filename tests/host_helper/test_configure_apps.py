"""host-helper/configure_apps.py isn't part of any services/ package (it's
a standalone script meant to run natively, not inside a container), so
it's loaded directly by file path rather than via the normal pythonpath
machinery the rest of tests/ relies on.

The Windows-specific functions here (_find_installed_apps_windows,
_label_for_windows_exe) are exercised against synthetic directory trees
built with tempfile — this is the only way to get real test coverage on
that code at all, since there's no Windows machine to run it against for
real. Each test below exists because manually simulating this exact
scenario during development caught a real bug before it shipped (see the
comments on each) — not hypothetical edge cases.
"""
import importlib.util
import os
import sys
import tempfile

import pytest

_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "host-helper", "configure_apps.py")
_spec = importlib.util.spec_from_file_location("configure_apps", _PATH)
configure_apps = importlib.util.module_from_spec(_spec)
sys.modules["configure_apps"] = configure_apps
_spec.loader.exec_module(configure_apps)


@pytest.fixture
def fake_windows_tree(tmp_path):
    program_files = tmp_path / "Program Files"
    localappdata_autodesk = tmp_path / "LocalAppData" / "Autodesk"
    program_files.mkdir()
    localappdata_autodesk.mkdir(parents=True)
    return program_files, localappdata_autodesk


def test_find_installed_apps_windows_excludes_uninstaller_in_same_folder(fake_windows_tree, monkeypatch):
    # Real bug caught during development: the folder-name-based noise
    # filter (used on macOS, where an uninstaller is its own separate
    # .app bundle) doesn't help on Windows, where an uninstaller .exe
    # commonly sits in the exact same install folder as the real app —
    # both would share the identical folder-derived label.
    program_files, autodesk_dir = fake_windows_tree
    app_dir = program_files / "Bambu Studio"
    app_dir.mkdir()
    (app_dir / "bambu-studio.exe").touch()
    (app_dir / "Uninstall Bambu Studio.exe").touch()

    monkeypatch.setattr(configure_apps, "_windows_scan_dirs", lambda: [str(program_files), str(autodesk_dir)])
    apps = configure_apps._find_installed_apps_windows()

    assert apps == [("Bambu Studio", str(app_dir / "bambu-studio.exe"))]


def test_find_installed_apps_windows_reaches_deeply_nested_install(fake_windows_tree, monkeypatch):
    # Real bug caught during development: the original depth cap (3) was
    # too shallow to reach a real Autodesk Fusion install, which sits 3
    # levels below the %LOCALAPPDATA%\Autodesk scan root itself
    # (webdeploy/production/<hash>/Autodesk Fusion.exe) — the exe was
    # silently never found at all, not just mislabeled.
    program_files, autodesk_dir = fake_windows_tree
    fusion_dir = autodesk_dir / "webdeploy" / "production" / "abc123def456"
    fusion_dir.mkdir(parents=True)
    (fusion_dir / "Autodesk Fusion.exe").touch()

    monkeypatch.setattr(configure_apps, "_windows_scan_dirs", lambda: [str(program_files), str(autodesk_dir)])
    apps = configure_apps._find_installed_apps_windows()

    assert apps == [("Autodesk Fusion", str(fusion_dir / "Autodesk Fusion.exe"))]


def test_find_installed_apps_windows_prunes_paths_past_the_depth_cap(fake_windows_tree, monkeypatch):
    program_files, autodesk_dir = fake_windows_tree
    too_deep = program_files.joinpath(*["a"] * (configure_apps._WINDOWS_SCAN_MAX_DEPTH + 2))
    too_deep.mkdir(parents=True)
    (too_deep / "toodeep.exe").touch()

    monkeypatch.setattr(configure_apps, "_windows_scan_dirs", lambda: [str(program_files), str(autodesk_dir)])
    apps = configure_apps._find_installed_apps_windows()

    assert apps == []


def test_label_for_windows_exe_uses_meaningful_parent_folder():
    assert configure_apps._label_for_windows_exe("C:/Program Files/Bambu Studio", "bambu-studio.exe") == "Bambu Studio"


def test_label_for_windows_exe_falls_back_to_filename_for_a_hash_folder():
    # The Autodesk webdeploy case — the immediate parent is a meaningless
    # build hash, so the label should come from the exe's own name instead.
    assert (
        configure_apps._label_for_windows_exe("C:/.../production/abc123def456", "Autodesk Fusion.exe")
        == "Autodesk Fusion"
    )


def test_label_for_windows_exe_falls_back_to_filename_for_a_version_folder():
    assert configure_apps._label_for_windows_exe("C:/Program Files/OrcaSlicer/2.1.0", "orca-slicer.exe") == "orca-slicer"


def test_label_for_windows_exe_does_not_climb_past_the_immediate_parent():
    # Deliberately does NOT fall back further to the grandparent folder —
    # tried during development to recover a nicer label for the
    # version-folder case above, but reverted: it actively broke the real
    # Fusion case, since its grandparent folder is literally named
    # "production" (a real word, not caught by the hash/version filter,
    # but exactly as meaningless as a hash here). No reliable way to tell
    # those two situations apart from a folder name alone, so this locks
    # in the safer choice: a less-polished-but-correct label beats a
    # confidently wrong one.
    assert (
        configure_apps._label_for_windows_exe("C:/.../webdeploy/production/abc123def456", "Autodesk Fusion.exe")
        != "production"
    )


def test_match_candidates_filters_by_keyword_and_noise_words():
    apps = [("Bambu Studio", "/x/bambu-studio.exe"), ("Remove BambuStudio", "/x/remove.exe"), ("PrusaSlicer", "/x/prusa.exe")]
    result = configure_apps.match_candidates(apps, ["bambu"])
    assert result == [("Bambu Studio", "/x/bambu-studio.exe")]


def test_format_dict_uses_double_quotes_matching_project_style():
    body = configure_apps.format_dict("APP_MAP", {".stl": "BambuStudio"})
    assert body == 'APP_MAP = {\n    ".stl": "BambuStudio",\n}'
