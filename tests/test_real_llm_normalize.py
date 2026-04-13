"""Opt-in integration test for the real LLM normalizer.

Requires:
  - llama-cpp-python installed (pip install lexaloud[llm])
  - LLM model downloaded (lexaloud download-models --llm)
  - LEXALOUD_REAL_LLM=1 environment variable

Run:
  LEXALOUD_REAL_LLM=1 python -m pytest tests/test_real_llm_normalize.py -s
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("LEXALOUD_REAL_LLM") != "1",
    reason="Set LEXALOUD_REAL_LLM=1 to run real LLM integration tests",
)

llama_cpp = pytest.importorskip("llama_cpp", reason="llama-cpp-python not installed")

from lexaloud.config import NormalizerConfig  # noqa: E402
from lexaloud.models import default_cache_dir  # noqa: E402
from lexaloud.preprocessor.llm_normalize import LlmNormalizer  # noqa: E402


@pytest.fixture(scope="module")
def normalizer():
    """Create a real LlmNormalizer with the downloaded model."""
    cfg = NormalizerConfig(enabled=True)
    model_path = default_cache_dir() / cfg.model_file
    if not model_path.is_file():
        pytest.skip(f"LLM model not found at {model_path}; run lexaloud download-models --llm")
    n = LlmNormalizer(cfg)
    yield n
    n.shutdown()


async def test_glossary_expansion(normalizer):
    """Glossary should expand domain-specific acronyms."""
    cfg = NormalizerConfig(
        enabled=True,
        glossary={"MAPPO": "Multi-Agent Proximal Policy Optimization"},
    )
    n = LlmNormalizer(cfg)
    result = await n.normalize("The MAPPO algorithm is efficient.")
    assert "Multi-Agent Proximal Policy Optimization" in result
    n.shutdown()


async def test_plain_text_passthrough(normalizer):
    """Plain prose should return unchanged (fast path)."""
    text = "The cat sat on the mat."
    result = await normalizer.normalize(text)
    assert result == text


async def test_llm_handles_acronyms(normalizer):
    """The LLM should attempt to expand unknown acronyms."""
    result = await normalizer.normalize(
        "We evaluate MAPPO and GCBF on the SMAC benchmark."
    )
    # The LLM should modify the text in some way
    assert result != "We evaluate MAPPO and GCBF on the SMAC benchmark."
    # Core content should be preserved
    assert "benchmark" in result.lower()


async def test_llm_handles_math(normalizer):
    r"""The LLM should normalize LaTeX-like math."""
    result = await normalizer.normalize(
        r"Consider $\frac{1}{2}$ of the total."
    )
    # Should mention "half" or "one over two" or similar
    assert "frac" not in result.lower()
