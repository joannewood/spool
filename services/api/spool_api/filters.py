from common.text import clean_name  # noqa: F401 — re-exported as a Jinja filter, see main.py


def ext_class(ext):
    """CSS class for the extension color-coding on grid cards — .step/.stp
    share one class since they're the same format, just spelled two ways."""
    ext = (ext or "").lower()
    if ext in (".step", ".stp"):
        return "ext-step"
    return "ext-" + ext.lstrip(".")


def thumb_url(thumbnail_path, content_hash=None):
    """Appends a cache-busting ?v= query param derived from the file's own
    content_hash — the thumbnail's filename is stable (`{file_id}.png`,
    overwritten in place on re-render), so pairing a long-lived
    Cache-Control header on /thumbnails (see main.py) with a plain
    filename would serve a stale image after a real re-render until the
    browser's cache expired. A changed content_hash naturally produces a
    new URL, so the long cache lifetime is safe. Sidecars have no
    content_hash (never re-rendered in place once created), so they're
    omitted — nothing to bust."""
    if not thumbnail_path:
        return None
    if content_hash:
        return f"/thumbnails/{thumbnail_path}?v={content_hash[:8]}"
    return f"/thumbnails/{thumbnail_path}"


def render_error_label(error_text):
    """Short, human-readable category for a failed render's raw jobs.error
    text, shown in the thumbnail placeholder instead of the bare word
    "failed" — see worker/app/mesh_safety.py for the two safety-guard
    error shapes this recognizes (an oversized mesh vs. a 3MF component
    tree that would blow up into far more geometry than its file size
    suggests). Anything else (a real bug, a malformed file) falls back to
    a generic label; the raw text is still available via the
    placeholder's title tooltip / the detail page's footer."""
    text = error_text or ""
    if "uncompressed" in text and "safety limit" in text:
        return "Mesh too large to render"
    if "build references" in text and "safety limit" in text:
        return "Too complex to render"
    return "Render failed"


def format_size(num_bytes):
    if num_bytes is None:
        return "—"
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"
