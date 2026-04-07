"""Tests for citation stripping."""

from readaloud.preprocessor.citations import (
    strip_numeric_bracket_citations,
    strip_parenthetical_citations,
)


def test_strip_single_numeric():
    assert strip_numeric_bracket_citations("As shown in [12].") == "As shown in."


def test_strip_multiple_numeric():
    assert strip_numeric_bracket_citations("As shown in [12, 15].") == "As shown in."


def test_strip_range_numeric():
    assert strip_numeric_bracket_citations("As shown in [12-15].") == "As shown in."
    assert strip_numeric_bracket_citations("As shown in [12\u201315].") == "As shown in."


def test_numeric_does_not_strip_other_brackets():
    # Brackets containing non-numeric text are preserved.
    out = strip_numeric_bracket_citations("[sic] this is correct")
    assert "[sic]" in out


def test_numeric_cleans_up_spacing():
    out = strip_numeric_bracket_citations("Before [12] , after.")
    assert "  " not in out
    assert "," in out


def test_parenthetical_author_year_single():
    out = strip_parenthetical_citations("As shown (Smith, 2023), the result.")
    assert "Smith" not in out
    assert "the result" in out


def test_parenthetical_et_al():
    out = strip_parenthetical_citations("As shown (Smith et al., 2023).")
    assert "Smith" not in out


def test_parenthetical_multiple():
    out = strip_parenthetical_citations(
        "As shown (Smith, 2023; Jones, 2020; Brown et al., 2024)."
    )
    assert "Smith" not in out
    assert "Jones" not in out
    assert "Brown" not in out


def test_parenthetical_preserves_non_citation():
    # (see Figure 3) has no year; must be preserved.
    out = strip_parenthetical_citations("The result (see Figure 3) is striking.")
    assert "see Figure 3" in out
    # (ibid.) has no author-year shape; preserved too.
    out2 = strip_parenthetical_citations("Repeating (ibid.) the claim.")
    assert "ibid." in out2


def test_parenthetical_off_by_default_in_pipeline():
    # Smoke check: the preprocessor module wires citations off by default.
    from readaloud.preprocessor import PreprocessorConfig, preprocess

    cfg = PreprocessorConfig()
    assert cfg.strip_parenthetical_citations is False
    sentences = preprocess("As shown (Smith, 2023), the result.", cfg)
    assert any("Smith" in s for s in sentences)
