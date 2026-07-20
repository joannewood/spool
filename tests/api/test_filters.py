from spool_api.filters import ext_class, format_size, render_error_label, thumb_url


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


def test_render_error_label_oversized_mesh():
    error = (
        "3MF's inner mesh data is 99,000,000 bytes uncompressed, over the "
        "12,000,000-byte safety limit — skipped without attempting to render"
    )
    assert render_error_label(error) == "Mesh too large to render"


def test_render_error_label_excessive_components():
    error = (
        "3MF has 166 <item>/<component> build references, over the "
        "60-reference safety limit — skipped without attempting to render"
    )
    assert render_error_label(error) == "Too complex to render"


def test_render_error_label_falls_back_for_unrecognized_errors():
    assert render_error_label("'world'") == "Render failed"
    assert render_error_label(None) == "Render failed"
    assert render_error_label("") == "Render failed"
