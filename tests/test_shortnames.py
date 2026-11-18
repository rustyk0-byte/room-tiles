"""Short-name suggestions (shortnames.py): per-language rules."""

from custom_components.room_tiles.shortnames import fits, rules_for, set_language, suggest


def test_a_name_that_fits_is_kept():
    assert suggest("Laundry2") == ("Laundry2", False)


def test_english_abbreviations_then_vowels_then_words():
    assert suggest("Primary Bathroom Lights", "en") == ("Prmry Bath Lts", True)
    assert suggest("Garage Door Opener", "en") == ("Grg Door Opener", True)  # keeps all three words
    # dropping vowels doesn't save a word here: the words stay whole
    assert suggest("Kitchen Island Pendants", "en") == ("Kit Island", True)
    for full in ("Living Room Ceiling Fan", "Front Porch String Lights"):
        short, review = suggest(full, "en")
        assert fits(short) and review


def test_other_languages_never_drop_vowels_but_know_english_names():
    """English names are common in any home (manufacturers' defaults): the
    English abbreviations apply after the language's own - whole words only,
    so the language's own words are never touched; no vowel dropping."""
    assert rules_for("de").drop_vowels is False
    assert suggest("Garage Door Opener", "de") == ("Garage Door", True)
    assert suggest("Kitchen Island Pendants", "fr") == ("Kit Island", True)
    assert suggest("Master Bedroom Lights", "de") == ("Master Bed Lts", True)
    assert suggest("Licht Wohnzimmer Links", "de") == ("Licht Wohnzi. L", True)  # its own words, as before
    # a language without rules: the generic ones
    assert rules_for("ja").abbreviations == ()


def test_each_language_uses_its_own_words():
    assert suggest("Lámpara Habitación Principal", "es") == ("Lámp. Hab.", True)
    # only as much as needed: "SdB" alone makes it fit
    assert suggest("Plafonnier salle de bain", "fr") == ("Plafonnier SdB", True)
    assert suggest("Lampada Soggiorno Sinistra", "it") == ("Lamp. Sogg. Sx", True)
    assert suggest("Licht Wohnzimmer Links", "de") == ("Licht Wohnzi. L", True)
    assert suggest("Luminária Sala de estar", "pt") == ("Luminária Sala", True)
    assert suggest("Slaapkamer Verlichting", "nl") == ("Slaapk. Licht", True)
    for lang in ("es", "fr", "it", "de", "pt", "nl"):
        assert rules_for(lang).drop_vowels is False


def test_ha_language_is_followed():
    set_language("en-GB")
    assert rules_for().drop_vowels is True
    set_language("de")
    assert rules_for().drop_vowels is False
    set_language("en")


def test_accented_letters_measure_like_their_base_letters():
    from custom_components.room_tiles.shortnames import width_px

    assert width_px("Habitación") == width_px("Habitacion")
    assert width_px("Spülen") == width_px("Spulen")


def test_suggestions_capitalise_every_word_in_english():
    """Short names look alike whatever the entity names were."""
    from custom_components.room_tiles.shortnames import capitalise, suggest

    assert suggest("back patio")[0] == "Back Patio"
    assert suggest("patio door") == ("Patio Door", False)  # only the case changed: no review
    assert suggest("living room TV")[0] == "Living Room TV"  # capitals stay
    assert capitalise("my iPad stand") == "My iPad Stand"
    assert capitalise("luz de cocina", "first") == "Luz de cocina"
    assert capitalise("bañera grande") == "Bañera Grande"  # accents too


def test_other_languages_capitalise_the_first_letter():
    from custom_components.room_tiles.shortnames import rules_for

    assert rules_for("en").case == "words" and rules_for("nl").case == "words"
    assert {rules_for(lang).case for lang in ("de", "es", "fr", "it", "pt")} == {"first"}


def test_small_words_stay_lower_unless_first():
    from custom_components.room_tiles.shortnames import suggest

    assert suggest("back of house")[0] == "Back of House"
    assert suggest("the den")[0] == "The Den"  # first word: capital
