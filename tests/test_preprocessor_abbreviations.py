"""Tests for Latin abbreviation expansion."""

from lexaloud.preprocessor.abbreviations import expand_latin_abbreviations


def test_et_al_lowercase():
    assert "and colleagues" in expand_latin_abbreviations("Smith et al. found that...")


def test_et_al_capitalized():
    assert "and colleagues" in expand_latin_abbreviations("Smith Et al. said...")


def test_eg_with_and_without_comma():
    assert "for example," in expand_latin_abbreviations("Many techniques, e.g., MAPPO")
    assert "for example," in expand_latin_abbreviations("Many e.g. MAPPO")


def test_ie_with_comma():
    assert "that is," in expand_latin_abbreviations("A monoid, i.e., a set with an operation")


def test_cf_viz_ibid_nb():
    assert "compare" in expand_latin_abbreviations("See cf. Smith 2020")
    assert "namely" in expand_latin_abbreviations("Two options viz. A and B")
    assert "same source" in expand_latin_abbreviations("See ibid.")
    assert "note well" in expand_latin_abbreviations("N.B. this important point")
    assert "note well" in expand_latin_abbreviations("NB. this important point")


def test_vs_expansion():
    assert "versus" in expand_latin_abbreviations("CPU vs. GPU comparison")


def test_no_false_positives_in_ordinary_words():
    # "The vs" shouldn't trigger because no trailing period.
    text = "The eg hypothesis."
    out = expand_latin_abbreviations(text)
    assert "for example" not in out
