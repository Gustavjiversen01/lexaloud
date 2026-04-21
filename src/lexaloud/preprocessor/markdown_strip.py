"""Strip markdown formatting for TTS reading.

Converts a markdown document into natural prose suitable for Kokoro TTS:

- Headings become paragraph breaks + plain text ending with a period
- Emphasis/bold/strikethrough markers are dropped (Kokoro has no prosody
  control, so there is nothing to emphasize via markup)
- Lists flow as sentences, separated by periods
- Code blocks are skipped by default (announce ``"Code block omitted."``)
- Tables are linearized row-by-row with headers as labels
- Links show only their text; URLs are dropped
- Block quotes are announced with ``"Quote."``
- HTML is stripped

Heuristic fast path: if no markdown construct is detected in the input,
return it unchanged without invoking the parser.

Runs second in the preprocessor pipeline (after the MathJax dedupe)
so later stages see clean prose.
"""

from __future__ import annotations

import re

from markdown_it import MarkdownIt
from markdown_it.token import Token

# Conservative heuristic: we only trigger the markdown parser when the
# input shows *unambiguous* evidence of being a markdown document. The
# earlier version triggered on single `*...*`, single `_..._`, `__`,
# and inline backticks, which produced silent false positives on
# ordinary technical prose:
#
#     Compute a*b*c in the loop.        (single emphasis false positive)
#     Call __init__ now.                (bare __ false positive)
#     dunder __name__ variable.          (same)
#     Let's discuss _private_ members.  (single emphasis false positive)
#     Use the `x` variable.              (inline-code false positive)
#
# Those inline markers are dropped from the hint. A real markdown
# document almost always has at least one BLOCK-level marker (heading,
# list, blockquote, fence, rule, table) or a link/image/HTML tag —
# those remain as triggers. Bold via `**text**` and strikethrough via
# `~~text~~` are kept but now require a balanced non-empty pair whose
# first inner character is not whitespace, which rules out bare `**`
# / `~~` in technical prose.
#
# Trade-off: short prose that ONLY uses single-asterisk or
# single-underscore emphasis (e.g. `"Just a *little* reminder."`) now
# passes through with the markers intact. That is a recoverable
# cosmetic issue; the earlier behavior silently corrupted code-like
# prose, which is much worse.
_MD_HINT = re.compile(
    r"(?m)("
    r"^\s{0,3}#{1,6}\s"  # ATX heading
    r"|^\s{0,3}[-*+]\s"  # unordered list
    r"|^\s{0,3}\d+\.\s"  # ordered list
    r"|^\s{0,3}>\s?"  # blockquote
    r"|^\s{0,3}```"  # fenced code
    r"|^\s{0,3}-{3,}\s*$"  # thematic break (---)
    r"|^\s{0,3}\*{3,}\s*$"  # thematic break (***)
    r"|\*\*[^\s*][^\n*]*\*\*"  # balanced bold pair with non-whitespace inner
    r"|~~[^\s~][^\n~]*~~"  # balanced strikethrough pair
    r"|\[[^\]]+\]\([^)]+\)"  # link
    r"|!\[[^\]]*\]\([^)]+\)"  # image
    r"|^\|[^\n]*\|"  # table row
    r"|</?[a-zA-Z][\w-]*[^>]*>"  # HTML tag (letter start avoids e.g. `<3`)
    r")"
)

_SENTENCE_END = frozenset(".!?:;")


def _inline_text(token: Token, *, announce_images: bool = True) -> str:
    """Extract plain text from an ``inline`` token's children.

    Drops marker tokens (``em_open``/``strong_open``/``s_open``/
    ``link_open`` etc.) and keeps the text children. ``image`` tokens
    are converted to ``"Image: <alt>."``.
    """
    if not token.children:
        return token.content
    parts: list[str] = []
    for child in token.children:
        ct = child.type
        if ct == "text":
            parts.append(child.content)
        elif ct in ("softbreak", "hardbreak"):
            parts.append(" ")
        elif ct == "code_inline":
            parts.append(child.content)
        elif ct == "image":
            alt = child.content.strip()
            if announce_images:
                # Intentionally no trailing period — surrounding prose
                # usually provides one (``. ![alt](x)`` → ``. Image: alt.``
                # with this rule, vs ``. Image: alt..`` with a trailing
                # period). Trade-off: when the image is at a paragraph
                # boundary with no prose punctuation, the output lacks
                # a period — acceptable because `_canonicalize()` still
                # produces a paragraph break from the surrounding
                # newlines.
                parts.append(f"Image: {alt}" if alt else "Image")
        # em/strong/s/link open/close: skip — the `text` children they
        # wrap are emitted directly by this loop.
    return "".join(parts)


def _canonicalize(text: str) -> str:
    """Collapse whitespace so tests can be robust to exact formatting."""
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    return text.strip()


_SRE_LPAREN = ""
_SRE_RPAREN = ""
_SRE_LBRACK = ""
_SRE_RBRACK = ""


