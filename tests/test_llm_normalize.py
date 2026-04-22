"""Tests for the LLM normalizer — all work WITHOUT llama-cpp-python installed."""

from unittest.mock import patch

from lexaloud.config import NormalizerConfig
from lexaloud.preprocessor.llm_normalize import (
    LlmNormalizer,
    _needs_llm,
)

# --- glossary ---


def test_glossary_applies_word_boundaries():
    cfg = NormalizerConfig(glossary={"GPU": "graphics processing unit"})
    n = LlmNormalizer(cfg)
    result = n._apply_glossary("The GPU outperforms the CPU.")
    assert "graphics processing unit" in result
    # CPU is not in glossary, should remain
    assert "CPU" in result


def test_glossary_multiple_entries():
    cfg = NormalizerConfig(glossary={"MAPPO": "Multi-Agent PPO", "GCBF": "Graph CBF"})
    n = LlmNormalizer(cfg)
    result = n._apply_glossary("We compare MAPPO and GCBF.")
    assert "Multi-Agent PPO" in result
    assert "Graph CBF" in result


def test_glossary_non_string_value_skipped():
    """Non-string glossary values are skipped with a warning (M15)."""
    cfg = NormalizerConfig(glossary={"BAD": 42, "GOOD": "good value"})
    n = LlmNormalizer(cfg)
    # Only GOOD should be in the compiled patterns
    assert len(n._glossary) == 1


def test_glossary_empty():
    cfg = NormalizerConfig(glossary={})
    n = LlmNormalizer(cfg)
    text = "Nothing to replace here."
    assert n._apply_glossary(text) == text


# --- _needs_llm heuristic ---


def test_needs_llm_false_for_plain_prose():
    assert _needs_llm("The cat sat on the mat.") is False


def test_needs_llm_false_for_common_acronyms():
    """Common acronyms (USA, CEO, AI) should NOT trigger the LLM (H7)."""
    assert _needs_llm("The USA and EU signed a treaty.") is False
    assert _needs_llm("The CEO and CTO met.") is False


def test_needs_llm_true_for_unknown_acronyms():
    """Two or more unknown uppercase acronyms trigger the LLM."""
    assert _needs_llm("We compare MAPPO and GCBF on the SMAC benchmark.") is True


def test_needs_llm_single_unknown_not_enough():
    """A single unknown acronym is not enough (threshold >= 2)."""
    assert _needs_llm("The MAPPO algorithm is efficient.") is False


def test_needs_llm_true_for_latex():
    assert _needs_llm(r"Consider $\frac{1}{2}$ of the total.") is True


def test_needs_llm_true_for_latex_command():
    assert _needs_llm(r"We use \sqrt{n} as the bound.") is True


def test_needs_llm_true_for_table():
    assert _needs_llm("| Name | Score |\n| Alice | 95 |") is True


def test_needs_llm_false_for_single_pipe():
    """A single pipe is not a table."""
    assert _needs_llm("The value is x | y.") is False


# --- normalize graceful degradation ---


async def test_normalize_returns_input_when_llama_missing():
    """If llama-cpp-python is not installed, normalize returns input unchanged."""
    cfg = NormalizerConfig(enabled=True)
    n = LlmNormalizer(cfg)

    with patch.dict("sys.modules", {"llama_cpp": None}):
        # Force _needs_llm to return True so we actually try the LLM path
        with patch("lexaloud.preprocessor.llm_normalize._needs_llm", return_value=True):
            result = await n.normalize("Test text with MAPPO and GCBF here.")

    assert "Test text" in result


async def test_normalize_skips_llm_for_plain_text():
    """Plain prose should return unchanged without ever touching the LLM."""
    cfg = NormalizerConfig(enabled=True)
    n = LlmNormalizer(cfg)
    result = await n.normalize("The cat sat on the mat.")
    assert result == "The cat sat on the mat."


async def test_normalize_applies_glossary_even_without_llm():
    """Glossary should work even when LLM is not available."""
    cfg = NormalizerConfig(
        enabled=True,
        glossary={"MAPPO": "Multi-Agent Proximal Policy Optimization"},
    )
    n = LlmNormalizer(cfg)
    result = await n.normalize("The MAPPO algorithm.")
    assert "Multi-Agent Proximal Policy Optimization" in result


# --- postprocess ---


def test_postprocess_strips_preamble():
    cfg = NormalizerConfig()
    n = LlmNormalizer(cfg)
    result = n._postprocess(
        "original text",
        "Here is the normalized version:\nThe actual output text.",
    )
    assert result == "The actual output text."


def test_postprocess_strips_sure_preamble():
    cfg = NormalizerConfig()
    n = LlmNormalizer(cfg)
    result = n._postprocess(
        "original text",
        "Sure, here you go:\nThe actual output.",
    )
    assert result == "The actual output."


def test_postprocess_rejects_too_short():
    """Output <10% of input length should fall back to original (M7)."""
    cfg = NormalizerConfig()
    n = LlmNormalizer(cfg)
    result = n._postprocess("A very long input text with many words", "x")
    assert result == "A very long input text with many words"


def test_postprocess_rejects_too_long():
    """Output >300% of input length should fall back to original (M7)."""
    cfg = NormalizerConfig()
    n = LlmNormalizer(cfg)
    result = n._postprocess("short", "x " * 500)
    assert result == "short"


def test_postprocess_rejects_empty():
    cfg = NormalizerConfig()
    n = LlmNormalizer(cfg)
    result = n._postprocess("original", "")
    assert result == "original"


def test_postprocess_passes_reasonable_output():
    cfg = NormalizerConfig()
    n = LlmNormalizer(cfg)
    result = n._postprocess(
        "The MAPPO algo is good.",
        "The Multi-Agent Proximal Policy Optimization algorithm is good.",
    )
    assert "Multi-Agent" in result


# --- shutdown ---


def test_shutdown_when_never_initialized():
    """shutdown() on a never-initialized normalizer should not raise."""
    cfg = NormalizerConfig()
    n = LlmNormalizer(cfg)
    n.shutdown()  # should not raise


# --- M3 regression: load-path containment ---


async def test_path_traversal_in_model_file_rejected(monkeypatch, tmp_path, caplog):
    """A config with model_file that escapes the cache dir must be refused
    at load time — _ensure_initialized sets _available=False and returns."""
    import logging

    cfg = NormalizerConfig(enabled=True, model_file="../../.bashrc")
    n = LlmNormalizer(cfg)

    # Point default_cache_dir at a real tmp_path so the resolve check runs
    # against a realistic base. Without this, the malicious path might
    # resolve somewhere that accidentally satisfies containment.
    monkeypatch.setattr("lexaloud.models.default_cache_dir", lambda: tmp_path)

    # Pretend llama_cpp IS importable so we get past the first guard and
    # actually hit the path-containment check.
    class _FakeLlama:
        def __init__(self, *a, **kw):
            raise AssertionError("Llama() must not be invoked when path escapes")

    import sys

    fake_llama_cpp = type(sys)("llama_cpp")
    fake_llama_cpp.Llama = _FakeLlama  # type: ignore[attr-defined]

    with caplog.at_level(logging.ERROR, logger="lexaloud.preprocessor.llm_normalize"):
        with patch.dict("sys.modules", {"llama_cpp": fake_llama_cpp}):
            ok = await n._ensure_initialized()

    assert ok is False
    assert n._available is False
    # The log should mention the escape.
    assert any("escape" in rec.getMessage().lower() for rec in caplog.records)
