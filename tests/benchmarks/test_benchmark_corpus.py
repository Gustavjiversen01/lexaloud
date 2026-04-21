"""Rule-only benchmark runner.

Iterates the shared corpus through ``preprocess()`` with no SRE and no
LLM. Pure-LaTeX cases in this runner only assert preservation — spoken
math expectations live in ``test_benchmark_corpus_sre.py``.
"""

from __future__ import annotations

import pytest

from lexaloud.preprocessor import PreprocessorConfig, preprocess

from .math_corpus import CORPUS, BenchmarkCase


@pytest.mark.parametrize("case", CORPUS, ids=lambda c: c.name)
def test_case(case: BenchmarkCase) -> None:
    cfg = PreprocessorConfig(**case.config_overrides)
    sentences = preprocess(case.raw_input, cfg)
    joined = " ".join(sentences)

    failures: list[str] = []
    for needle in case.expected_contains:
        if needle not in joined:
            failures.append(f"expected_contains missing: {needle!r}")
    for forbidden in case.expected_absent:
        if forbidden in joined:
            failures.append(f"expected_absent present: {forbidden!r}")

    if failures:
        raw_preview = case.raw_input[:200].replace("\n", "\\n")
        out_preview = joined[:400].replace("\n", "\\n")
        detail = "\n".join(
            [
                f"CASE: {case.name}",
                f"RAW:  {raw_preview}",
                f"OUT:  {out_preview}",
                *failures,
            ]
        )
        pytest.fail(detail)
