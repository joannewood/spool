import os
import subprocess
import tempfile

import trimesh

# Shells out to a small standalone C++ tool (services/worker/step_converter/)
# linked directly against Debian's packaged OpenCASCADE (OCCT) libraries,
# instead of using cadquery-ocp's Python bindings in-process — replaces a
# ~1.4GB bundled OpenCASCADE distribution with ~380MB of apt packages (see
# the Dockerfile's own comment). The tool's only job is "STEP -> raw OBJ
# triangle soup"; every correctness-critical step below (deflection
# formula match, merge_vertices, nondegenerate_faces,
# remove_unreferenced_vertices) is unchanged from the original in-process
# implementation, verified against the same box/sphere/filleted-corner
# test cases that validated it originally.
STEP_CONVERTER = "/usr/local/bin/step_converter"


def load_step_mesh(path):
    fd, obj_path = tempfile.mkstemp(suffix=".obj")
    os.close(fd)
    try:
        result = subprocess.run(
            [STEP_CONVERTER, path, obj_path],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"failed to read STEP file: {path} ({result.stderr.strip()})")

        # process=False -- we want the raw, unmerged triangle soup the
        # converter wrote (one exactly matching what the old in-process
        # OCP-based loader built directly), not whatever automatic
        # cleanup trimesh's own OBJ loader would otherwise apply before
        # the explicit steps below run.
        mesh = trimesh.load(obj_path, process=False, force="mesh")

        # Each face is tessellated independently, so vertices along a shared
        # edge between two faces don't come out bit-identical — without
        # merging them, trimesh sees phantom boundary edges and reports a
        # closed solid as non-watertight.
        mesh.merge_vertices()

        # Curved surfaces with a pole singularity (spheres, filleted corners,
        # etc.) tessellate with a couple of zero-area triangles right at the
        # pole — real geometry, not a defect, but they read as boundary edges
        # to the watertight check just like the seam issue above.
        mesh.update_faces(mesh.nondegenerate_faces())
        mesh.remove_unreferenced_vertices()

        return mesh
    finally:
        if os.path.exists(obj_path):
            os.remove(obj_path)
