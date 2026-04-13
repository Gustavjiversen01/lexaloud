"""Tests for sentence segmentation and the full preprocess pipeline."""

from lexaloud.preprocessor import PreprocessorConfig, preprocess
from lexaloud.preprocessor.segmenter import split_sentences


def test_basic_segmentation():
    out = split_sentences("This is one. This is two. This is three.")
    assert len(out) == 3


def test_et_al_does_not_split():
    out = split_sentences("Smith et al. 2020 found a result. Jones then replied.")
    assert len(out) == 2


def test_figure_reference_does_not_split():
    out = split_sentences("See Fig. 3 for details. The results are clear.")
    assert len(out) == 2


def test_full_pipeline_runs_stages_in_order():
    text = (
        "The agent com-\npleted its task (see Fig. 3 ). As shown [12],\n"
        "the result holds for i.e. the n=5 case.\n"
    )
    sentences = preprocess(text)
    joined = " ".join(sentences)
    # de-hyphenation
    assert "completed" in joined
    # numeric citation stripped
    assert "[12]" not in joined
    # i.e. expanded
    assert "that is" in joined
    # (see Fig. 3) NOT stripped (parenthetical citations off by default)
    # Fig. is expanded to Figure by academic abbreviation expansion
    assert "Figure 3" in joined


def test_empty_input_returns_empty_list():
    assert preprocess("") == []
    assert preprocess("   \n\n   ") == []


def test_full_pipeline_with_parenthetical_strip_enabled():
    cfg = PreprocessorConfig(strip_parenthetical_citations=True)
    text = "As shown (Smith, 2023), the result follows."
    sentences = preprocess(text, cfg)
    assert all("Smith" not in s for s in sentences)
