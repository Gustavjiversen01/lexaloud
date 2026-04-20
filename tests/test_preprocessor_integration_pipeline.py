"""End-to-end integration test for the preprocessor pipeline.

Runs the full ``preprocess()`` on a real MathJax/KaTeX capture (the RL
homework sample that triggered the dedupe + markdown features) and
asserts the output is readable prose with every known artifact gone.
"""

from __future__ import annotations

from pathlib import Path

from lexaloud.preprocessor import PreprocessorConfig, preprocess

FIXTURES = Path(__file__).parent / "fixtures"


def test_rl_fixture_end_to_end_rules_only():
    raw = (FIXTURES / "mathjax_rl_sample.txt").read_text()
    sentences = preprocess(raw, PreprocessorConfig())

    assert sentences, "preprocess produced no sentences"
    joined = " ".join(sentences)

    # Greek letter got expanded to its spoken name.
    assert "rho" in joined.lower()

    # MathJax duplications are gone.
    assert "X X" not in joined
    assert "x∈X x∈X" not in joined
    assert "u∈U u∈U" not in joined

    # No zero-width / NBSP residue.
    assert "\u200b" not in joined
    assert "\u00a0" not in joined

    # Markdown-style markers that never belonged in prose.
    for stray in ("**", "~~", "```"):
        assert stray not in joined

    # No leading pound sign (would come from an unstripped heading).
    for s in sentences:
        assert not s.lstrip().startswith("#")

    # At least a few sentences survive — we're not swallowing the input.
    assert len(sentences) >= 3
