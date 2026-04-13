"""Expand common academic abbreviations used in scholarly prose.

Follows the same pattern as ``abbreviations.py``: a compiled regex list
applied in order, longer patterns first to avoid partial matches.

Key design decisions from stress-test review:
- ``p.`` requires a following digit to avoid matching ``p.m.``, ``p.d.f.``
- ``No.`` requires a following digit to avoid matching sentence-final "No."
- ``s.t.`` is strictly lowercase (no ``(?i)``) to avoid matching ``St.``
- ``w.r.t.``, ``i.i.d.``, ``w.l.o.g.`` are case-insensitive
"""

from __future__ import annotations

import re

_REPLACEMENTS: list[tuple[re.Pattern[str], str]] = [
    # Multi-word patterns first (longest match)
    (re.compile(r"(?i)\bet\s+seq\."), "and following"),
    (re.compile(r"(?i)\bw\.l\.o\.g\."), "without loss of generality"),
    (re.compile(r"(?i)\bi\.i\.d\."), "independently and identically distributed"),
    # w.r.t. — case-insensitive
    (re.compile(r"(?i)\bw\.r\.t\."), "with respect to"),
    # s.t. — strictly lowercase to avoid "St." (Saint/Street)
    (re.compile(r"\bs\.t\.\s"), "such that "),
    # Academic abbreviations — case-insensitive, require word boundary
    (re.compile(r"(?i)\bApprox\."), "approximately"),
    (re.compile(r"(?i)\bChap\."), "Chapter"),
    (re.compile(r"(?i)\bEqn\."), "Equation"),
    (re.compile(r"(?i)\bEq\."), "Equation"),
    (re.compile(r"(?i)\bFig\."), "Figure"),
    (re.compile(r"(?i)\bSec\."), "Section"),
    (re.compile(r"(?i)\bRef\."), "Reference"),
    (re.compile(r"(?i)\bTab\."), "Table"),
    (re.compile(r"(?i)\bVol\."), "Volume"),
    (re.compile(r"(?i)\bCh\."), "Chapter"),
    (re.compile(r"(?i)\bDef\."), "Definition"),
    (re.compile(r"(?i)\bThm\."), "Theorem"),
    (re.compile(r"(?i)\bLem\."), "Lemma"),
    (re.compile(r"(?i)\bCor\."), "Corollary"),
    (re.compile(r"(?i)\bProp\."), "Proposition"),
    (re.compile(r"(?i)\bEx\."), "Example"),
    (re.compile(r"(?i)\bRem\."), "Remark"),
    # p. / pp. — require following digit to avoid matching p.m., p.d.f., etc.
    (re.compile(r"\bpp\.\s*(?=\d)"), "pages "),
    (re.compile(r"\bp\.\s*(?=\d)"), "page "),
    # No. — require following digit to avoid sentence-final "No."
    (re.compile(r"\bNo\.\s*(?=\d)"), "Number "),
]


def expand_academic_abbreviations(text: str) -> str:
    """Expand academic abbreviations to their full forms."""
    for pat, repl in _REPLACEMENTS:
        text = pat.sub(repl, text)
    return text
