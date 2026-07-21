from common.text import clean_name, suggest_clean_project_name


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


# ---- suggest_clean_project_name --------------------------------------------

def test_suggest_clean_project_name_strips_model_files_suffix():
    assert suggest_clean_project_name("towel-hanger-model_files") == "towel hanger"


def test_suggest_clean_project_name_converts_separators_to_spaces():
    assert suggest_clean_project_name("Hex3D_SaberPack4_Shroud_Extensions") == "Hex3D SaberPack4 Shroud Extensions"


def test_suggest_clean_project_name_strips_long_standalone_asset_id():
    assert suggest_clean_project_name("Desktop Mini conveyor - 5415144") == "Desktop Mini conveyor"
    assert suggest_clean_project_name("4635682_Credit_card_cutlery") == "Credit card cutlery"


def test_suggest_clean_project_name_keeps_short_meaningful_numbers():
    # a 3-digit number plausibly means something (e.g. a 1/12 scale marker)
    # and isn't the kind of long asset id this heuristic targets.
    assert suggest_clean_project_name("doll-house-kitchen-sink-112-model_files") == "doll house kitchen sink 112"


def test_suggest_clean_project_name_leaves_already_clean_names_alone():
    assert suggest_clean_project_name("Dry Box Caps") == "Dry Box Caps"
    assert suggest_clean_project_name("4th of July Uncle Sam Hat") == "4th of July Uncle Sam Hat"


def test_suggest_clean_project_name_combines_with_percent_decoding():
    assert suggest_clean_project_name("Anker%20Nano-model_files") == "Anker Nano"


def test_suggest_clean_project_name_expands_scale_notation():
    assert suggest_clean_project_name("1_12_US_Mail_box_3520864") == "1/12 scale US Mail box"


def test_suggest_clean_project_name_scale_notation_does_not_double_up_the_word_scale():
    assert suggest_clean_project_name("1_12_scale_bookshelf_4218879 (1)") == "1/12 scale bookshelf (1)"


def test_suggest_clean_project_name_fused_digits_are_not_treated_as_scale_notation():
    # No separator between "1" and "12" here — genuinely ambiguous (could
    # be a part number, a size), so left alone rather than guessed at.
    assert suggest_clean_project_name("doll-house-kitchen-sink-112-model_files") == "doll house kitchen sink 112"
