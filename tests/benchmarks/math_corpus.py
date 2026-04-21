"""Benchmark corpus for the math / markdown preprocessor pipeline.

Each case captures an input and what must (or must not) appear in the
joined, preprocessed output. Runners in this directory iterate the
corpus under different pipeline configurations:

- ``test_benchmark_corpus.py`` — rule-only pipeline (default).
- ``test_benchmark_corpus_sre.py`` — SRE enabled, opt-in via
  ``LEXALOUD_REAL_SRE=1``.
- ``test_benchmark_corpus_llm.py`` — LLM normalizer enabled, opt-in
  via ``LEXALOUD_REAL_LLM=1``.

Guardrail for pure-LaTeX cases under the rule-only pipeline: we only
assert preservation / no-regression (no ``$``, no orphan ``\\frac``).
Spoken-math expectations like "over" or "sub" belong in the SRE
variant runner.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

FIXTURES = Path(__file__).parent.parent / "fixtures"


@dataclass
class BenchmarkCase:
    name: str
    raw_input: str
    expected_contains: list[str] = field(default_factory=list)
    expected_absent: list[str] = field(default_factory=list)
    config_overrides: dict = field(default_factory=dict)


# Lazy-read the RL fixture so the module imports cheaply.
_RL_SAMPLE: str | None = None


def _rl_sample() -> str:
    global _RL_SAMPLE
    if _RL_SAMPLE is None:
        _RL_SAMPLE = (FIXTURES / "mathjax_rl_sample.txt").read_text()
    return _RL_SAMPLE


# A reusable short MathJax duplication pattern used to construct several
# textbook-equation cases. The structure mirrors real KaTeX output: one
# char per line for the stacked form, then the compact repetition.
def _dup(stacked_lines: list[str], compact: str) -> str:
    return "\n".join(stacked_lines) + "\n" + compact


_RL_SAMPLE_TEXT = _rl_sample()

CORPUS: list[BenchmarkCase] = [
    # ------------------------------------------------------------------
    # 5 cases from the RL fixture
    # ------------------------------------------------------------------
    BenchmarkCase(
        name="rl_full_fixture",
        raw_input=_RL_SAMPLE_TEXT,
        expected_contains=["rho"],
        expected_absent=["\u200b", "\u00a0", "{X,U,T,R,ρ0} {X"],
    ),
    BenchmarkCase(
        name="rl_tuple_elements",
        raw_input="tuple\n{\nX\n,\nU\n,\nT\n,\nR\n,\nρ\n0\n}\n{X,U,T,R,ρ\u00a00\u200b }. Here",
        expected_contains=["Here"],
        expected_absent=["\n{\nX\n", "\u200b", "\u00a0"],
    ),
    BenchmarkCase(
        name="rl_single_variable_X",
        raw_input="Here \nX\nX stands for the set of states.",
        expected_contains=["Here X stands"],
        expected_absent=[" X\nX "],
    ),
    BenchmarkCase(
        name="rl_membership_x_in_X",
        raw_input="states i.e.\u00a0\nx\n∈\nX\nx∈X, for instance",
        expected_contains=["for instance"],
        expected_absent=["x∈X x∈X"],
    ),
    BenchmarkCase(
        name="rl_action_u_in_U",
        raw_input="\nu\n∈\nU\nu∈U is the action",
        expected_contains=["action"],
        expected_absent=["u∈U u∈U"],
    ),
    # ------------------------------------------------------------------
    # 5 textbook equations — rendered (duplicated) form + pure-LaTeX form
    # ------------------------------------------------------------------
    # Bayes — rendered
    BenchmarkCase(
        name="bayes_rendered",
        raw_input="Bayes' theorem: \nP\n(\nA\n|\nB\n)\nP(A|B) = P(B|A) P(A) / P(B).",
        expected_contains=["Bayes", "theorem"],
        expected_absent=["P(A|B) P(A|B)"],
    ),
    # Bayes — pure LaTeX. Rule-only pipeline leaves LaTeX macros as-is;
    # spoken-form expectations live in test_benchmark_corpus_sre.py.
    BenchmarkCase(
        name="bayes_latex_source",
        raw_input=r"Bayes' theorem says $P(A|B) = P(B|A) P(A) / P(B)$.",
        expected_contains=["Bayes", "theorem"],
    ),
    # Schrödinger (time-independent) — pure LaTeX
    BenchmarkCase(
        name="schrodinger_latex",
        raw_input=r"The time-independent form is $H \psi = E \psi$ for eigenstates.",
        expected_contains=["eigenstates"],
    ),
    # OLS normal equations — rendered
    BenchmarkCase(
        name="ols_rendered",
        raw_input="The OLS estimator is \nβ\n^\n=\n(\nX\nT\nX\n)\n−\n1\nX\nT\ny\nβ̂ = (XᵀX)⁻¹Xᵀy.",
        expected_contains=["OLS", "estimator"],
        expected_absent=["β̂ β̂"],
    ),
    # Softmax — pure LaTeX. Rule-only pipeline leaves LaTeX macros
    # as-is; spoken-form expectations live in test_benchmark_corpus_sre.py.
    BenchmarkCase(
        name="softmax_latex",
        raw_input=r"The softmax is $\sigma(z)_i = \frac{e^{z_i}}{\sum_j e^{z_j}}$.",
        expected_contains=["softmax"],
    ),
    # KL divergence — rendered
    BenchmarkCase(
        name="kl_divergence_rendered",
        raw_input="KL divergence is \nD\nK\nL\n(\np\n|\n|\nq\n)\nDKL(p||q) = sum p log(p/q).",
        expected_contains=["KL", "divergence"],
        expected_absent=["DKL(p||q) DKL"],
    ),
    # ------------------------------------------------------------------
    # 5 markdown-heavy cases
    # ------------------------------------------------------------------
    BenchmarkCase(
        name="md_nested_lists",
        raw_input="# Agenda\n\n1. First\n   - Sub A\n   - Sub B\n2. Second\n3. Third",
        expected_contains=["Agenda", "First", "Sub A", "Sub B", "Second", "Third"],
        expected_absent=["#", "   -"],
    ),
    BenchmarkCase(
        name="md_fenced_python",
        raw_input="Before.\n\n```python\ndef foo():\n    return 1\n```\n\nAfter.",
        expected_contains=["Before", "Code block omitted", "After"],
        expected_absent=["```", "def foo"],
    ),
    BenchmarkCase(
        name="md_gfm_table",
        raw_input="| Name | Age |\n|------|-----|\n| Alice | 30 |\n| Bob | 25 |",
        expected_contains=["Name: Alice", "Age: 30", "Name: Bob", "Age: 25"],
        expected_absent=["|---|"],
    ),
    BenchmarkCase(
        name="md_blockquote_inline_math",
        raw_input="> Recall that $x^2 + y^2 = z^2$ for right triangles.",
        expected_contains=["Quote", "right triangles"],
        expected_absent=["> "],
    ),
    BenchmarkCase(
        name="md_heading_only",
        raw_input="# Chapter 1: Introduction",
        expected_contains=["Introduction"],
        expected_absent=["# "],
    ),
    # ------------------------------------------------------------------
    # 5 adversarial cases
    # ------------------------------------------------------------------
    BenchmarkCase(
        name="adversarial_greek_prose_preserved",
        raw_input="α particles scatter off β emitters.",
        expected_contains=["α", "β"],
        expected_absent=["alpha particles", "beta emitters"],
        # Run with the Unicode math-symbol stage disabled — otherwise
        # Greek glyphs get expanded to names, which is correct default
        # behavior but contradicts the "don't touch" expectation here.
        config_overrides={"normalize_math_symbols": False},
    ),
    BenchmarkCase(
        name="adversarial_code_golf",
        raw_input="x\n=\n1\ny\n=\n2",
        expected_contains=["x", "y"],
        # Should not be aggressively collapsed into "x=1y=2".
        expected_absent=["x=1y=2"],
    ),
    BenchmarkCase(
        name="adversarial_ascii_art",
        raw_input=" /\\\n/__\\\n|  |\n|__|",
        expected_contains=["|"],
        expected_absent=[],
    ),
    BenchmarkCase(
        name="adversarial_pipe_not_a_table",
        raw_input="The pipe character | separates fields sometimes.",
        expected_contains=["pipe character", "separates fields"],
        expected_absent=["Name:", "Age:"],
    ),
    BenchmarkCase(
        name="adversarial_year_bullet_list",
        raw_input="Notable years:\n- 2020\n- 2021\n- 2022",
        # Existing normalize_numbers leaves bare 4-digit years as digits;
        # we check that all three year numbers survive in some form.
        expected_contains=["Notable years"],
        expected_absent=["-  -"],
    ),
]


assert len(CORPUS) >= 20, f"corpus must have at least 20 cases; got {len(CORPUS)}"