def _protect_sre_delimiters(text: str) -> str:
    """Hide ``\\(``, ``\\)``, ``\\[``, ``\\]`` from markdown-it-py.

    CommonMark treats ``\\(`` / ``\\[`` as backslash escapes and strips
    the leading backslash during parsing, which destroys the LaTeX
    math delimiters that the downstream SRE stage recognizes. We
    substitute them with Private Use Area codepoints before parsing
    and restore them after canonicalization.
    """
    text = text.replace("\\(", _SRE_LPAREN).replace("\\)", _SRE_RPAREN)
    text = text.replace("\\[", _SRE_LBRACK).replace("\\]", _SRE_RBRACK)
    return text


def _restore_sre_delimiters(text: str) -> str:
    text = text.replace(_SRE_LPAREN, "\\(").replace(_SRE_RPAREN, "\\)")
    text = text.replace(_SRE_LBRACK, "\\[").replace(_SRE_RBRACK, "\\]")
    return text


def markdown_to_tts_prose(
    text: str,
    *,
    skip_code_blocks: bool = True,
    announce_quotes: bool = True,
    table_headers_as_labels: bool = True,
) -> str:
    """Convert markdown to plain prose for TTS.

    Returns the input unchanged if the heuristic detects no markdown.
    Backslash-escaped LaTeX delimiters (``\\(``, ``\\)``, ``\\[``,
    ``\\]``) are protected with Private Use Area sentinels during
    parsing so they survive for the downstream SRE stage.
    """
    if not _MD_HINT.search(text):
        return text

    text = _protect_sre_delimiters(text)

    md = MarkdownIt("commonmark")
    md.enable("table")
    md.enable("strikethrough")
    tokens = md.parse(text)

    out: list[str] = []
    last_nontrivial: str = ""

    def append(s: str) -> None:
        nonlocal last_nontrivial
        if not s:
            return
        out.append(s)
        stripped = s.rstrip()
        if stripped:
            last_nontrivial = stripped[-1]

    def end_sentence() -> None:
        """Ensure the most recent non-whitespace char is sentence punctuation."""
        if last_nontrivial and last_nontrivial not in _SENTENCE_END:
            append(".")

    in_table_head = False
    in_table_body = False
    table_headers: list[str] = []
    table_col = 0
    list_counter: int | None = None  # None=no list; 0=unordered; 1+ = ordered counter

    for tok in tokens:
        t = tok.type

        if t == "heading_open":
            append("\n\n")
        elif t == "heading_close":
            end_sentence()
            append("\n\n")

        elif t == "paragraph_close":
            append("\n\n")
        elif t == "paragraph_open":
            pass

        elif t == "ordered_list_open":
            list_counter = 1
            append("\n\n")
        elif t == "bullet_list_open":
            list_counter = 0
            append("\n\n")
        elif t in ("ordered_list_close", "bullet_list_close"):
            list_counter = None
            append("\n\n")
        elif t == "list_item_open":
            if list_counter is not None and list_counter > 0:
                append(f"{list_counter}. ")
                list_counter += 1
        elif t == "list_item_close":
            end_sentence()
            append(" ")

        elif t in ("fence", "code_block"):
            if skip_code_blocks:
                append("Code block omitted.\n\n")
            else:
                append(tok.content.rstrip())
                append("\n\n")

        elif t == "blockquote_open":
            if announce_quotes:
                append("Quote. ")
        elif t == "blockquote_close":
            end_sentence()
            append("\n\n")

        elif t == "hr":
            append("\n\n")

        elif t == "table_open":
            in_table_head = False
            in_table_body = False
            table_headers = []
            table_col = 0
        elif t == "table_close":
            append("\n\n")
            table_headers = []
        elif t == "thead_open":
            in_table_head = True
            table_col = 0
        elif t == "thead_close":
            in_table_head = False
        elif t == "tbody_open":
            in_table_body = True
        elif t == "tbody_close":
            in_table_body = False
        elif t == "tr_open":
            table_col = 0
        elif t == "tr_close":
            end_sentence()
            append("\n")
        elif t in ("th_open", "td_open"):
            pass
        elif t in ("th_close", "td_close"):
            if not in_table_head:
                table_col += 1

        elif t == "inline":
            body = _inline_text(tok).strip()
            if in_table_head and table_headers_as_labels:
                table_headers.append(body)
            elif in_table_body and table_headers_as_labels:
                if table_col < len(table_headers) and table_headers[table_col]:
                    append(f"{table_headers[table_col]}: {body}, ")
                else:
                    append(f"{body}, ")
            else:
                append(body)

        elif t in ("html_block", "html_inline"):
            # HTML is stripped entirely at the block level. Inline HTML
            # that appears inside an `inline` token is handled via
            # _inline_text (which ignores `html_inline` children).
            pass

    return _restore_sre_delimiters(_canonicalize("".join(out)))


__all__ = ["markdown_to_tts_prose"]
