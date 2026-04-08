"""PDF-paste cleanup: whitespace, de-hyphenation, line unwrap.

Option A (simple, no extra dependency) heuristic: only de-hyphenate when
a line break clearly splits a lowercase token, and preserve sentence
boundaries so pysbd downstream can still see them.

Unicode hyphen variants are normalized to ASCII `-` up front so the
de-hyphenation regex doesn't need to enumerate them, and soft hyphens
(U+00AD) are dropped entirely (they're invisible hints to the renderer
that the word is breakable, not real characters).
"""

from __future__ import annotations

import re
import unicodedata

# Soft hyphens (U+00AD) are invisible hints to a renderer; they should never
# be spoken. When one lands immediately before a line break (the common PDF
# case), drop the hyphen AND the newline so `com\u00ad\npleted` becomes
# `completed` without leaking a stray space into the unwrap pass.
_SOFTHYPHEN_LINEBREAK = re.compile(r"\u00ad\n[ \t]*")

# Any remaining standalone soft hyphens (e.g., in mid-line text) are deleted
# without leaving anything behind.
_SOFTHYPHEN_STANDALONE = re.compile(r"\u00ad")

# Normalize Unicode hyphen-like codepoints to ASCII `-` so the downstream
# de-hyphenation patterns don't have to enumerate them.
_HYPHEN_NORMALIZE = {
    "\u2010": "-",  # HYPHEN
    "\u2011": "-",  # NON-BREAKING HYPHEN
    "\u2012": "-",  # FIGURE DASH (occasionally used as hyphen in PDFs)
}

# Compound word broken at a line break. Only matches when the captured
# start is preceded by `-` (i.e., it's already the tail of a compound).
# In that case we PRESERVE the hyphen: `state-of-the-\nart` →
# `state-of-the-art`.
_COMPOUND_LINEBREAK = re.compile(r"(?<=[a-z]-)([a-z]+)-\n[ \t]*([a-z]+)")

# Plain word broken at a line break: `com-\npleted` → `completed`.
# Runs AFTER the compound pattern so a compound tail isn't touched again.
_PLAIN_HYPHEN_LINEBREAK = re.compile(r"([a-z]{2,})-\n[ \t]*([a-z]{2,})")

# Normalize curly quotes and various dash forms to plain ASCII where safe.
# en/em dashes are NOT mapped (they have different spoken meaning).
_QUOTE_MAP = {
    "\u2018": "'",  # ‘
    "\u2019": "'",  # ’
    "\u201c": '"',  # “
    "\u201d": '"',  # ”
    "\u2032": "'",  # ′
    "\u2033": '"',  # ″
    "\u00a0": " ",  # NBSP
    "\u2009": " ",  # thin space
    "\u200a": " ",  # hair space
    "\u202f": " ",  # narrow no-break space
}

_TERMINAL_PUNCTUATION = ".!?…"


def _normalize_punctuation(text: str) -> str:
    # Unicode normalize first (so combining marks don't split oddly), then
    # apply our per-codepoint quote/space/hyphen maps. Soft hyphens are
    # handled separately so we can context-match `\u00ad\n`.
    text = unicodedata.normalize("NFKC", text)
    for src, dst in _QUOTE_MAP.items():
        text = text.replace(src, dst)
    for src, dst in _HYPHEN_NORMALIZE.items():
        text = text.replace(src, dst)
    # Drop soft hyphens across a line break (no space left behind),
    # then drop any remaining standalone soft hyphens.
    text = _SOFTHYPHEN_LINEBREAK.sub("", text)
    text = _SOFTHYPHEN_STANDALONE.sub("", text)
    return text


def _dehyphenate(text: str) -> str:
    # Preserve the hyphen for compound words (tail continuation) first, then
    # collapse plain word-internal hyphens that landed at a line break.
    text = _COMPOUND_LINEBREAK.sub(r"\1-\2", text)
    text = _PLAIN_HYPHEN_LINEBREAK.sub(r"\1\2", text)
    return text


def _unwrap_lines(text: str) -> str:
    """Join consecutive non-empty lines within a paragraph.

    Paragraphs are separated by blank lines. Within a paragraph, lines are
    joined with a single space — EXCEPT when the prior line ends with
    terminal punctuation (`. ! ? …`), in which case we preserve the newline
    as a stronger boundary signal for pysbd.
    """
    # Normalize \r\n and \r to \n.
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    paragraphs = re.split(r"\n[ \t]*\n+", text)
    out: list[str] = []
    for para in paragraphs:
        lines = [ln.strip() for ln in para.split("\n") if ln.strip()]
        if not lines:
            continue
        pieces: list[str] = [lines[0]]
        for prev, cur in zip(lines, lines[1:], strict=False):
            if prev and prev[-1] in _TERMINAL_PUNCTUATION:
                # Preserve sentence boundary: keep a newline so pysbd sees
                # a hard break even though we still want the lines in the
                # same paragraph.
                pieces.append("\n")
            else:
                pieces.append(" ")
            pieces.append(cur)
        out.append("".join(pieces))
    return "\n\n".join(out)


def _collapse_whitespace(text: str) -> str:
    # Collapse runs of spaces and tabs to one space, but preserve newlines.
    text = re.sub(r"[ \t]+", " ", text)
    # Trim trailing spaces on each line.
    text = re.sub(r" +\n", "\n", text)
    # Collapse 3+ newlines to exactly two (paragraph break).
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def clean_pdf_paste(text: str) -> str:
    """Run the PDF-paste cleanup stages in order."""
    text = _normalize_punctuation(text)
    text = _dehyphenate(text)
    text = _unwrap_lines(text)
    text = _collapse_whitespace(text)
    return text
