"""Deduplicate MathJax/KaTeX copy-paste text.

When selecting rendered math from a webpage, the browser captures TWO
representations of each expression:

  1. STACKED (visual layer): one symbol per line, from the absolutely-
     positioned CSS spans that KaTeX/MathJax uses for layout.
  2. COMPACT (accessibility layer): the inline text that KaTeX includes
     for screen readers or as aria-label fallback.

The stacked version always precedes the compact version. This module
detects the stacked blocks and removes them, keeping the compact inline
form which reads naturally for TTS.

Runs FIRST in the preprocessor pipeline, before `clean_pdf_paste`,
because it needs the raw newline structure intact to detect the
stacked pattern.

Safe on non-MathJax input: requires both the single-char-per-line
structure AND a matching compact duplicate immediately after.
"""

from __future__ import annotations

import re

_ZERO_WIDTH_RE = re.compile("[\u200b\u200c\u200d\ufeff]")

_INVISIBLE_ONLY_RE = re.compile(r"^[\s\u200b\u200c\u200d\ufeff\u00a0]*$")


def _visible_chars(s: str) -> str:
    """Return only the visible (non-whitespace, non-zero-width) characters."""
    return _ZERO_WIDTH_RE.sub("", s).replace("\u00a0", " ").strip()


def _extract_alpha_math(s: str) -> str:
    """Extract comparison-visible characters.

    Strips a narrow set: whitespace, commas, semicolons, colons, braces,
    parens, brackets, NBSP. Does NOT strip general ASCII punctuation like
    ``+ - =`` because those are meaningful and stripping them would let
    ``a+b`` match ``ab``.
    """
    return re.sub(r"[\s,;:{}()\[\]\u00a0]", "", s)


def dedupe_mathjax_selection(text: str) -> str:
    """Remove duplicated stacked math from KaTeX/MathJax copy-paste.

    Strategy:

    1. Normalize invisible characters (zero-width, NBSP) first — even
       input without newlines gets this cleanup, so the no-newline
       fast path still produces clean output.
    2. Fast-return if the normalized text has no newlines.
    3. Scan for runs of lines where each line has exactly 1 visible
       character (the "stacked" visual layer). Require >=2 such lines.
    4. Look at the text immediately following the run. If its leading
       visible characters match the stacked sequence (under the
       narrow punctuation strip in ``_extract_alpha_math``), the
       stacked block is a duplicate — delete it.
    5. Collapse KaTeX's subscript continuation lines.
    6. A regex pass handles single-variable duplications
       (``" \\nX\\nX "`` → ``" X "``) that slipped through.
    """
    text = _ZERO_WIDTH_RE.sub("", text)
    text = text.replace("\u00a0", " ")

    if "\n" not in text:
        return text

    lines = text.split("\n")
    result_lines: list[str] = []
    i = 0

    while i < len(lines):
        vis = _visible_chars(lines[i])

        if len(vis) == 1 and i + 1 < len(lines) and len(_visible_chars(lines[i + 1])) == 1:
            run_start = i
            stacked_chars: list[str] = []
            while i < len(lines):
                v = _visible_chars(lines[i])
                if len(v) == 1:
                    stacked_chars.append(v)
                    i += 1
                elif _INVISIBLE_ONLY_RE.match(lines[i]):
                    i += 1
                else:
                    break

            if i < len(lines) and len(stacked_chars) >= 2:
                # A real MathJax/KaTeX stacked block almost always
                # contains at least one non-letter: a digit, operator,
                # brace, or non-ASCII char (Greek). A run of single-
                # char ASCII-letter lines is almost certainly a
                # short-line outline or list, not math — require at
                # least one non-(ASCII-letter) visible char.
                if all(c.isalpha() and c.isascii() for c in stacked_chars):
                    result_lines.extend(lines[run_start:i])
                    continue

                stacked_seq = "".join(stacked_chars)

                compact_text = ""
                for j in range(i, min(i + 6, len(lines))):
                    compact_text += _visible_chars(lines[j])
                    if len(_extract_alpha_math(compact_text)) >= len(
                        _extract_alpha_math(stacked_seq)
                    ):
                        break

                stacked_norm = _extract_alpha_math(stacked_seq)
                compact_norm = _extract_alpha_math(compact_text)

                if compact_norm.startswith(stacked_norm):
                    continue
                else:
                    result_lines.extend(lines[run_start:i])
                    continue
            else:
                result_lines.extend(lines[run_start:i])
                continue
        else:
            result_lines.append(lines[i])
            i += 1

    output = "\n".join(result_lines)

    output = re.sub(
        r"(\S) \n(\d+)\n\s*\n\s*([})\]])",
        r"\1\2\3",
        output,
    )

    output = re.sub(
        r"( )\n(\w)\n\2( )",
        r"\1\2\3",
        output,
    )

    output = re.sub(r"\n{3,}", "\n\n", output)

    output = "\n".join(line.rstrip() for line in output.split("\n"))

    return output


__all__ = ["dedupe_mathjax_selection"]
