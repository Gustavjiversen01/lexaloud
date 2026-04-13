"""Convert numeric tokens to spoken-word forms for TTS.

Zero external dependencies — pure Python implementation covering the
most common patterns in academic and general English text.

Stress-test-driven design decisions:
- Reference numbers (Figure 3, Section 2.1) are left as-is — TTS
  handles single digits fine and "Section two point one" sounds wrong.
- IP addresses, version strings, phone numbers, and hyphenated sequences
  are protected with placeholders before normalization.
- Years (1800-2099) preceded by temporal context words are spoken as
  years ("twenty twenty-four"), not cardinals.
- Numbers >999,999 are left as-is (LLM fallback in Phase 2).
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Placeholder protection for patterns that look numeric but should not
# be normalized: IP addresses, version strings, phone numbers, etc.
# ---------------------------------------------------------------------------

_PLACEHOLDER_PREFIX = "\x00NUMPROTECT"

_PROTECT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # IP addresses: 192.168.1.1
    (re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"), "IP"),
    # Version strings: v3.12.1, V2.0
    (re.compile(r"\b[vV]\d+\.\d+(?:\.\d+)*\b"), "VER"),
    # Phone numbers: 555-1234, (555) 123-4567, 555.123.4567
    (re.compile(r"\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b"), "PHONE"),
    # Hyphenated number sequences (ISBNs, etc.): 978-3-16-148410-0
    (re.compile(r"\b\d+(?:-\d+){2,}\b"), "HYPH"),
]


def _protect(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Replace protected patterns with placeholders, return restore list."""
    restores: list[tuple[str, str]] = []
    for pat, tag in _PROTECT_PATTERNS:
        for match in pat.finditer(text):
            original = match.group()
            placeholder = f"{_PLACEHOLDER_PREFIX}{tag}{len(restores)}\x00"
            restores.append((placeholder, original))
            text = text.replace(original, placeholder, 1)
    return text, restores


def _restore(text: str, restores: list[tuple[str, str]]) -> str:
    """Restore placeholders back to original text."""
    for placeholder, original in reversed(restores):
        text = text.replace(placeholder, original)
    return text


# ---------------------------------------------------------------------------
# Reference-context exclusion: numbers immediately following these words
# (after academic abbreviation expansion) are left as-is.
# ---------------------------------------------------------------------------

_REFERENCE_CONTEXT_WORDS = (
    "Section",
    "Figure",
    "Table",
    "Equation",
    "Algorithm",
    "Theorem",
    "Lemma",
    "Corollary",
    "Proposition",
    "Example",
    "Definition",
    "Remark",
    "Chapter",
    "Step",
    "Appendix",
    "Listing",
    "Reference",
    "Volume",
    "Number",
    # Lowercase variants (in case expansion didn't capitalize)
    "section",
    "figure",
    "table",
    "equation",
    "page",
    "pages",
)

# Matches a reference-context word followed by whitespace and a number
# (possibly with dots like 2.1.3). Used to identify numbers to skip.
_REFERENCE_NUM = re.compile(
    r"\b(?:" + "|".join(re.escape(w) for w in _REFERENCE_CONTEXT_WORDS) + r")\s+(\d[\d.]*)",
    re.IGNORECASE,
)


def _find_reference_numbers(text: str) -> set[int]:
    """Return character positions of numbers that follow reference-context words."""
    positions: set[int] = set()
    for m in _REFERENCE_NUM.finditer(text):
        # The captured group (1) is the number; record its start position
        positions.add(m.start(1))
    return positions


# ---------------------------------------------------------------------------
# Number-to-words conversion (pure Python, English only)
# ---------------------------------------------------------------------------

_ONES = [
    "",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
]
_TENS = [
    "",
    "",
    "twenty",
    "thirty",
    "forty",
    "fifty",
    "sixty",
    "seventy",
    "eighty",
    "ninety",
]
_SCALES = ["", "thousand", "million"]


def _int_to_words(n: int) -> str:
    """Convert a non-negative integer (0-999,999) to English words."""
    if n == 0:
        return "zero"
    if n < 0 or n > 999_999:
        return str(n)  # out of range, leave as digits

    parts: list[str] = []
    for _i, scale in enumerate(_SCALES):
        if n == 0:
            break
        chunk = n % 1000
        n //= 1000
        if chunk == 0:
            continue
        chunk_words = _chunk_to_words(chunk)
        if scale:
            chunk_words += " " + scale
        parts.append(chunk_words)

    return " ".join(reversed(parts))


