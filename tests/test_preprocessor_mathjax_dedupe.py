"""Tests for MathJax / KaTeX selection deduplication."""

from __future__ import annotations

from pathlib import Path

from lexaloud.preprocessor.mathjax_dedupe import dedupe_mathjax_selection

FIXTURES = Path(__file__).parent / "fixtures"


def test_user_sample_deduplicated():
    """The real RL captured sample must be cleaned end-to-end."""
    raw = (FIXTURES / "mathjax_rl_sample.txt").read_text()
    out = dedupe_mathjax_selection(raw)

    # Every math symbol that was duplicated in the raw input now appears
    # exactly once.
    assert "x∈X x∈X" not in out
    assert "u∈U u∈U" not in out

    # The compact form survives exactly once.
    assert out.count("{X,U,T,R,ρ0}") == 1

    # Single-variable duplications were collapsed.
    assert " X X " not in out
    assert " x x " not in out
    assert " u u " not in out

    # Zero-width characters and NBSP are gone.
    assert "\u200b" not in out
    assert "\u00a0" not in out


def test_plain_prose_unchanged():
    text = "The cat sat on the mat."
    assert dedupe_mathjax_selection(text) == text


def test_ascii_code_unchanged():
    """Multi-line code with short lines must not be mangled."""
    code = "for i in range(3):\n    print(i)\n"
    assert dedupe_mathjax_selection(code) == code


def test_latex_source_unchanged():
    latex = r"$\frac{1}{2}$"
    assert dedupe_mathjax_selection(latex) == latex


def test_zero_width_stripped_without_newlines():
    """Normalization must happen BEFORE the no-newline fast path."""
    assert dedupe_mathjax_selection("x\u200by") == "xy"


def test_nbsp_normalized_without_newlines():
    """NBSP must become ASCII space even on single-line input."""
    assert dedupe_mathjax_selection("x\u00a0y") == "x y"


def test_empty_input():
    assert dedupe_mathjax_selection("") == ""


def test_reversed_order_is_noop():
    """Compact-before-stacked is NOT the real MathJax layout.

    The deduplicator only fires on the stacked-then-compact pattern it
    actually sees from MathJax/KaTeX selections. A hypothetical reversed
    input stays unchanged — documenting this is intentional.
    """
    text = "x∈X\nx\n∈\nX"
    out = dedupe_mathjax_selection(text)
    # Both forms survive — the function is a no-op on this layout.
    assert "x∈X" in out
    assert "\n∈\n" in out


def test_multi_char_stacked_dedup():
    """Core positive case: stacked run followed by compact form."""
    text = "elements\nx\n∈\nX\nx∈X, for instance"
    out = dedupe_mathjax_selection(text)
    assert "x∈X" in out
    assert "\n∈\n" not in out


def test_single_var_dedup():
    text = "Here \nX\nX stands"
    assert dedupe_mathjax_selection(text) == "Here X stands"


def test_single_char_line_no_dup_preserved():
    """A single-char line that is NOT followed by a compact duplicate stays."""
    text = "Set A contains\nx\nand nothing else."
    out = dedupe_mathjax_selection(text)
    assert "x" in out


def test_no_false_positive_on_initials():
    """'J\\nK\\nRowling' must not be treated as a stacked math block."""
    text = "Written by\nJ\nK\nRowling in 1997."
    out = dedupe_mathjax_selection(text)
    assert "J" in out and "K" in out and "Rowling" in out


# --- M1 regression: pure ASCII-letter stacks are not real MathJax ---


def test_pure_letter_stacked_block_not_deleted():
    """Letter-only stacked lines followed by a word whose prefix matches
    must NOT be treated as a MathJax duplicate. Real MathJax stacks
    contain operators / digits / Greek; all-ASCII-letter stacks are
    almost certainly outline or list fragments."""
    text = "Set:\na\nb\nabc is the answer."
    out = dedupe_mathjax_selection(text)
    assert "a" in out
    assert "b" in out
    assert "abc is the answer." in out


def test_digit_only_stacked_block_still_deduped():
    """A digit-only stacked block IS legitimate MathJax (subscript
    rendering), so the guard must not over-block: digits are not
    ASCII letters, so the guard lets this through and the block is
    deduped."""
    text = "var\n1\n2\n12 is big."
    out = dedupe_mathjax_selection(text)
    assert "12 is big." in out
    # The stacked digit lines should be gone (compact form '12' survives)
    assert "\n1\n2\n" not in out
