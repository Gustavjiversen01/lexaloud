"""Tests for URL/email and Unicode math symbol normalization."""

from lexaloud.preprocessor.symbols import (
    normalize_math_symbols,
    normalize_urls_emails,
)

# --- URL normalization ---


def test_url_replaced_with_domain():
    result = normalize_urls_emails("Visit https://example.com/path for details.")
    assert "link to example.com" in result
    assert "https://" not in result


def test_url_strips_www():
    result = normalize_urls_emails("See https://www.example.org for more.")
    assert "link to example.org" in result


def test_url_preserves_trailing_period():
    """Trailing sentence period must not be consumed by URL regex."""
    result = normalize_urls_emails("See https://example.com.")
    assert result.endswith(".")
    assert "link to example.com." in result


def test_url_preserves_trailing_comma():
    result = normalize_urls_emails("Check https://example.com, then continue.")
    assert "link to example.com," in result


def test_markdown_link_uses_text():
    result = normalize_urls_emails("See [the docs](https://example.com/docs) here.")
    assert "the docs" in result
    assert "https://" not in result
    assert "example.com" not in result


# --- email normalization ---


def test_email_expanded():
    result = normalize_urls_emails("Contact user@example.com for help.")
    assert "user at example.com" in result
    assert "@" not in result


def test_email_with_dots():
    result = normalize_urls_emails("Send to john.doe@university.edu please.")
    assert "john.doe at university.edu" in result


# --- Unicode math symbols ---


def test_greek_alpha():
    assert "alpha" in normalize_math_symbols("The value \u03b1 is small.")


def test_greek_beta():
    assert "beta" in normalize_math_symbols("Set \u03b2 = 0.5.")


def test_greek_pi():
    assert "pi" in normalize_math_symbols("The constant \u03c0.")


def test_greek_uppercase_sigma():
    assert "Sigma" in normalize_math_symbols("The \u03a3 notation.")


def test_less_than_or_equal():
    assert "less than or equal to" in normalize_math_symbols("If x \u2264 y.")


def test_not_equal():
    assert "not equal to" in normalize_math_symbols("When a \u2260 b.")


def test_approximately_equal():
    assert "approximately equal to" in normalize_math_symbols("x \u2248 3.14.")


def test_plus_or_minus():
    assert "plus or minus" in normalize_math_symbols("The error is \u00b1 0.5.")


def test_infinity():
    assert "infinity" in normalize_math_symbols("As n approaches \u221e.")


def test_integral():
    assert "integral of" in normalize_math_symbols("Compute \u222b f(x) dx.")


def test_for_all():
    assert "for all" in normalize_math_symbols("\u2200 x in S.")


def test_there_exists():
    assert "there exists" in normalize_math_symbols("\u2203 y such that.")


def test_implies_arrow():
    assert "implies" in normalize_math_symbols("A \u2192 B.")


def test_superscript_squared():
    result = normalize_math_symbols("x\u00b2 + y\u00b2")
    assert "squared" in result


def test_superscript_cubed():
    assert "cubed" in normalize_math_symbols("x\u00b3")


def test_degrees():
    assert "degrees" in normalize_math_symbols("Rotate by 90\u00b0.")


# --- ASCII operators are NOT expanded (stress-test M5) ---


def test_ascii_arrow_not_expanded():
    result = normalize_math_symbols("x -> y")
    assert "->" in result


def test_ascii_leq_not_expanded():
    result = normalize_math_symbols("if x <= 5")
    assert "<=" in result


def test_ascii_neq_not_expanded():
    result = normalize_math_symbols("a != b")
    assert "!=" in result


# --- edge cases ---


def test_empty_string():
    assert normalize_math_symbols("") == ""
    assert normalize_urls_emails("") == ""


def test_no_symbols():
    text = "The cat sat on the mat."
    assert normalize_math_symbols(text) == text


def test_greek_adjacent_to_text():
    """Greek letter adjacent to text should expand without breaking the word."""
    result = normalize_math_symbols("\u03b1-stable distribution")
    assert "alpha" in result
    assert "-stable" in result


# --- integration: pipeline order (math symbols before NFKC) ---


def test_superscript_before_nfkc():
    """Superscript digits should be expanded BEFORE PDF cleanup's NFKC
    normalization flattens them to plain digits."""
    from lexaloud.preprocessor import preprocess

    # x² should become "x squared" not "x2"
    sentences = preprocess("x\u00b2 + y\u00b2 = z\u00b2")
    joined = " ".join(sentences)
    assert "squared" in joined
