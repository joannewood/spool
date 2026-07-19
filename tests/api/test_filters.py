from spool_api.filters import ext_class, format_size, thumb_url


def test_thumb_url_none_thumbnail_path():
    assert thumb_url(None) is None
    assert thumb_url(None, "somehash") is None


def test_thumb_url_appends_content_hash_prefix():
    assert thumb_url("42.png", "abcdef1234567890") == "/thumbnails/42.png?v=abcdef12"


def test_thumb_url_no_content_hash_no_query_string():
    # sidecars have no content_hash — never re-rendered in place, nothing
    # to bust, so the plain stable URL is fine.
    assert thumb_url("sidecar-9.jpg") == "/thumbnails/sidecar-9.jpg"
    assert thumb_url("sidecar-9.jpg", None) == "/thumbnails/sidecar-9.jpg"
