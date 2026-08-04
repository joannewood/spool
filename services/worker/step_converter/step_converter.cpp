// Standalone STEP -> OBJ tessellator, linked directly against Debian's
// packaged OpenCASCADE (OCCT) libraries (apt: libocct-*-dev) instead of
// pulling in cadquery-ocp's ~1.4GB bundled OpenCASCADE distribution via
// pip. Mirrors the exact same pattern the author's separate spool-swift
// (native Mac) rewrite already uses for the same problem: OCCT is
// portable C++, so isolating the tessellation step into a small external
// tool sidesteps ever needing OCCT bindings for the host language at all.
//
// Deliberately does the *minimum* here: read the STEP file, tessellate
// with the exact same deflection formula step_loader.py already used via
// OCP's Python bindings, and write the raw (unmerged, unprocessed)
// triangle soup as a plain OBJ file. All of the correctness-critical
// post-processing (merge_vertices, nondegenerate_faces,
// remove_unreferenced_vertices -- see step_loader.py's own comments for
// why each one matters) deliberately stays in the already-proven Python/
// trimesh pipeline, fed from this tool's OBJ output instead of from
// direct in-process OCP calls. Splitting the risk this way means only
// the "read STEP, tessellate, dump vertices/faces" step is new code --
// the two hard-won correctness fixes already verified against a sphere
// and a filleted box are untouched.
#include <STEPControl_Reader.hxx>
#include <BRepMesh_IncrementalMesh.hxx>
#include <TopoDS_Shape.hxx>
#include <TopoDS_Face.hxx>
#include <Bnd_Box.hxx>
#include <BRepBndLib.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>
#include <BRep_Tool.hxx>
#include <Poly_Triangulation.hxx>
#include <TopLoc_Location.hxx>
#include <gp_Pnt.hxx>
#include <gp_Trsf.hxx>

#include <cmath>
#include <cstdio>
#include <fstream>
#include <iostream>
#include <vector>

// Matches step_loader.py's DEFLECTION_RATIO/MIN_LINEAR_DEFLECTION/
// ANGULAR_DEFLECTION exactly -- deflection scales with part size (~0.1%
// of the bounding diagonal) so a fixed value doesn't over-tessellate a
// small part or leave a large one visibly faceted, floored so tiny parts
// still get a usable mesh.
static const double DEFLECTION_RATIO = 0.001;
static const double MIN_LINEAR_DEFLECTION = 0.05;
static const double ANGULAR_DEFLECTION = 0.3;

static double boundingDiagonal(const TopoDS_Shape& shape) {
    Bnd_Box bbox;
    BRepBndLib::Add(shape, bbox);
    Standard_Real xmin, ymin, zmin, xmax, ymax, zmax;
    bbox.Get(xmin, ymin, zmin, xmax, ymax, zmax);
    double dx = xmax - xmin, dy = ymax - ymin, dz = zmax - zmin;
    return std::sqrt(dx * dx + dy * dy + dz * dz);
}

int main(int argc, char** argv) {
    if (argc != 3) {
        std::cerr << "usage: step_converter <input.step> <output.obj>\n";
        return 2;
    }
    const char* inputPath = argv[1];
    const char* outputPath = argv[2];

    STEPControl_Reader reader;
    if (reader.ReadFile(inputPath) != IFSelect_RetDone) {
        std::cerr << "failed to read STEP file: " << inputPath << "\n";
        return 1;
    }
    reader.TransferRoots();
    TopoDS_Shape shape = reader.OneShape();

    double diagonal = boundingDiagonal(shape);
    double linearDeflection = std::max(diagonal * DEFLECTION_RATIO, MIN_LINEAR_DEFLECTION);
    // Same 5-arg constructor step_loader.py uses: isRelative=false,
    // angular deflection, isInParallel=true -- not the simpler 2-arg
    // overload, which has different defaults for both.
    BRepMesh_IncrementalMesh(shape, linearDeflection, Standard_False, ANGULAR_DEFLECTION, Standard_True);

    std::vector<gp_Pnt> vertices;
    // Each entry is 3 global (1-indexed, matching OBJ's own convention)
    // vertex references.
    std::vector<std::array<int, 3>> faces;

    for (TopExp_Explorer exp(shape, TopAbs_FACE); exp.More(); exp.Next()) {
        TopoDS_Face face = TopoDS::Face(exp.Current());
        TopLoc_Location loc;
        Handle(Poly_Triangulation) tri = BRep_Tool::Triangulation(face, loc);
        if (tri.IsNull()) continue;

        const gp_Trsf& transform = loc.Transformation();
        int offset = static_cast<int>(vertices.size());
        for (int i = 1; i <= tri->NbNodes(); i++) {
            gp_Pnt pnt = tri->Node(i);
            pnt.Transform(transform);
            vertices.push_back(pnt);
        }
        for (int i = 1; i <= tri->NbTriangles(); i++) {
            int a, b, c;
            tri->Triangle(i).Get(a, b, c);
            faces.push_back({offset + a, offset + b, offset + c});
        }
    }

    if (faces.empty()) {
        std::cerr << "no triangulated geometry found in " << inputPath << "\n";
        return 1;
    }

    std::ofstream out(outputPath);
    if (!out) {
        std::cerr << "failed to open output file: " << outputPath << "\n";
        return 1;
    }
    // Full double precision (not a truncated %f) -- merge_vertices
    // downstream relies on shared-edge vertices from adjacent faces
    // coming out numerically identical, so any avoidable precision loss
    // here would work against exactly the fix it exists to apply.
    out.precision(17);
    for (const auto& v : vertices) {
        out << "v " << v.X() << " " << v.Y() << " " << v.Z() << "\n";
    }
    for (const auto& f : faces) {
        out << "f " << f[0] << " " << f[1] << " " << f[2] << "\n";
    }

    std::cerr << "wrote " << vertices.size() << " vertices, " << faces.size() << " triangles\n";
    return 0;
}
