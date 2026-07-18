import re
from urllib.parse import unquote_plus

_PERCENT_ENCODED_RE = re.compile(r"%[0-9A-Fa-f]{2}")


def clean_name(name):
    """Some downloaded files/folders keep literal URL encoding in their
    name (a "%20" for space, or a "+" for space from a query-string
    filename, both common in Thingiverse/Printables downloads extracted
    without decoding) — cosmetic only, applied wherever a name is
    displayed, never touching the real file/folder on disk. Decodes when
    the name contains a %XX escape, or a "+" with no real space already
    present (guards against mangling a name that intentionally has a "+"
    in it, which would only misfire if it also happened to have zero
    spaces)."""
    if not name:
        return name
    looks_encoded = _PERCENT_ENCODED_RE.search(name) or ("+" in name and " " not in name)
    return unquote_plus(name) if looks_encoded else name
