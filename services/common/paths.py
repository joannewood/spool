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
