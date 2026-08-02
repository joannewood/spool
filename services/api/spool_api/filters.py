from datetime import datetime, timezone

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
    suggests), plus a real trimesh 4.12.2 bug (confirmed live against 4
    real files: `KeyError: 'world'` from trimesh/exchange/threemf.py's
    load_3MF, which unconditionally walks its parsed 3MF build graph
    from a root node named "world" — for a 3MF whose build structure
    doesn't produce one, this fails the exact same way regardless of
    load mode, so there's no SPOOL-side workaround, just a clearer label
    than the bare `'world'` str(KeyError(...)) repr). Anything else (a
    real bug, a malformed file) falls back to a generic label; the raw
    text is still available via the placeholder's title tooltip / the
    detail page's footer."""
    text = error_text or ""
    if "uncompressed" in text and "safety limit" in text:
        return "Mesh too large to render"
    if "build references" in text and "safety limit" in text:
        return "Too complex to render"
    if text == "'world'":
        return "Unsupported 3MF structure (trimesh limitation)"
    return "Render failed"


def format_date(dt):
    """Short, human-readable date — "Jul 28, 2026" — instead of the raw
    datetime's own verbose default str() (full timestamp + microseconds
    + timezone offset), for contexts where only the day actually
    matters (e.g. "created" on a project summary)."""
    if dt is None:
        return "—"
    return dt.strftime("%b %-d, %Y")


def format_duration(seconds):
    """Plain description of a duration ("5 minutes", "30 seconds") — for
    describing the configured rescan interval itself, as opposed to
    format_relative_time's "X ago" / "in X" framing for a specific point
    in time."""
    if seconds is None:
        return "—"
    if seconds < 60:
        return f"{seconds} second{'s' if seconds != 1 else ''}"
    minutes = round(seconds / 60)
    return f"{minutes} minute{'s' if minutes != 1 else ''}"


def format_relative_time(dt):
    """Short, human relative time ("3 minutes ago" / "in about 2 minutes")
    instead of an absolute clock time the reader has to mentally diff
    against "now" themselves — used for the /admin/status auto-sync
    panel's last/next-scan display, which self-refreshes every 4s anyway
    (see admin_status.html's htmx polling), so a server-computed relative
    value stays reasonably live without any client-side clock."""
    if dt is None:
        return "—"
    delta_seconds = (dt - datetime.now(timezone.utc)).total_seconds()
    future = delta_seconds > 0
    delta_seconds = abs(delta_seconds)
    if delta_seconds < 45:
        phrase = "a few seconds"
    elif delta_seconds < 90:
        phrase = "about a minute"
    elif delta_seconds < 3600:
        phrase = f"about {round(delta_seconds / 60)} minutes"
    elif delta_seconds < 7200:
        phrase = "about an hour"
    else:
        phrase = f"about {round(delta_seconds / 3600)} hours"
    return f"in {phrase}" if future else f"{phrase} ago"


def format_size(num_bytes):
    if num_bytes is None:
        return "—"
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"
