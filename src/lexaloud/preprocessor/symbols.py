"""URL/email normalization and Unicode math symbol expansion for TTS.

Stress-test-driven design:
- Math symbol dictionary covers ONLY Unicode codepoints (not ASCII
  operators like ->, <=, !=) to avoid mangling code snippets.
- URL regex strips trailing punctuation to preserve sentence boundaries.
- Markdown links [text](url) are handled before general URL regex.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# URL and email normalization
# ---------------------------------------------------------------------------

# Markdown links: [text](url) -> just the text
_MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\(https?://[^)]+\)")

# General URLs: strip trailing sentence punctuation before replacing
_URL = re.compile(r"https?://[^\s<>\"]+")
_TRAILING_PUNCT = re.compile(r"[.,;:!?)\]]+$")

# Email addresses
_EMAIL = re.compile(r"\b([a-zA-Z0-9._%+-]+)@([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})\b")


def _url_to_spoken(url: str) -> str:
    """Convert a URL to a short spoken form: 'link to example.com'."""
    # Strip protocol
    domain = url.split("://", 1)[-1] if "://" in url else url
    # Strip path, query, fragment
    domain = domain.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    # Strip www.
    if domain.startswith("www."):
        domain = domain[4:]
    return f"link to {domain}"


def normalize_urls_emails(text: str) -> str:
    """Replace URLs and email addresses with spoken forms."""
    # Step 1: Markdown links -> just the link text
    text = _MARKDOWN_LINK.sub(r"\1", text)

    # Step 2: General URLs
    def _replace_url(m: re.Match) -> str:
        url = m.group()
        # Strip trailing punctuation that's actually sentence-ending
        trailing = ""
        stripped = _TRAILING_PUNCT.search(url)
        if stripped:
            trailing = stripped.group()
            url = url[: stripped.start()]
        return _url_to_spoken(url) + trailing

    text = _URL.sub(_replace_url, text)

    # Step 3: Email addresses
    def _replace_email(m: re.Match) -> str:
        name = m.group(1)
        domain = m.group(2)
        return f"{name} at {domain}"

    text = _EMAIL.sub(_replace_email, text)

    return text


# ---------------------------------------------------------------------------
# Unicode math symbol dictionary
#
# ONLY Unicode codepoints — ASCII operators (-> <= >= != ~ *) are NOT
# expanded to avoid mangling code snippets and pseudocode.
# ---------------------------------------------------------------------------

_MATH_SYMBOLS: dict[str, str] = {
    # Greek lowercase
    "\u03b1": "alpha",
    "\u03b2": "beta",
    "\u03b3": "gamma",
    "\u03b4": "delta",
    "\u03b5": "epsilon",
    "\u03b6": "zeta",
    "\u03b7": "eta",
    "\u03b8": "theta",
    "\u03b9": "iota",
    "\u03ba": "kappa",
    "\u03bb": "lambda",
    "\u03bc": "mu",
    "\u03bd": "nu",
    "\u03be": "xi",
    "\u03bf": "omicron",
    "\u03c0": "pi",
    "\u03c1": "rho",
    "\u03c3": "sigma",
    "\u03c4": "tau",
    "\u03c5": "upsilon",
    "\u03c6": "phi",
    "\u03c7": "chi",
    "\u03c8": "psi",
    "\u03c9": "omega",
    # Greek uppercase (commonly used in math)
    "\u0393": "Gamma",
    "\u0394": "Delta",
    "\u0398": "Theta",
    "\u039b": "Lambda",
    "\u039e": "Xi",
    "\u03a0": "Pi",
    "\u03a3": "Sigma",
    "\u03a6": "Phi",
    "\u03a8": "Psi",
    "\u03a9": "Omega",
    # Relational operators
    "\u2264": "less than or equal to",
    "\u2265": "greater than or equal to",
    "\u2260": "not equal to",
    "\u2248": "approximately equal to",
    "\u2261": "equivalent to",
    "\u226a": "much less than",
    "\u226b": "much greater than",
    # Arithmetic / algebraic
    "\u00b1": "plus or minus",
    "\u2213": "minus or plus",
    "\u00d7": "times",
    "\u00f7": "divided by",
    "\u2219": "dot",
    "\u22c5": "dot",
    # Set theory / logic
    "\u2208": "in",
    "\u2209": "not in",
    "\u2282": "subset of",
    "\u2286": "subset of or equal to",
    "\u222a": "union",
    "\u2229": "intersection",
    "\u2200": "for all",
    "\u2203": "there exists",
    "\u00ac": "not",
    "\u2227": "and",
    "\u2228": "or",
    # Arrows
    "\u2192": "implies",
    "\u2190": "from",
    "\u2194": "if and only if",
    "\u21d2": "implies",
    "\u21d4": "if and only if",
    # Calculus / analysis
    "\u222b": "integral of",
    "\u2211": "sum of",
    "\u220f": "product of",
    "\u221e": "infinity",
    "\u2202": "partial",
    "\u2207": "nabla",
    # Superscript digits (before NFKC flattens them)
    "\u00b2": " squared",
    "\u00b3": " cubed",
    "\u00b9": " to the first",
    "\u2070": " to the zero",
    "\u2074": " to the fourth",
    "\u2075": " to the fifth",
    "\u2076": " to the sixth",
    "\u2077": " to the seventh",
    "\u2078": " to the eighth",
    "\u2079": " to the ninth",
    # Miscellaneous
    "\u221a": "square root of",
    "\u2225": "parallel to",
    "\u22a5": "perpendicular to",
    "\u2220": "angle",
    "\u00b0": " degrees",
}

# Build a regex that matches any of the symbols (longest first to avoid
# partial matches, though single-char symbols don't have that risk).
_SYMBOL_PATTERN = re.compile(
    "|".join(re.escape(s) for s in sorted(_MATH_SYMBOLS, key=len, reverse=True))
)


def normalize_math_symbols(text: str) -> str:
    """Replace Unicode math symbols with their spoken-word equivalents.

    Only handles Unicode codepoints. ASCII operators (<=, >=, ->, !=)
    are NOT expanded to avoid mangling code snippets.
    """
    return _SYMBOL_PATTERN.sub(lambda m: _MATH_SYMBOLS[m.group()], text)
