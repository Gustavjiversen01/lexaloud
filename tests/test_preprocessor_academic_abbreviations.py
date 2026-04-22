"""Tests for academic abbreviation expansion."""

from lexaloud.preprocessor.academic_abbreviations import (
    expand_academic_abbreviations,
)

# --- figure / equation / section references ---


def test_fig_expands():
    assert "Figure 3" in expand_academic_abbreviations("See Fig. 3 for details.")


def test_eq_expands():
    assert "Equation 1" in expand_academic_abbreviations("Eq. 1 shows the result.")


def test_eqn_expands():
    assert "Equation" in expand_academic_abbreviations("Eqn. 5 is derived from")


def test_sec_expands():
    assert "Section 2" in expand_academic_abbreviations("In Sec. 2 we discuss")


def test_ref_expands():
    assert "Reference" in expand_academic_abbreviations("See Ref. 4.")


def test_tab_expands():
    assert "Table" in expand_academic_abbreviations("Tab. 1 summarizes")


def test_vol_expands():
    assert "Volume" in expand_academic_abbreviations("Vol. 12, pp.")


def test_ch_expands():
    assert "Chapter" in expand_academic_abbreviations("See Ch. 3.")


def test_chap_expands():
    assert "Chapter" in expand_academic_abbreviations("In Chap. 4 we")


def test_def_expands():
    assert "Definition" in expand_academic_abbreviations("By Def. 1,")


def test_thm_expands():
    assert "Theorem" in expand_academic_abbreviations("Thm. 2 states")


def test_lem_expands():
    assert "Lemma" in expand_academic_abbreviations("From Lem. 3,")


def test_cor_expands():
    assert "Corollary" in expand_academic_abbreviations("Cor. 1 follows")


def test_prop_expands():
    assert "Proposition" in expand_academic_abbreviations("Prop. 5 shows")


def test_ex_expands():
    assert "Example" in expand_academic_abbreviations("Ex. 2 illustrates")


def test_rem_expands():
    assert "Remark" in expand_academic_abbreviations("Rem. 1 notes")


def test_approx_expands():
    assert "approximately" in expand_academic_abbreviations("Approx. 50% of")


# --- page references ---


def test_p_with_digit():
    result = expand_academic_abbreviations("See p. 42.")
    assert "page" in result
    assert "42" in result


def test_pp_with_digit():
    result = expand_academic_abbreviations("See pp. 10-15.")
    assert "pages" in result


def test_p_does_not_match_pm():
    """p. in p.m. should NOT be expanded."""
    result = expand_academic_abbreviations("It is 5 p.m. today.")
    assert "page" not in result
    assert "p.m." in result


def test_p_does_not_match_pdf():
    """p. inside abbreviations like p.d.f. should NOT be expanded."""
    # p.d.f. doesn't contain the pattern "p." followed by a digit
    result = expand_academic_abbreviations("The p.d.f. function is")
    assert "page" not in result


# --- No. ---


def test_no_with_digit():
    result = expand_academic_abbreviations("No. 5 in the series.")
    assert "Number" in result


def test_no_sentence_final_not_expanded():
    """Sentence-final 'No.' meaning a negative should NOT be expanded."""
    result = expand_academic_abbreviations("The answer is No.")
    assert "Number" not in result
    assert "No." in result


# --- Latin-style academic abbreviations ---


def test_wrt_expands():
    assert "with respect to" in expand_academic_abbreviations("w.r.t. the baseline")


def test_wrt_case_insensitive():
    assert "with respect to" in expand_academic_abbreviations("W.R.T. the baseline")


def test_st_lowercase():
    """s.t. (such that) should expand when lowercase."""
    result = expand_academic_abbreviations("We minimize f(x) s.t. g(x) <= 0.")
    assert "such that" in result


def test_st_does_not_match_saint():
    """St. (as in St. Louis) should NOT be matched by the s.t. pattern."""
    result = expand_academic_abbreviations("St. Louis is a city.")
    assert "such that" not in result
    assert "St." in result


# --- L1 regression: s.t. expands at sentence-boundary lookaheads ---


def test_st_at_end_of_string_expanded():
    """``s.t.`` at end-of-string matched via ``$`` lookahead."""
    result = expand_academic_abbreviations("Minimize f(x) s.t.")
    assert "such that" in result
    assert "s.t." not in result


def test_st_before_comma_expanded():
    """``s.t.,`` — comma satisfies the boundary lookahead."""
    result = expand_academic_abbreviations("Find x, s.t., y > 0.")
    assert "such that" in result
    # The comma after the expansion stays intact.
    assert "such that," in result


def test_iid_expands():
    result = expand_academic_abbreviations("Samples are i.i.d. random variables.")
    assert "independently and identically distributed" in result


def test_wlog_expands():
    result = expand_academic_abbreviations("W.l.o.g. assume x > 0.")
    assert "without loss of generality" in result


def test_et_seq_expands():
    result = expand_academic_abbreviations("Article 5 et seq. applies.")
    assert "and following" in result


# --- multiple abbreviations in one sentence ---


def test_multiple_abbreviations():
    text = "See Eq. 3 and Thm. 4 in Sec. 2."
    result = expand_academic_abbreviations(text)
    assert "Equation" in result
    assert "Theorem" in result
    assert "Section" in result


# --- case insensitivity ---


def test_fig_case_insensitive():
    assert "Figure" in expand_academic_abbreviations("FIG. 1 shows")
    assert "Figure" in expand_academic_abbreviations("fig. 1 shows")


# --- integration: abbreviation before sentence splitting ---


def test_expansion_before_splitting_prevents_mis_segmentation():
    """Expanding 'Eq.' to 'Equation' removes a period that pysbd
    would otherwise treat as a sentence boundary."""
    from lexaloud.preprocessor import preprocess

    sentences = preprocess("See Eq. 3. Next sentence.")
    # Should be 2 sentences, not 3 (Eq. should not cause a split)
    assert len(sentences) == 2
    assert "Equation" in sentences[0]
