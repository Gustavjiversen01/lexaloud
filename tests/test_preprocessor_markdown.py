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


def test_inline_code():
    out = markdown_to_tts_prose("Use `print(x)` to debug.")
    assert "print(x)" in out
    assert "`" not in out


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
