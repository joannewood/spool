from common.text import clean_name


def test_clean_name_decodes_percent_encoding():
    assert clean_name("Anker%20Nano%20Bracket.stl") == "Anker Nano Bracket.stl"


def test_clean_name_decodes_plus_when_no_real_spaces():
    assert clean_name("AAA+battery+tray+mk2.stl") == "AAA battery tray mk2.stl"


def test_clean_name_leaves_real_spaces_and_plusses_alone():
    assert clean_name("C++ Project") == "C++ Project"


def test_clean_name_leaves_plain_names_alone():
    assert clean_name("widget.stl") == "widget.stl"


def test_clean_name_handles_empty_and_none():
    assert clean_name("") == ""
    assert clean_name(None) is None


def test_clean_name_handles_mixed_percent_and_plus():
    assert clean_name("Double%20holder+20mm.STL") == "Double holder 20mm.STL"
