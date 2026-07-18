from common.text import clean_name  # noqa: F401 — re-exported as a Jinja filter, see main.py


def ext_class(ext):
    """CSS class for the extension color-coding on grid cards — .step/.stp
    share one class since they're the same format, just spelled two ways."""
    ext = (ext or "").lower()
    if ext in (".step", ".stp"):
        return "ext-step"
    return "ext-" + ext.lstrip(".")


def format_size(num_bytes):
    if num_bytes is None:
        return "—"
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"