def _chunk_to_words(n: int) -> str:
    """Convert a number 1-999 to words."""
    if n < 20:
        return _ONES[n]
    if n < 100:
        tens, ones = divmod(n, 10)
        return _TENS[tens] + ("-" + _ONES[ones] if ones else "")
    hundreds, remainder = divmod(n, 100)
    result = _ONES[hundreds] + " hundred"
    if remainder:
        result += " " + _chunk_to_words(remainder)
    return result


def _year_to_words(n: int) -> str:
    """Convert a year (1800-2099) to spoken form."""
    if 2000 <= n <= 2009:
        return "two thousand" + (" " + _ONES[n - 2000] if n > 2000 else "")
    if 2010 <= n <= 2099:
        return "twenty " + _chunk_to_words(n - 2000)
    # 1800-1999: split into two halves
    hi, lo = divmod(n, 100)
    hi_words = _chunk_to_words(hi)
    if lo == 0:
        return hi_words + " hundred"
    return hi_words + " " + _chunk_to_words(lo)


# ---------------------------------------------------------------------------
# Ordinal conversion
# ---------------------------------------------------------------------------

_ORDINAL_SUFFIX = re.compile(r"\b(\d{1,6})(st|nd|rd|th)\b", re.IGNORECASE)

_ORDINAL_WORDS = {
    1: "first",
    2: "second",
    3: "third",
    4: "fourth",
    5: "fifth",
    6: "sixth",
    7: "seventh",
    8: "eighth",
    9: "ninth",
    10: "tenth",
    11: "eleventh",
    12: "twelfth",
    13: "thirteenth",
    14: "fourteenth",
    15: "fifteenth",
    16: "sixteenth",
    17: "seventeenth",
    18: "eighteenth",
    19: "nineteenth",
    20: "twentieth",
    30: "thirtieth",
    40: "fortieth",
    50: "fiftieth",
    60: "sixtieth",
    70: "seventieth",
    80: "eightieth",
    90: "ninetieth",
}


def _ordinal_to_words(n: int) -> str:
    """Convert an ordinal number to words (e.g. 1 -> 'first')."""
    if n in _ORDINAL_WORDS:
        return _ORDINAL_WORDS[n]
    if n > 999_999 or n < 1:
        return str(n)
    # For compound ordinals: "twenty-first", "one hundred third"
    base = _int_to_words(n)
    # Replace the last word with its ordinal form
    # e.g. "twenty-one" -> "twenty-first"
    words = base.rsplit(" ", 1)
    last = words[-1]
    # Handle hyphenated last word: "twenty-one" -> "twenty-first"
    if "-" in last:
        prefix, suffix = last.rsplit("-", 1)
        last_num = _word_to_num(suffix)
        if last_num is not None and last_num in _ORDINAL_WORDS:
            return " ".join(words[:-1] + [prefix + "-" + _ORDINAL_WORDS[last_num]])
    # Simple suffix rule for the last word
    last_num = _word_to_num(last)
    if last_num is not None and last_num in _ORDINAL_WORDS:
        return " ".join(words[:-1] + [_ORDINAL_WORDS[last_num]])
    # Fallback: append "th" with adjustments
    if last.endswith("y"):
        return " ".join(words[:-1] + [last[:-1] + "ieth"])
    if last.endswith("e"):
        return " ".join(words[:-1] + [last[:-1] + "th"])
    return base + "th"


_WORD_TO_NUM = {v: k for k, v in _ORDINAL_WORDS.items() if v}
_WORD_TO_NUM.update({w: i for i, w in enumerate(_ONES) if w})


def _word_to_num(word: str) -> int | None:
    return _WORD_TO_NUM.get(word)


# ---------------------------------------------------------------------------
# Pattern matchers for the main normalize function
# ---------------------------------------------------------------------------

# Year context: preceded by a temporal word
_YEAR_CONTEXT = re.compile(
    r"\b(?:in|by|since|until|circa|around|from|after|before|during)\s+(\d{4})\b",
    re.IGNORECASE,
)

# Currency: $100, $1,234.56
_CURRENCY = re.compile(r"\$(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?)\b")

# Percentage: 50%, 3.14%
_PERCENTAGE = re.compile(r"\b(\d+(?:\.\d+)?)%")

# Simple fractions: 1/2, 3/4
_FRACTION = re.compile(r"\b(\d)/(\d)\b")

_FRACTION_WORDS = {
    (1, 2): "one half",
    (1, 3): "one third",
    (1, 4): "one quarter",
    (1, 5): "one fifth",
    (1, 8): "one eighth",
    (2, 3): "two thirds",
    (3, 4): "three quarters",
    (3, 8): "three eighths",
    (5, 8): "five eighths",
    (7, 8): "seven eighths",
}

