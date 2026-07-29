from common.paths import is_archive_file, is_ignorable_junk, is_model_file, to_container_path, to_host_path
from common.roots import WatchedRoot


def _root(host_path="/Users/test/Documents/3DPrintFiles", container_path="/roots/dropfolder"):
    return WatchedRoot(
        id=1,
        host_path=host_path,
        container_path=container_path,
        label="Test",
        kind="drop_folder",
        ingest_mode="index_in_place",
        active=True,
    )


def test_is_model_file_recognizes_all_current_extensions():
    for ext in (".stl", ".3mf", ".step", ".stp", ".STL", ".SvG", ".scad", ".gcode", ".obj"):
        assert is_model_file(f"widget{ext}")


def test_is_model_file_rejects_unrelated_extensions():
    for ext in (".jpg", ".zip", ".txt", ".png", ""):
        assert not is_model_file(f"widget{ext}")


def test_is_archive_file():
    assert is_archive_file("Archive.zip")
    assert is_archive_file("Archive.ZIP")
    assert is_archive_file("Archive.7z")
    assert is_archive_file("Archive.7Z")
    assert is_archive_file("Archive.rar")
    assert is_archive_file("Archive.RAR")
    assert not is_archive_file("widget.stl")


def test_is_ignorable_junk():
    assert is_ignorable_junk("/some/dir/.DS_Store")
    assert is_ignorable_junk("/some/dir/Thumbs.db")
    assert not is_ignorable_junk("/some/dir/widget.stl")


def test_is_ignorable_junk_appledouble():
    assert is_ignorable_junk("/some/dir/._widget.stl")
    assert is_ignorable_junk("/some/dir/._.DS_Store")
    assert not is_ignorable_junk("/some/dir/widget.stl")


def test_to_container_path_maps_host_path_under_root():
    root = _root()
    host_path = "/Users/test/Documents/3DPrintFiles/sub/widget.stl"
    assert to_container_path(root, host_path) == "/roots/dropfolder/sub/widget.stl"


def test_to_host_path_maps_container_path_under_root():
    root = _root()
    container_path = "/roots/dropfolder/sub/widget.stl"
    assert to_host_path(root, container_path) == "/Users/test/Documents/3DPrintFiles/sub/widget.stl"


def test_host_and_container_path_round_trip():
    root = _root()
    host_path = "/Users/test/Documents/3DPrintFiles/a/b/widget.stl"
    container_path = to_container_path(root, host_path)
    assert to_host_path(root, container_path) == host_path


# ---- Windows host paths ------------------------------------------------
#
# watcher/worker/api always run inside Linux containers regardless of the
# host OS, so os.path here is always POSIX — a Windows host_path only
# round-trips correctly through it if it uses forward slashes ("C:/Users/
# you/..."), never backslashes ("C:\Users\you\..."), since POSIX os.path
# only recognizes "/" as a separator. This is the one convention Windows
# support (host-helper/host_helper_windows.py, setup.ps1) depends on —
# Windows itself accepts forward-slash paths everywhere that matters
# (os.path, subprocess, Explorer's address bar), so nothing on the Windows
# side needs backslashes either. Locked in with real tests rather than
# left as an unverified assumption, since nothing else in this change can
# be exercised against real Windows hardware.

def test_to_container_path_maps_windows_style_forward_slash_host_path():
    root = _root(host_path="C:/Users/test/Documents/3DPrintFiles")
    host_path = "C:/Users/test/Documents/3DPrintFiles/sub/widget.stl"
    assert to_container_path(root, host_path) == "/roots/dropfolder/sub/widget.stl"


def test_to_host_path_produces_windows_style_forward_slash_path():
    root = _root(host_path="C:/Users/test/Documents/3DPrintFiles")
    container_path = "/roots/dropfolder/sub/widget.stl"
    assert to_host_path(root, container_path) == "C:/Users/test/Documents/3DPrintFiles/sub/widget.stl"


def test_windows_style_host_and_container_path_round_trip():
    root = _root(host_path="C:/Users/test/Documents/3DPrintFiles")
    host_path = "C:/Users/test/Documents/3DPrintFiles/a/b/widget.stl"
    container_path = to_container_path(root, host_path)
    assert to_host_path(root, container_path) == host_path
