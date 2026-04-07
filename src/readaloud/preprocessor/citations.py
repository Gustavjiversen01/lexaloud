"""Citation stripping.

Two functions:

- `strip_numeric_bracket_citations` — on by default. Removes `[12]`,
  `[12, 15]`, `[12-15]`, `[12–15]`. These are unambiguous in academic text.

- `strip_parenthetical_citations` — off by default. Removes
  `(Smith, 2023)`, `(Smith et al., 2023)`, `(Smith and Jones, 2023)`,
  `(Smith, 2023; Jones, 2020)`. The risk: false positives against
  meaningful parentheticals like `(see Fig. 3)`. Only run on text from
  sources where the user knows inline author-year citations dominate.
  The surname character class accepts ASCII letters plus common
  accented Latin letters so international surnames aren't missed.
"""

from __future__ import annotations

import re

# [12], [12, 15], [12-15], [12–15], [12, 15-18]. Anchored to ASCII digits and
# commas/dashes/spaces only inside the brackets.
_NUMERIC_BRACKET = re.compile(r"\[\s*\d+(?:\s*[–\-,]\s*\d+)*\s*\]")

# Parenthetical author-year. Relaxed from earlier iterations:
#  - accepts `&`, `and` as coauthor connector
#  - accepts optional comma before the year (`(Smith 2020)` style)
#  - accepts a broad set of surname characters including common accented
#    Latin letters (García, Müller, Bañuelos)
#
# Surname character class: ASCII A-Z and selected accented uppercase +
# ASCII letters and selected accented lowercase for continuation. Not
# Unicode-perfect (would need the third-party `regex` package for
# `\p{Lu}\p{L}*`), but substantially better than bare [A-Za-z].
_SURNAME = r"[A-ZÀ-Ý][A-Za-zÀ-ÿ\-']+"

_PAREN_AUTHOR_YEAR = re.compile(
    rf"""
    \(
        \s*
        (?:
            {_SURNAME}
            (?:\s+et\s+al\.?)?                              # optional et al.
            (?:\s*(?:&|and)\s*{_SURNAME})*                  # optional coauthors
            (?:\s*,)?\s*                                    # optional comma
            \d{{4}}[a-z]?                                   # 4-digit year
            (?:\s*[;,]\s*                                   # more cites after ;
               {_SURNAME}
               (?:\s+et\s+al\.?)?
               (?:\s*(?:&|and)\s*{_SURNAME})*
               (?:\s*,)?\s*\d{{4}}[a-z]?
            )*
            \s*
        )
    \)
    """,
    re.VERBOSE,
)


def _tidy(text: str) -> str:
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r" +\n", "\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text


def strip_numeric_bracket_citations(text: str) -> str:
    text = _NUMERIC_BRACKET.sub("", text)
    return _tidy(text)


def strip_parenthetical_citations(text: str) -> str:
    text = _PAREN_AUTHOR_YEAR.sub("", text)
    return _tidy(text)
