"""Extracts the largest embedded preview PNG from a gcode file's own
header comments — PrusaSlicer/SuperSlicer/OrcaSlicer/Bambu Studio all
write these the same way (`; thumbnail begin <W>x<H> <bytes>`, base64
data lines each prefixed with `; `, `; thumbnail end`), since Bambu
Studio's slicer is itself a PrusaSlicer fork sharing the same convention.

Deliberately its own lightweight module (stdlib only — base64/re/os),
not folded into render.py, so nothing that just wants to peek at gcode
header comments drags pyrender/trimesh along with it — same reasoning
as bambu_metadata.py being separate from the mesh renderer.
"""
import base64
import binascii
import os
import re

THUMBNAILS_DIR = os.environ.get("THUMBNAILS_DIR", "/data/thumbnails")

_BEGIN_RE = re.compile(r"^;\s*thumbnail\s+begin\s+(\d+)x(\d+)\s+\d+\s*$", re.IGNORECASE)
_END_RE = re.compile(r"^;\s*thumbnail\s+end\s*$", re.IGNORECASE)

# Every slicer that embeds thumbnails writes them in the gcode's header,
# well within this — scanning further would just cost time on the (more
# common) files that don't have one at all, and a gcode file can
# otherwise run to tens of MB of pure toolpath commands.
_HEADER_SCAN_LIMIT_BYTES = 2_000_000


def _find_largest_embedded_png(container_path):
    best_score = -1
    best_bytes = None
    in_block = False
    chunks = []
    dims = (0, 0)
    bytes_scanned = 0

    with open(container_path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            bytes_scanned += len(line)
            stripped = line.strip()
            if not in_block:
                m = _BEGIN_RE.match(stripped)
                if m:
                    in_block = True
                    chunks = []
                    dims = (int(m.group(1)), int(m.group(2)))
                elif bytes_scanned > _HEADER_SCAN_LIMIT_BYTES:
                    break
                continue
            if _END_RE.match(stripped):
                in_block = False
                try:
                    raw = base64.b64decode("".join(chunks))
                except (binascii.Error, ValueError):
                    continue
                score = dims[0] * dims[1]
                if score > best_score:
                    best_score = score
                    best_bytes = raw
                continue
            if stripped.startswith(";"):
                chunks.append(stripped[1:].strip())

    return best_bytes


def extract_gcode_thumbnail(container_path, file_id):
    """Returns the thumbnail filename if this gcode had an embedded
    preview, or None if it didn't — thumbnails are an opt-in slicer
    profile setting, confirmed off for some real files already in this
    library, so a miss here is a normal outcome, not an error."""
    png_bytes = _find_largest_embedded_png(container_path)
    if png_bytes is None:
        return None
    os.makedirs(THUMBNAILS_DIR, exist_ok=True)
    filename = f"{file_id}.png"
    with open(os.path.join(THUMBNAILS_DIR, filename), "wb") as out:
        out.write(png_bytes)
    return filename
