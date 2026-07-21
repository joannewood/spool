import re
from urllib.parse import unquote_plus

_PERCENT_ENCODED_RE = re.compile(r"%[0-9A-Fa-f]{2}")
_SEPARATOR_RUN_RE = re.compile(r"[_\-]+")
_KIT_SUFFIX_RE = re.compile(r"\bmodel\s*files?\b|\bprint\s*files?\b", re.IGNORECASE)
_STANDALONE_ID_RE = re.compile(r"\b\d{5,}\b")
_WHITESPACE_RUN_RE = re.compile(r"\s+")
# "1" + separator + a short number is the standard Thingiverse/Printables
# way of writing a scale ratio (1_12, 1-6, 1_24...) in a folder name — run
# *after* separators are already collapsed to single spaces, so it doesn't
# matter whether the source used "_" or "-". Also swallows a following
# "scale" word so "1_12_scale_x" doesn't end up as "1/12 scale scale x".
# A false positive is possible (a literal "1 12 widgets" meaning a
# quantity, not a ratio) but scale notation is by far the dominant reading
# in this domain, and this is a reviewed suggestion, not an automatic
# rewrite.
_SCALE_NOTATION_RE = re.compile(r"\b1 (\d{1,3})(?: scale)?\b", re.IGNORECASE)


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


def suggest_clean_project_name(name):
    """A best-effort cleanup suggestion for a folder-derived project name —
    the raw folder name a downloaded kit unpacks to is often full of
    hyphens/underscores standing in for spaces, a "model_files"/
    "print_files" container-folder suffix (the same download convention
    `_GENERIC_CONTAINER_NAMES` already works around elsewhere), a
    "1_12"-style scale ratio, and a long standalone numeric asset id
    (Thingiverse/Printables). A short number *not* immediately preceded by
    a lone "1" separator (e.g. the "112" in "doll-house-kitchen-sink-112-
    model_files" — fused digits, no separator, genuinely ambiguous) is
    left alone rather than guessed at; only a run of 5+ digits, which
    reads unambiguously as an asset id, gets stripped outright. This is a
    *suggestion* a human reviews before applying (see the
    /projects/bulk-rename page), not an automatic rewrite — the heuristic
    will occasionally be wrong for a given name, same as any
    pattern-based text cleanup."""
    text = clean_name(name)
    text = _SEPARATOR_RUN_RE.sub(" ", text)
    text = _SCALE_NOTATION_RE.sub(lambda m: f"1/{m.group(1)} scale", text)
    text = _KIT_SUFFIX_RE.sub(" ", text)
    text = _STANDALONE_ID_RE.sub(" ", text)
    return _WHITESPACE_RUN_RE.sub(" ", text).strip()
