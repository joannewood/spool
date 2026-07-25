import os

from .config import MODEL_EXTENSIONS


def to_host_path(root, container_path):
    rel = os.path.relpath(container_path, root.container_path)
    return os.path.normpath(os.path.join(root.host_path, rel))


def to_container_path(root, host_path):
    rel = os.path.relpath(host_path, root.host_path)
    return os.path.normpath(os.path.join(root.container_path, rel))


def is_model_file(path):
    return os.path.splitext(path)[1].lower() in MODEL_EXTENSIONS


# All three are peeked (namelist only, no decompression) to decide
# whether they're worth surfacing for review — see common/zip_ingest.py,
# which dispatches to zipfile, py7zr, or rarfile based on which of these
# matched. .rar itself can't be read in pure Python (its compression
# algorithm isn't freely implementable the way .zip/.7z's are) — rarfile
# shells out to a system tool (bsdtar, in this project's Docker images)
# just for the actual decompression; listing/namelist only needs the
# archive's own header, no external tool involved.
_ARCHIVE_EXTENSIONS = {".zip", ".7z", ".rar"}


def is_archive_file(path):
    return os.path.splitext(path)[1].lower() in _ARCHIVE_EXTENSIONS


# OS-generated clutter that shows up in nearly every folder and carries no
# information worth surfacing as a project sidecar.
_IGNORED_FILENAMES = {".DS_Store", "Thumbs.db", "desktop.ini"}


def is_ignorable_junk(path):
    basename = os.path.basename(path)
    # AppleDouble resource-fork shadow files (e.g. "._Hammer handle.stl") —
    # created by macOS when copying from drives/shares that don't support
    # native resource forks, one per real file, never worth indexing.
    if basename.startswith("._"):
        return True
    return basename in _IGNORED_FILENAMES
