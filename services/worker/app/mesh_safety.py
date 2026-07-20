"""Pre-flight safety checks for 3MF files, run before ever handing one to
trimesh.load — pure zipfile/regex inspection, no geometry deps, deliberately
kept separate from render.py so these are importable (and testable) without
dragging in numpy/pyrender/trimesh (same lightweight-module precedent as
job_queue.py/gcode_thumbnail.py/gcode_metadata.py/bambu_metadata.py).

Two independent, confirmed-live hazards, neither implied by the other:

- A .3mf's *compressed* file size is a poor proxy for how expensive it is
  to render — confirmed live during a 2600-file bulk import: several
  files, each an unremarkable few MB on disk, carried a single inner
  3D/Objects/*.model XML entry of 25-108MB *uncompressed* (a very
  high-poly mesh/scan), and parsing+rendering that reliably exhausted
  available memory and OOM-killed the whole worker process every time,
  regardless of the self-recycle/restart safeguards elsewhere. Rejecting
  by *uncompressed* mesh size before ever attempting trimesh.load — which
  is cheap, since zipfile.infolist() reads the zip's central directory,
  not the entries themselves — avoids repeating that crash for every
  future oversized file in a large, varied import instead of relying on
  OOM recovery after the fact.

  First deployed at 30MB; a 25MB file still crashed the process under
  this same burst-load (many jobs processed back-to-back, no gap for the
  OS to reclaim anything in between) before the threshold was lowered —
  30MB wasn't "wrong", it just didn't leave enough margin for how much
  *more* expensive rendering the same uncompressed byte count is under
  sustained load vs. normal trickle-load. 12MB is deliberately
  conservative, not a tightly-fitted number from more data points.

- A second, independent hazard: a Bambu multi-plate export ("ege.3mf")
  OOM-killed the worker within ~20s every single restart, despite its
  *.model entries totaling only ~5MB uncompressed (well under the size
  guard above). Its root 3D/3dmodel.model had 166 <component> references
  — trimesh's 3MF loader resolves each build item's component tree into
  concrete instanced geometry, and a tree with many (possibly nested)
  component references multiplies out into far more actual triangle data
  than the raw XML size suggests — a "small file, huge expansion" hazard
  the byte-size guard structurally can't see, same category as an XML
  entity-expansion ("billion laughs") bomb. Counting raw <item>/<component
  tag occurrences across every *.model entry (cheap text search, no XML
  parsing, no recursion — same "don't touch the expensive path at all"
  principle as the size guard) is a heuristic proxy, not an exact instance
  count: it can't detect deep/recursive multiplication hidden behind a low
  flat tag count, and could in principle reject a legitimately complex
  flat multi-part plate. Deliberately conservative given exactly one real
  data point (166 crashed) — revisit if a legitimate file ever gets
  rejected by this.
"""
import re
import zipfile

MAX_UNCOMPRESSED_3MF_MESH_BYTES = 12_000_000  # ~12MB uncompressed XML
MAX_3MF_BUILD_REFERENCES = 60

_BUILD_REF_RE = re.compile(rb"<(?:item|component)\s")


class OversizedMeshError(Exception):
    """Raised instead of attempting to load/render a mesh known in
    advance to be dangerously large for this process's available memory."""


class ExcessiveComponentCountError(Exception):
    """Raised instead of attempting to load/render a 3MF whose build item/
    component reference count suggests dangerous instance-count blowup when
    flattened into concrete geometry (see module docstring)."""


def _model_entries(zf):
    return [
        info
        for info in zf.infolist()
        if info.filename.startswith("3D/") and info.filename.endswith(".model")
    ]


def check_3mf_mesh_size(container_path):
    with zipfile.ZipFile(container_path) as zf:
        total = sum(info.file_size for info in _model_entries(zf))
    if total > MAX_UNCOMPRESSED_3MF_MESH_BYTES:
        raise OversizedMeshError(
            f"3MF's inner mesh data is {total:,} bytes uncompressed, over the "
            f"{MAX_UNCOMPRESSED_3MF_MESH_BYTES:,}-byte safety limit — skipped without "
            "attempting to render (see mesh_safety.py's module docstring)"
        )


def check_3mf_component_count(container_path):
    total = 0
    with zipfile.ZipFile(container_path) as zf:
        for info in _model_entries(zf):
            total += len(_BUILD_REF_RE.findall(zf.read(info)))
    if total > MAX_3MF_BUILD_REFERENCES:
        raise ExcessiveComponentCountError(
            f"3MF has {total:,} <item>/<component> build references, over the "
            f"{MAX_3MF_BUILD_REFERENCES:,}-reference safety limit — skipped without "
            "attempting to render (see mesh_safety.py's module docstring)"
        )


def check_3mf_is_safe_to_render(container_path):
    check_3mf_mesh_size(container_path)
    check_3mf_component_count(container_path)
