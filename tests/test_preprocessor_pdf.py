"""Tests for PDF-paste cleanup."""

from lexaloud.preprocessor.pdf_cleanup import clean_pdf_paste


def test_dehyphenates_broken_word_across_lines():
    text = "The agent com-\npleted its task."
    assert "completed" in clean_pdf_paste(text)
    assert "com-pleted" not in clean_pdf_paste(text)


def test_does_not_dehyphenate_hyphenated_compounds():
    # "state-of-the-art" should NOT be joined because there's no linebreak
    # inside the hyphen.
    text = "This is state-of-the-art technology."
    out = clean_pdf_paste(text)
    assert "state-of-the-art" in out


def test_unwraps_lines_within_paragraph():
    text = (
        "Reading-while-listening is a technique\n"
        "with a contested empirical basis.\n"
    )
    out = clean_pdf_paste(text)
    assert "Reading-while-listening is a technique with a contested" in out
    assert "\n" not in out.split("\n\n")[0]  # paragraph is one line


def test_preserves_paragraph_breaks():
    text = (
        "First paragraph.\n"
        "Same paragraph continued.\n"
        "\n"
        "Second paragraph starts here.\n"
    )
    out = clean_pdf_paste(text)
    paragraphs = out.split("\n\n")
    assert len(paragraphs) == 2
    assert "First paragraph." in paragraphs[0]
    assert "Same paragraph" in paragraphs[0]
    assert "Second paragraph" in paragraphs[1]


def test_normalizes_curly_quotes_and_nbsp():
    text = "He said \u201chello\u201d to\u00a0everyone."
    out = clean_pdf_paste(text)
    assert '"hello"' in out
    # NBSP was replaced by space
    assert "to everyone" in out


def test_collapses_multi_space():
    text = "word1    word2       word3"
    out = clean_pdf_paste(text)
    assert out == "word1 word2 word3"


def test_does_not_drop_empty_input():
    assert clean_pdf_paste("") == ""
