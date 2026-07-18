import numpy as np
import trimesh
from OCP.Bnd import Bnd_Box
from OCP.BRep import BRep_Tool
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.STEPControl import STEPControl_Reader
from OCP.TopAbs import TopAbs_FACE
from OCP.TopExp import TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS

# Deflection scales with part size — a fixed value would over-tessellate a
# small part or leave a large one faceted. ~0.1% of the bounding diagonal,
# floored so tiny parts still get a usable mesh.
DEFLECTION_RATIO = 0.001
MIN_LINEAR_DEFLECTION = 0.05
ANGULAR_DEFLECTION = 0.3


def _bounding_diagonal(shape):
    bbox = Bnd_Box()
    BRepBndLib.Add_s(shape, bbox)
    xmin, ymin, zmin, xmax, ymax, zmax = bbox.Get()
    return float(np.linalg.norm([xmax - xmin, ymax - ymin, zmax - zmin]))


def load_step_mesh(path):
    reader = STEPControl_Reader()
    if reader.ReadFile(path) != 1:  # IFSelect_RetDone
        raise RuntimeError(f"failed to read STEP file: {path}")
    reader.TransferRoots()
    shape = reader.OneShape()

    diagonal = _bounding_diagonal(shape)
    linear_deflection = max(diagonal * DEFLECTION_RATIO, MIN_LINEAR_DEFLECTION)
    BRepMesh_IncrementalMesh(shape, linear_deflection, False, ANGULAR_DEFLECTION, True)

    vertices = []
    faces = []
    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    while explorer.More():
        face = TopoDS.Face_s(explorer.Current())
        location = TopLoc_Location()
        triangulation = BRep_Tool.Triangulation_s(face, location)
        if triangulation is not None:
            transform = location.Transformation()
            offset = len(vertices)
            for i in range(1, triangulation.NbNodes() + 1):
                pnt = triangulation.Node(i).Transformed(transform)
                vertices.append((pnt.X(), pnt.Y(), pnt.Z()))
            for i in range(1, triangulation.NbTriangles() + 1):
                a, b, c = triangulation.Triangle(i).Get()
                faces.append((offset + a - 1, offset + b - 1, offset + c - 1))
        explorer.Next()

    if not faces:
        raise RuntimeError(f"no triangulated geometry found in {path}")

    mesh = trimesh.Trimesh(vertices=np.array(vertices), faces=np.array(faces), process=False)

    # Each face is tessellated independently, so vertices along a shared
    # edge between two faces don't come out bit-identical — without merging
    # them, trimesh sees phantom boundary edges and reports a closed solid
    # as non-watertight.
    mesh.merge_vertices()

    # Curved surfaces with a pole singularity (spheres, filleted corners,
    # etc.) tessellate with a couple of zero-area triangles right at the
    # pole — real geometry, not a defect, but they read as boundary edges
    # to the watertight check just like the seam issue above.
    mesh.update_faces(mesh.nondegenerate_faces())
    mesh.remove_unreferenced_vertices()

    return mesh
