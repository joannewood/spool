MODEL_EXTENSIONS = {".stl", ".3mf", ".step", ".stp"}

# Rendered via trimesh directly (Phase 02) vs. tessellated through a CAD
# kernel first (Phase 03) — STEP renders get their own job_type/queue lane
# (render_step) so a slow CAD render never blocks quick mesh renders behind it.
MESH_EXTENSIONS = {".stl", ".3mf"}
STEP_EXTENSIONS = {".step", ".stp"}
