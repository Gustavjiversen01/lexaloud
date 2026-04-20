"""LLM-normalizer benchmark runner (opt-in).

Skipped unless ``LEXALOUD_REAL_LLM=1`` and llama-cpp-python + the
default model are installed. LLM output is non-deterministic so we
only assert ``expected_contains`` substrings.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("LEXALOUD_REAL_LLM") != "1",
    reason="Set LEXALOUD_REAL_LLM=1 to run LLM benchmarks",
)

llama_cpp = pytest.importorskip("llama_cpp", reason="llama-cpp-python not installed")

from lexaloud.config import NormalizerConfig  # noqa: E402
from lexaloud.models import default_cache_dir  # noqa: E402
from lexaloud.preprocessor import PreprocessorConfig, preprocess_with_llm  # noqa: E402
from lexaloud.preprocessor.llm_normalize import LlmNormalizer  # noqa: E402

from .math_corpus import CORPUS, BenchmarkCase  # noqa: E402


@pytest.fixture(scope="module")
def normalizer():
    cfg = NormalizerConfig(enabled=True)
    model_path = default_cache_dir() / cfg.model_file
    if not model_path.is_file():
        pytest.skip(f"LLM model not found at {model_path}; run `lexaloud download-models --llm`")
    n = LlmNormalizer(cfg)
    yield n
    n.shutdown()


@pytest.mark.parametrize("case", CORPUS, ids=lambda c: c.name)
async def test_case_with_llm(case: BenchmarkCase, normalizer) -> None:
    cfg = PreprocessorConfig(**case.config_overrides)
    sentences = await preprocess_with_llm(case.raw_input, cfg, normalizer)
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
