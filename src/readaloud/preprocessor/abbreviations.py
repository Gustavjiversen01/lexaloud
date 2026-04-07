"""Expand common Latin abbreviations used in academic prose.

Case-insensitive where reasonable, so sentence-initial `Cf.`, `Ibid.`,
`E.g.`, `I.e.` all expand. This matters because a sentence-initial
capitalized abbreviation like `Ibid.` will otherwise confuse pysbd
segmentation (it looks like a sentence terminator).

Order matters: longer patterns first so "et al." beats "et".
"""

from __future__ import annotations

import re

# (pattern, replacement) — applied in order. Patterns include the trailing
# period because sentence-segmentation hasn't happened yet. Case-insensitive
# via `(?i)` inline flag so sentence-initial capitalization is handled.
_REPLACEMENTS: list[tuple[re.Pattern[str], str]] = [
    # "et al." (any capitalization); broad lookahead so it also matches
    # before closing punctuation (`)`, `]`, `"`, `'`, `.`)
    (
        re.compile(r"\b[Ee]t\s+al\.(?=\s|$|[,;:.)\]\"\'])"),
        "and colleagues",
    ),
    # "e.g.," / "e.g." / "E.g.," / "E.g."
    (re.compile(r"(?i)\be\.\s*g\.,?"), "for example,"),
    # "i.e.," / "i.e." / "I.e.," / "I.e."
    (re.compile(r"(?i)\bi\.\s*e\.,?"), "that is,"),
    # "cf." → "compare" (case-insensitive)
    (re.compile(r"(?i)\bcf\."), "compare"),
    # "viz." → "namely"
    (re.compile(r"(?i)\bviz\."), "namely"),
    # "ibid." → "same source"
    (re.compile(r"(?i)\bibid\."), "same source"),
    # "N.B."/"NB." → "note well"
    (re.compile(r"(?i)\bN\.?B\."), "note well"),
    # "vs." → "versus"
    (re.compile(r"(?i)\bvs\."), "versus"),
]


def expand_latin_abbreviations(text: str) -> str:
    for pat, repl in _REPLACEMENTS:
        text = pat.sub(repl, text)
    return text
