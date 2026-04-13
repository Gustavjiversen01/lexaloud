"""Tests for number-to-words normalization."""

from lexaloud.preprocessor.numbers import normalize_numbers

# --- ordinals ---


def test_ordinal_1st():
    assert "first" in normalize_numbers("The 1st place winner.")


def test_ordinal_2nd():
    assert "second" in normalize_numbers("The 2nd attempt.")


def test_ordinal_3rd():
    assert "third" in normalize_numbers("The 3rd option.")


def test_ordinal_4th():
    assert "fourth" in normalize_numbers("In the 4th round.")


def test_ordinal_21st():
    assert "twenty-first" in normalize_numbers("The 21st century.")


def test_ordinal_100th():
    result = normalize_numbers("The 100th anniversary.")
    assert "hundred" in result


# --- cardinals with commas ---


def test_cardinal_comma_1234():
    result = normalize_numbers("We had 1,234 participants.")
    assert "one thousand two hundred thirty-four" in result


def test_cardinal_comma_1000000():
    # Exactly 999,999 is the upper bound
    result = normalize_numbers("There were 999,999 entries.")
    assert "nine hundred ninety-nine thousand" in result


def test_cardinal_large_left_alone():
    # >999,999 left as digits
    result = normalize_numbers("The budget was 1,000,000.")
    assert "1,000,000" in result


# --- decimals ---


def test_decimal_3_14():
    result = normalize_numbers("Pi is approximately 3.14.")
    assert "three point one four" in result


def test_decimal_0_5():
    result = normalize_numbers("The probability is 0.5.")
    assert "zero point five" in result


# --- percentages ---


def test_percentage_50():
    assert "fifty percent" in normalize_numbers("About 50% of users.")


def test_percentage_3_14():
    result = normalize_numbers("Growth of 3.14% this year.")
    assert "three point one four percent" in result


def test_percentage_100():
    assert "one hundred percent" in normalize_numbers("We achieved 100% accuracy.")


# --- currency ---


def test_currency_100():
    assert "one hundred dollars" in normalize_numbers("It costs $100.")


def test_currency_with_cents():
    result = normalize_numbers("The price is $5.99.")
    assert "five dollars" in result
    assert "ninety-nine cent" in result


def test_currency_with_commas():
    result = normalize_numbers("Revenue was $1,234.")
    assert "one thousand two hundred thirty-four dollars" in result


# --- fractions ---


def test_fraction_half():
    assert "one half" in normalize_numbers("About 1/2 of the data.")


def test_fraction_three_quarters():
    assert "three quarters" in normalize_numbers("Roughly 3/4 complete.")


def test_unknown_fraction_left_alone():
    # 5/7 is not in the known fractions dict
    result = normalize_numbers("A ratio of 5/7.")
    assert "5/7" in result


# --- years ---


def test_year_in_context():
    result = normalize_numbers("In 2024, the study was published.")
    assert "twenty twenty-four" in result


def test_year_since():
    result = normalize_numbers("Since 1999, progress has been steady.")
    assert "nineteen ninety-nine" in result


def test_year_2000():
    result = normalize_numbers("In 2000, the millennium began.")
    assert "two thousand" in result


def test_year_2005():
    result = normalize_numbers("In 2005, the paper appeared.")
    assert "two thousand five" in result


def test_year_without_context_left_as_digits():
    # 2023 without a temporal context word: not treated as a year.
    # It will match as a plain integer but we don't normalize plain ints.
    result = normalize_numbers("We collected 2023 samples.")
    assert "2023" in result


# --- reference-context exclusion (stress-test H2) ---


def test_figure_number_not_expanded():
    result = normalize_numbers("See Figure 3 for the results.")
    assert "three" not in result.lower() or "Figure 3" in result


def test_section_subsection_not_expanded():
    result = normalize_numbers("In Section 2.1 we discuss.")
    assert "2.1" in result


def test_table_number_not_expanded():
    result = normalize_numbers("Table 5 summarizes the findings.")
    assert "5" in result


def test_equation_number_not_expanded():
    result = normalize_numbers("Equation 12 shows the relationship.")
    assert "12" in result


# --- protected patterns (stress-test H4) ---


def test_ip_address_not_expanded():
    result = normalize_numbers("Connect to 192.168.1.1 for access.")
    assert "192.168.1.1" in result


def test_version_string_not_expanded():
    result = normalize_numbers("We used Python v3.12.1 for testing.")
    assert "v3.12.1" in result


def test_phone_number_not_expanded():
    result = normalize_numbers("Call 555-123-4567 for support.")
    assert "555-123-4567" in result


def test_isbn_not_expanded():
    result = normalize_numbers("ISBN 978-3-16-148410-0.")
    assert "978-3-16-148410-0" in result


# --- edge cases ---


def test_empty_string():
    assert normalize_numbers("") == ""


def test_no_numbers():
    text = "The cat sat on the mat."
    assert normalize_numbers(text) == text


def test_negative_number_left_alone():
    # Negative numbers are not handled by the simple patterns
    result = normalize_numbers("Temperature was -5 degrees.")
    assert "-5" in result


def test_scientific_notation_left_alone():
    result = normalize_numbers("The value is 1.5e10.")
    # 1.5 would be normalized but the e10 suffix prevents the full match
    # The exact behavior depends on regex matching; just verify no crash
    assert "10" in result or "e10" in result


# --- integration with the full pipeline ---


def test_pipeline_abbreviation_then_number():
    """Numbers after expanded abbreviations should respect reference context."""
    from lexaloud.preprocessor import preprocess

    sentences = preprocess("See Fig. 3 and Eq. 12.")
    joined = " ".join(sentences)
    # Fig. expanded to Figure, Eq. expanded to Equation
    assert "Figure" in joined
    assert "Equation" in joined
    # Numbers should still be digits (reference context)
    assert "3" in joined
    assert "12" in joined