# Cardinals with commas: 1,234 or 1,234,567
_CARDINAL_COMMA = re.compile(r"\b(\d{1,3}(?:,\d{3})+)\b")

# Decimals: 3.14 (but not version-like x.y.z where another .digit follows)
_DECIMAL = re.compile(r"\b(\d+)\.(\d+)\b(?!\.\d)")

# Plain integers: standalone digits (1-6 digits)
_PLAIN_INT = re.compile(r"\b(\d{1,6})\b")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def normalize_numbers(text: str) -> str:
    """Convert numeric tokens to spoken-word English.

    Designed to run AFTER academic abbreviation expansion so that
    reference-context words (Figure, Section, etc.) are already expanded.
    """
    # Step 1: protect patterns that should not be normalized
    text, restores = _protect(text)

    # Step 2: find reference-number positions to skip
    ref_positions = _find_reference_numbers(text)

    # Step 3: ordinals (1st, 2nd, 3rd, 4th, ...)
    def _replace_ordinal(m: re.Match) -> str:
        if m.start() in ref_positions:
            return m.group()
        n = int(m.group(1))
        if n > 999_999:
            return m.group()
        return _ordinal_to_words(n)

    text = _ORDINAL_SUFFIX.sub(_replace_ordinal, text)

    # Step 4: currency ($100, $1,234.56)
    def _replace_currency(m: re.Match) -> str:
        raw = m.group(1).replace(",", "")
        if "." in raw:
            dollars_s, cents_s = raw.split(".", 1)
            dollars = int(dollars_s)
            cents = int(cents_s)
            if dollars > 999_999:
                return m.group()
            result = _int_to_words(dollars) + " dollar" + ("s" if dollars != 1 else "")
            if cents:
                result += " and " + _int_to_words(cents) + " cent" + ("s" if cents != 1 else "")
            return result
        dollars = int(raw)
        if dollars > 999_999:
            return m.group()
        return _int_to_words(dollars) + " dollar" + ("s" if dollars != 1 else "")

    text = _CURRENCY.sub(_replace_currency, text)

    # Step 5: percentages (50%, 3.14%)
    def _replace_percentage(m: re.Match) -> str:
        raw = m.group(1)
        if "." in raw:
            integer, frac = raw.split(".", 1)
            n = int(integer)
            if n > 999_999:
                return m.group()
            spoken_frac = " point " + " ".join(_ONES[int(d)] if d != "0" else "zero" for d in frac)
            return _int_to_words(n) + spoken_frac + " percent"
        n = int(raw)
        if n > 999_999:
            return m.group()
        return _int_to_words(n) + " percent"

    text = _PERCENTAGE.sub(_replace_percentage, text)

    # Step 6: simple fractions (1/2, 3/4)
    def _replace_fraction(m: re.Match) -> str:
        num, den = int(m.group(1)), int(m.group(2))
        key = (num, den)
        if key in _FRACTION_WORDS:
            return _FRACTION_WORDS[key]
        return m.group()

    text = _FRACTION.sub(_replace_fraction, text)

    # Step 7: years in temporal context (in 2024, since 1999)
    def _replace_year(m: re.Match) -> str:
        n = int(m.group(1))
        if 1800 <= n <= 2099:
            prefix = m.group()[: m.start(1) - m.start()]
            return prefix + _year_to_words(n)
        return m.group()

    text = _YEAR_CONTEXT.sub(_replace_year, text)

    # Step 8: cardinals with commas (1,234)
    def _replace_cardinal_comma(m: re.Match) -> str:
        if m.start() in ref_positions:
            return m.group()
        raw = m.group(1).replace(",", "")
        n = int(raw)
        if n > 999_999:
            return m.group()
        return _int_to_words(n)

    text = _CARDINAL_COMMA.sub(_replace_cardinal_comma, text)

    # Step 9: decimals (3.14 — but not after reference words)
    def _replace_decimal(m: re.Match) -> str:
        if m.start() in ref_positions:
            return m.group()
        integer = m.group(1)
        frac = m.group(2)
        n = int(integer)
        if n > 999_999:
            return m.group()
        spoken_frac = " ".join(_ONES[int(d)] if d != "0" else "zero" for d in frac)
        return _int_to_words(n) + " point " + spoken_frac

    text = _DECIMAL.sub(_replace_decimal, text)

    # Note: we do NOT normalize plain standalone integers here.
    # Single digits (0-9) and small numbers read fine as digits by TTS.
    # Large numbers without commas (>6 digits) are left for the LLM.

    # Step 10: restore protected patterns
    text = _restore(text, restores)

    return text
