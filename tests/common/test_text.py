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
    assert suggest_clean_project_name("towel-hanger-model_files") == "Towel Hanger"


def test_suggest_clean_project_name_converts_separators_to_spaces():
    assert suggest_clean_project_name("Hex3D_SaberPack4_Shroud_Extensions") == "Hex3D SaberPack4 Shroud Extensions"


def test_suggest_clean_project_name_strips_long_standalone_asset_id():
    assert suggest_clean_project_name("Desktop Mini conveyor - 5415144") == "Desktop Mini Conveyor"
    assert suggest_clean_project_name("4635682_Credit_card_cutlery") == "Credit Card Cutlery"


def test_suggest_clean_project_name_keeps_short_meaningful_numbers():
    # a 3-digit number plausibly means something (e.g. a 1/12 scale marker)
    # and isn't the kind of long asset id this heuristic targets.
    assert suggest_clean_project_name("doll-house-kitchen-sink-112-model_files") == "Doll House Kitchen Sink 112"


def test_suggest_clean_project_name_leaves_already_clean_names_alone():
    assert suggest_clean_project_name("Dry Box Caps") == "Dry Box Caps"


def test_suggest_clean_project_name_capitalizes_every_word_including_connectors():
    # "capitalize the first letter of each word" applies uniformly, with
    # no exception list for articles/prepositions — "of" becomes "Of".
    assert suggest_clean_project_name("4th of July Uncle Sam Hat") == "4th Of July Uncle Sam Hat"


def test_suggest_clean_project_name_preserves_acronyms_and_mixed_case():
    # Only the first letter of each word is touched — an already-uppercase
    # acronym or a mixed-case brand token isn't lowercased the way a real
    # str.title() call would ("USB" -> "Usb", "SaberPack4" -> "Saberpack4").
    assert suggest_clean_project_name("ryobi-usb-lithium-model_files") == "Ryobi Usb Lithium"
    assert suggest_clean_project_name("nespresso-VertuoNext-model_files") == "Nespresso VertuoNext"


def test_suggest_clean_project_name_combines_with_percent_decoding():
    assert suggest_clean_project_name("Anker%20Nano-model_files") == "Anker Nano"


def test_suggest_clean_project_name_expands_scale_notation_without_inventing_the_word_scale():
    # "scale" doesn't appear anywhere in the source name, so it isn't added.
    assert suggest_clean_project_name("1_12_US_Mail_box_3520864") == "1/12 US Mail Box"


def test_suggest_clean_project_name_scale_notation_preserves_existing_scale_word_without_doubling():
    assert suggest_clean_project_name("1_12_scale_bookshelf_4218879 (1)") == "1/12 Scale Bookshelf (1)"


def test_suggest_clean_project_name_expands_fused_ordinal_scale_notation():
    assert suggest_clean_project_name("110th-scale-fire-hydrant-model_files") == "1/10th Scale Fire Hydrant"


def test_suggest_clean_project_name_leaves_fused_ordinal_alone_without_scale_anchor():
    # No literal "scale" following — too ambiguous to touch (could be a
    # real ordinal, e.g. an anniversary), so left exactly as-is (beyond
    # the first-letter capitalization already applied to every word).
    assert suggest_clean_project_name("110th anniversary model") == "110th Anniversary Model"


def test_suggest_clean_project_name_fused_digits_are_not_treated_as_scale_notation():
    # No separator between "1" and "12" here — genuinely ambiguous (could
    # be a part number, a size), so left alone rather than guessed at.
    assert suggest_clean_project_name("doll-house-kitchen-sink-112-model_files") == "Doll House Kitchen Sink 112"
