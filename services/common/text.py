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
# matter whether the source used "_" or "-". The optional group captures a
# following "scale" word (if present) so it's preserved, not doubled — but
# never *invented*: "1_12_US_Mail_box" (no "scale" anywhere) becomes
# "1/12 US Mail box", not "1/12 scale US Mail box". A false positive is
# possible (a literal "1 12 widgets" meaning a quantity, not a ratio) but
# scale notation is by far the dominant reading in this domain, and this
# is a reviewed suggestion, not an automatic rewrite.
_SCALE_NOTATION_RE = re.compile(r"\b1 (\d{1,3})( scale)?\b", re.IGNORECASE)
# The same ratio, but fused with no separator at all and written with an
# ordinal suffix — "110th-scale-fire-hydrant" means 1/10th scale, "116th"
# means 1/16th. Only recognized when "scale" literally follows, same
# never-invent-the-word rule as above — without that anchor a fused
# ordinal is too ambiguous to touch at all (e.g. "112th Anniversary").
_FUSED_ORDINAL_SCALE_RE = re.compile(r"\b1(\d{1,2})(st|nd|rd|th) scale\b", re.IGNORECASE)


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
    "1_12"- or "110th"-style scale ratio, and a long standalone numeric
    asset id (Thingiverse/Printables). Never *invents* the word "scale" —
    "1_12_US_Mail_box" (no "scale" anywhere in the name) becomes
    "1/12 US Mail box", only "1_12_scale_bookshelf" becomes
    "1/12 scale bookshelf". A fused number with no separator at all (e.g.
    the "112" in "doll-house-kitchen-sink-112-model_files") is left alone
    rather than guessed at, *unless* it's an ordinal immediately followed
    by the literal word "scale" ("110th-scale-fire-hydrant" -> "1/10th
    scale fire hydrant") — that combination is unambiguous enough to
    touch even fused, whereas a bare fused number isn't. A standalone run
    of 5+ digits, which reads unambiguously as an asset id, gets stripped
    outright regardless. Finally, the first letter of each word is
    uppercased — but only the first letter; the rest of each word is left
    exactly as it already was, so an existing acronym or mixed-case brand
    token ("USB", "SaberPack4") isn't lowercased into something wrong the
    way a full title-case pass would. This is a *suggestion* a human
    reviews before applying (see the /projects/bulk-rename page), not an
    automatic rewrite — the heuristic will occasionally be wrong for a
    given name, same as any pattern-based text cleanup."""
    text = clean_name(name)
    text = _SEPARATOR_RUN_RE.sub(" ", text)
    text = _FUSED_ORDINAL_SCALE_RE.sub(lambda m: f"1/{m.group(1)}{m.group(2)} scale", text)
    text = _SCALE_NOTATION_RE.sub(lambda m: f"1/{m.group(1)}{' scale' if m.group(2) else ''}", text)
    text = _KIT_SUFFIX_RE.sub(" ", text)
    text = _STANDALONE_ID_RE.sub(" ", text)
    text = _WHITESPACE_RUN_RE.sub(" ", text).strip()
    return " ".join(word[:1].upper() + word[1:] for word in text.split(" "))
