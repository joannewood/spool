import re
from urllib.parse import unquote_plus

_PERCENT_ENCODED_RE = re.compile(r"%[0-9A-Fa-f]{2}")
_SEPARATOR_RUN_RE = re.compile(r"[_\-]+")
_KIT_SUFFIX_RE = re.compile(r"\bmodel\s*files?\b|\bprint\s*files?\b", re.IGNORECASE)
_STANDALONE_ID_RE = re.compile(r"\b\d{5,}\b")
_WHITESPACE_RUN_RE = re.compile(r"\s+")
# "1" + separator + a short number is the standard Thingiverse/Printables
# way of writing a scale ratio in a folder name — either with a real
# separator ("1_12", "1-6" -> already collapsed to a space by the time
# this runs) or fused with none at all ("125" = 1/25, "110th" = 1/10th,
# ordinal suffix optional). One single regex covers both forms in one
# pass *on purpose*: running a "1 12" pattern and a "125" pattern as two
# separate re.sub calls lets the second one re-scan the first one's own
# output and misfire (e.g. "1 12 scale" -> correctly "1/12 scale", but a
# second pass then sees the trailing "12 scale" inside that result and
# "fixes" it again into "1/1/2 scale") — a single pass can't do that,
# since re.sub finds all matches in the *original* text before any
# substitution happens.
#
# The fused form only converts when the literal word "scale" immediately
# follows (never invented — see _replace_scale) since a bare fused number
# is too ambiguous ("112th Anniversary", "125" as a plain part number).
# The separated form doesn't need that anchor, since "1 12" alone already
# reads unambiguously as a ratio in this domain. Either way "scale" is
# preserved when already present, never invented when it isn't:
# "1_12_US_Mail_box" -> "1/12 US Mail box", "1_12_scale_x" -> "1/12 scale x".
_SCALE_RE = re.compile(r"\b1( ?)(\d{1,3})(st|nd|rd|th)?( scale)?\b", re.IGNORECASE)


def _replace_scale(match):
    had_space, denominator, suffix, scale_word = match.group(1), match.group(2), match.group(3) or "", match.group(4)
    if not had_space:
        # Fused form — only touch it with the "scale" anchor present, and
        # reject a "0" denominator ("10 scale" parsed as "1" + "0" would
        # give the nonsensical "1/0 scale"; a real 1/10 scale is written
        # fused as "110", not "10").
        if not scale_word or denominator.startswith("0"):
            return match.group(0)
    return f"1/{denominator}{suffix}{scale_word or ''}"


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
    "1_12"-, "125"-, or "110th"-style scale ratio, and a long standalone
    numeric asset id (Thingiverse/Printables). Never *invents* the word
    "scale" — "1_12_US_Mail_box" (no "scale" anywhere in the name)
    becomes "1/12 US Mail box", only "1_12_scale_bookshelf" becomes
    "1/12 scale bookshelf". A fused number with no separator at all (e.g.
    the "112" in "doll-house-kitchen-sink-112-model_files") is left alone
    rather than guessed at, *unless* the literal word "scale" immediately
    follows it ("125-scale-boat" -> "1/25 scale boat",
    "110th-scale-fire-hydrant" -> "1/10th scale fire hydrant") — that
    anchor is unambiguous enough to touch even fused, whereas a bare
    fused number isn't. A standalone run of 5+ digits, which reads
    unambiguously as an asset id, gets stripped outright regardless.
    Finally, the first letter of each word is uppercased — but only the
    first letter; the rest of each word is left
    exactly as it already was, so an existing acronym or mixed-case brand
    token ("USB", "SaberPack4") isn't lowercased into something wrong the
    way a full title-case pass would. This is a *suggestion* a human
    reviews before applying (see the /projects/bulk-rename page), not an
    automatic rewrite — the heuristic will occasionally be wrong for a
    given name, same as any pattern-based text cleanup."""
    text = clean_name(name)
    text = _SEPARATOR_RUN_RE.sub(" ", text)
    text = _SCALE_RE.sub(_replace_scale, text)
    text = _KIT_SUFFIX_RE.sub(" ", text)
    text = _STANDALONE_ID_RE.sub(" ", text)
    text = _WHITESPACE_RUN_RE.sub(" ", text).strip()
    return " ".join(word[:1].upper() + word[1:] for word in text.split(" "))
