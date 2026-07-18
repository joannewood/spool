MODEL_EXTENSIONS = {".stl", ".3mf", ".step", ".stp", ".svg", ".scad"}

# Rendered via trimesh directly (Phase 02) vs. tessellated through a CAD
# kernel first (Phase 03) — STEP renders get their own job_type/queue lane
# (render_step) so a slow CAD render never blocks quick mesh renders behind it.
MESH_EXTENSIONS = {".stl", ".3mf"}
STEP_EXTENSIONS = {".step", ".stp"}
# SVG previews are the file itself (browsers render SVG natively and safely
# even via a plain <img> tag — no script execution in that context), so no
# rendering dependency is needed, just a copy into the thumbnails dir.
SVG_EXTENSIONS = {".svg"}
# OpenSCAD source — indexed like any other model file (hash/tag/relate/
# open-in-app) but deliberately no preview: a real one would mean running
# arbitrary .scad scripts through the OpenSCAD CLI, a much heavier
# dependency than anything else in this project. Still gets a 'render' job
# so it settles at render_status='done' (no thumbnail) instead of sitting
# at 'pending' forever, which would look like a stuck job rather than by
# design.
SCAD_EXTENSIONS = {".scad"}

# Sidecar image files (kit preview photos, etc.) get a thumbnail the same
# lightweight way SVG model files do — a plain copy into the thumbnails
# dir, no rasterization dependency needed since these are already raster.
SIDECAR_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
