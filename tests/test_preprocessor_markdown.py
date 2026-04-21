"""Tests for markdown stripping for TTS."""

from __future__ import annotations

from lexaloud.preprocessor.markdown_strip import markdown_to_tts_prose


def _canon(s: str) -> str:
    """Whitespace-robust canonical form for assertions."""
    return " ".join(s.split())


def test_plain_prose_unchanged_fast_path():
    text = "The cat sat on the mat."
    assert markdown_to_tts_prose(text) == text


def test_headings_become_paragraphs():
    out = markdown_to_tts_prose("# Intro\n\nBody paragraph.")
    assert "#" not in out
    assert "Intro" in out
    assert "Body paragraph" in out
    # Heading ends with a period so the sentence splitter sees a break.
    assert "Intro." in out


def test_emphasis_stripped():
    out = markdown_to_tts_prose("This is **bold** and *italic* and ~~old~~ text.")
    assert "bold" in out
    assert "italic" in out
    assert "old" in out
    for marker in ("**", "~~", "*", "_"):
        assert marker not in out


def test_ordered_list():
    out = markdown_to_tts_prose("1. First item\n2. Second item\n3. Third item")
    canon = _canon(out)
    assert "First item" in canon
    assert "Second item" in canon
    assert "Third item" in canon
    assert "1." in canon
    assert "2." in canon


def test_unordered_list():
    out = markdown_to_tts_prose("- Apple\n- Banana\n- Cherry")
    assert "Apple" in out
    assert "Banana" in out
    assert "Cherry" in out
    assert "\n- " not in out
    assert out.strip()[0] != "-"


def test_code_block_skipped_by_default():
    md = "Before.\n\n```python\ndef foo():\n    pass\n```\n\nAfter."
    out = markdown_to_tts_prose(md)
    assert "Code block omitted" in out
    assert "Before" in out
    assert "After" in out


def test_code_block_kept_when_requested():
    md = "```python\ndef foo():\n    pass\n```"
    out = markdown_to_tts_prose(md, skip_code_blocks=False)
    assert "Code block omitted" not in out
    # Content substrings appear — we don't care about exact formatting.
    assert "def foo" in out
    assert "pass" in out


def test_inline_code_stripped_in_real_markdown():
    """Inline backticks ARE stripped when the document has block-level
    markdown markers — the token walker handles them."""
    md = "# Debugging\n\nUse `print(x)` to inspect values."
    out = markdown_to_tts_prose(md)
    assert "print(x)" in out
    assert "`" not in out


def test_inline_code_only_passes_through():
    """Inline code alone is not enough to trigger parsing (avoids false
    positives on prose that mentions `` `x` `` as a variable)."""
    text = "Use `print(x)` to debug."
    assert markdown_to_tts_prose(text) == text


def test_table_with_headers_as_labels():
    md = "| Name | Age |\n|------|-----|\n| Alice | 30 |\n| Bob | 25 |"
    out = markdown_to_tts_prose(md)
    canon = _canon(out)
    assert "Name: Alice" in canon
    assert "Age: 30" in canon
    assert "Name: Bob" in canon
    assert "Age: 25" in canon


def test_link_text_only():
    out = markdown_to_tts_prose("See the [documentation](https://example.com/docs) for details.")
    assert "documentation" in out
    assert "https" not in out
    assert "example.com" not in out


def test_image_alt_text():
    out = markdown_to_tts_prose("Before. ![chart](/img/x.png). After.")
    assert "Image: chart" in out
    assert "/img/x.png" not in out
    # Must not produce a double period. The image emitter no longer
    # appends its own "." so the surrounding prose period is preserved.
    assert ".." not in out


def test_blockquote_prefix():
    out = markdown_to_tts_prose("> This is a quoted sentence.")
    canon = _canon(out)
    assert "Quote" in canon
    assert "This is a quoted sentence" in canon


def test_horizontal_rule_becomes_break():
    md = "Paragraph one.\n\n---\n\nParagraph two."
    out = markdown_to_tts_prose(md)
    assert "Paragraph one" in out
    assert "Paragraph two" in out
    assert "---" not in out


def test_html_stripped():
    out = markdown_to_tts_prose("Hello <span>world</span>.")
    assert "Hello" in out
    assert "world" in out
    assert "<" not in out
    assert ">" not in out


def test_strikethrough_stripped():
    out = markdown_to_tts_prose("Before ~~obsolete~~ now fresh.")
    assert "obsolete" in out
    assert "~~" not in out


# --- regression: technical prose must NOT be parsed as markdown ---


def test_single_asterisk_emphasis_in_prose_passes_through():
    """``Compute a*b*c in the loop.`` must not collapse to ``abc``."""
    text = "Compute a*b*c in the loop."
    assert markdown_to_tts_prose(text) == text


def test_dunder_init_not_emphasized():
    """``__init__`` is Python convention, not markdown strong emphasis."""
    text = "Call __init__ now."
    assert markdown_to_tts_prose(text) == text


def test_dunder_name_not_emphasized():
    text = "dunder __name__ variable."
    assert markdown_to_tts_prose(text) == text


def test_single_underscore_private_not_emphasized():
    text = "Discuss _private_ members."
    assert markdown_to_tts_prose(text) == text


def test_inline_backticks_in_prose_pass_through():
    """Backticks in prose should not trigger full markdown parsing."""
    text = "Use the `x` variable for clarity."
    assert markdown_to_tts_prose(text) == text


def test_double_asterisk_kwargs_not_parsed():
    """``**kwargs`` (Python) has no closing pair and must pass through."""
    text = "def foo(**kwargs): pass"
    assert markdown_to_tts_prose(text) == text


def test_real_bold_still_stripped():
    """``**bold**`` (balanced, non-empty) is a strong enough signal to strip."""
    out = markdown_to_tts_prose("This word is **important** here.")
    assert "important" in out
    assert "**" not in out


def test_single_asterisk_emphasis_passes_through_with_markers():
    """A document with ONLY single-asterisk emphasis is left alone.

    Documented trade-off: stripping single emphasis inline was too
    aggressive for technical prose. Short-form emphasis-only text
    keeps its markers; users who want stripping can add a heading
    or list marker.
    """
    text = "Just a *little* reminder."
    assert markdown_to_tts_prose(text) == text


def test_less_than_three_not_html():
    """``<3`` (heart emoticon) must not trigger HTML tag detection."""
    text = "I heart <3 this library."
    assert markdown_to_tts_prose(text) == text


def test_literal_pua_codepoints_in_input_survive():
    """Rare but valid input containing the sentinel-wrapper PUA
    codepoints must not be rewritten into LaTeX delimiters.

    Per-call UUID-scoped sentinels guarantee (to 2**-128) that an
    input cannot collide with our exact emitted sentinel strings.
    """
    # Input contains literal U+E000..U+E003 (PUA) in a markdown doc.
    # These must round-trip unchanged.
    pua = ""
    text = f"# PUA test\n\nLiteral: {pua} end."
    out = markdown_to_tts_prose(text)
    assert pua in out
    # And no spurious LaTeX delimiter got introduced.
    for tok in ("\\(", "\\)", "\\[", "\\]"):
        assert tok not in out
