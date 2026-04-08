"""Regression tests for bugs flagged by the preprocessor review agent.

Covers:
- Unicode hyphen / soft-hyphen de-hyphenation
- _unwrap_lines preserving newlines after terminal punctuation
- Capitalized Latin abbreviations (Cf., Ibid., E.g., I.e., Vs.)
- Parenthetical citations accepting "and" connector and no-comma variant
- Non-ASCII surnames in parenthetical citations
- pysbd thread safety under concurrent calls
"""

from __future__ import annotations

import concurrent.futures

from lexaloud.preprocessor import preprocess
from lexaloud.preprocessor.abbreviations import expand_latin_abbreviations
from lexaloud.preprocessor.citations import strip_parenthetical_citations
from lexaloud.preprocessor.pdf_cleanup import _unwrap_lines, clean_pdf_paste
from lexaloud.preprocessor.segmenter import split_sentences

# ---------- Unicode hyphens ----------


def test_dehyphenates_u2010_hyphen_at_line_break():
    text = "The agent com\u2010\npleted its task."
    out = clean_pdf_paste(text)
    assert "completed" in out
    assert "\u2010" not in out


def test_strips_soft_hyphen_at_line_break():
    # U+00AD is an invisible hint to the renderer; it should never be
    # spoken. After normalization the word should be joined.
    text = "The agent com\u00ad\npleted its task."
    out = clean_pdf_paste(text)
    assert "completed" in out
    assert "\u00ad" not in out


def test_dehyphenate_avoids_compound_word_tail():
    # `state-of-the-\nart` is a compound where the last hyphen accidentally
    # landed at a line break. The lookbehind `(?<![a-z\-])` prevents the
    # regex from merging `the-\nart` because the captured `the` is
    # preceded by `-`.
    text = "This is state-of-the-\nart technology."
    out = clean_pdf_paste(text)
    assert "state-of-the-art" in out
    assert "theart" not in out


# ---------- _unwrap_lines preserves terminal-punctuation boundaries ----------


def test_unwrap_preserves_terminal_punctuation_boundary():
    text = "First sentence.\nSecond sentence."
    out = _unwrap_lines(text)
    # A single newline survives between the two sentences.
    assert "First sentence.\nSecond sentence." in out


def test_unwrap_joins_continuation_lines_with_space():
    text = "The agent began\nits long journey"
    out = _unwrap_lines(text)
    assert "The agent began its long journey" in out


# ---------- Capitalized Latin abbreviations ----------


def test_sentence_initial_cf_expanded():
    assert "compare" in expand_latin_abbreviations("Cf. Smith 2020.")


def test_sentence_initial_ibid_expanded():
    assert "same source" in expand_latin_abbreviations("Ibid., p. 42")


def test_sentence_initial_e_g_expanded():
    assert "for example" in expand_latin_abbreviations("E.g., MAPPO.")


def test_sentence_initial_i_e_expanded():
    assert "that is" in expand_latin_abbreviations("I.e., a monoid.")


def test_vs_capitalized_expanded():
    assert "versus" in expand_latin_abbreviations("Vs. earlier work.")


# ---------- Parenthetical citations ----------


def test_paren_citation_with_and_connector():
    out = strip_parenthetical_citations("As shown (Smith and Jones, 2023).")
    assert "Smith" not in out
    assert "Jones" not in out


def test_paren_citation_no_comma_variant():
    out = strip_parenthetical_citations("As shown (Smith 2020) the result.")
    assert "Smith" not in out


def test_paren_citation_accented_surname():
    out = strip_parenthetical_citations("See (García-Márquez, 2020).")
    assert "García" not in out


def test_paren_preserves_non_citation():
    out = strip_parenthetical_citations("The result (see Figure 3) is striking.")
    assert "see Figure 3" in out


# ---------- pysbd thread safety ----------


def test_pysbd_is_thread_safe_under_concurrent_calls():
    """With the module-level lock, concurrent calls must not corrupt state.

    We run 16 workers x 50 calls each, each segmenting a known-long passage,
    and assert every call returns the expected sentence count.
    """
    text = "First sentence. Second sentence! Third sentence? Fourth sentence. Fifth sentence."
    expected_count = len(split_sentences(text))

    def _work() -> int:
        return len(split_sentences(text))

    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        futures = [pool.submit(_work) for _ in range(16 * 50)]
        counts = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert all(c == expected_count for c in counts), (
        f"pysbd segmentation produced inconsistent counts under concurrency: "
        f"expected {expected_count}, got {set(counts)}"
    )


# ---------- full pipeline sanity with new abbreviations ----------


def test_full_pipeline_handles_capitalized_cf_at_sentence_start():
    text = "Consider the earlier result. Cf. Smith 2020."
    sentences = preprocess(text)
    joined = " ".join(sentences)
    assert "compare" in joined
    assert "Cf." not in joined
