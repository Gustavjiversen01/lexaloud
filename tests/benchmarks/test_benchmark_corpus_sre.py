"""SRE-on benchmark runner (opt-in).

Skipped unless ``LEXALOUD_REAL_SRE=1`` and the ``sre`` binary is
resolvable. The SRE path is non-deterministic in minor wording
("over" vs "divided by") so we only assert ``expected_contains``
substrings.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("LEXALOUD_REAL_SRE") != "1",
    reason="Set LEXALOUD_REAL_SRE=1 to run SRE benchmarks",
)

from lexaloud.preprocessor import PreprocessorConfig, preprocess  # noqa: E402
from lexaloud.preprocessor.sre_latex import is_sre_available  # noqa: E402

from .math_corpus import CORPUS, BenchmarkCase  # noqa: E402


@pytest.fixture(autouse=True)
def _require_sre():
    if not is_sre_available():
        pytest.skip("SRE not installed — run scripts/install.sh --with-math-speech")


@pytest.mark.parametrize("case", CORPUS, ids=lambda c: c.name)
def test_case_with_sre(case: BenchmarkCase) -> None:
    overrides = {"sre_latex_enabled": True, **case.config_overrides}
    cfg = PreprocessorConfig(**overrides)
    sentences = preprocess(case.raw_input, cfg)
    joined = " ".join(sentences)

    failures: list[str] = []
    for needle in case.expected_contains:
        if needle not in joined:
            failures.append(f"expected_contains missing: {needle!r}")

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
