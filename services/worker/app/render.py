import os
import shutil

import numpy as np
import pyrender
import trimesh
from PIL import Image

from .step_loader import load_step_mesh

THUMBNAIL_SIZE = 512
MARGIN = 1.10  # ~10% margin around the bounding sphere
ELEVATION_DEG = 30  # above the XY (bed) plane
AZIMUTH_DEG = 40  # off-axis so box-like parts don't flatten into a hexagon
FOV_DEG = 40

THUMBNAILS_DIR = os.environ.get("THUMBNAILS_DIR", "/data/thumbnails")

# 3D-printing meshes are conventionally Z-up (bed = XY plane, Z = print
# height), unlike OpenGL's default Y-up convention — the camera math below
# is built around Z-up so the part sits the way it would on the bed.
_WORLD_UP = np.array([0.0, 0.0, 1.0])


def _look_at_pose(eye, target):
    forward = target - eye
    forward = forward / np.linalg.norm(forward)
    right = np.cross(forward, _WORLD_UP)
    right = right / np.linalg.norm(right)
    true_up = np.cross(right, forward)

    pose = np.eye(4)
    pose[:3, 0] = right
    pose[:3, 1] = true_up
    pose[:3, 2] = -forward  # camera looks down its own -Z
    pose[:3, 3] = eye
    return pose


def _camera_pose(radius):
    distance = (radius * MARGIN) / np.sin(np.radians(FOV_DEG) / 2)
    az = np.radians(AZIMUTH_DEG)
    el = np.radians(ELEVATION_DEG)
    eye = distance * np.array(
        [np.cos(el) * np.cos(az), np.cos(el) * np.sin(az), np.sin(el)]
    )
    return _look_at_pose(eye, np.zeros(3))


def render_svg_thumbnail(container_path, file_id):
    """SVG previews are the file itself — browsers render SVG natively and
    safely even via a plain <img> tag (no script execution in that
    context), so no rasterization dependency is needed."""
    os.makedirs(THUMBNAILS_DIR, exist_ok=True)
    filename = f"{file_id}.svg"
    shutil.copyfile(container_path, os.path.join(THUMBNAILS_DIR, filename))
    return filename


def load_mesh(container_path):
    ext = os.path.splitext(container_path)[1].lower()
    if ext in (".step", ".stp"):
        return load_step_mesh(container_path)
    return trimesh.load(container_path, force="mesh")


def render_thumbnail(container_path, file_id):
    mesh = load_mesh(container_path)

    center = mesh.bounds.mean(axis=0)
    radius = float(np.linalg.norm(mesh.bounds[1] - mesh.bounds[0])) / 2.0 or 1.0

    centered = mesh.copy()
    centered.apply_translation(-center)

    scene = pyrender.Scene(bg_color=[0.0, 0.0, 0.0, 0.0], ambient_light=[0.35, 0.35, 0.35])
    material = pyrender.MetallicRoughnessMaterial(
        baseColorFactor=[0.62, 0.66, 0.70, 1.0], metallicFactor=0.05, roughnessFactor=0.85
    )
    scene.add(pyrender.Mesh.from_trimesh(centered, material=material, smooth=True))

    pose = _camera_pose(radius)
    camera = pyrender.PerspectiveCamera(yfov=np.radians(FOV_DEG), aspectRatio=1.0)
    scene.add(camera, pose=pose)
    scene.add(pyrender.DirectionalLight(color=[1.0, 1.0, 1.0], intensity=3.0), pose=pose)

    renderer = pyrender.OffscreenRenderer(THUMBNAIL_SIZE, THUMBNAIL_SIZE)
    try:
        color, _depth = renderer.render(scene, flags=pyrender.RenderFlags.RGBA)
    finally:
        renderer.delete()

    os.makedirs(THUMBNAILS_DIR, exist_ok=True)
    filename = f"{file_id}.png"
    Image.fromarray(color).save(os.path.join(THUMBNAILS_DIR, filename))
    return filename, mesh
