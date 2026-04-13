"""Tests for the NormalizerConfig dataclass and TOML loading."""

from pathlib import Path

from lexaloud.config import Config, NormalizerConfig, load_config


def test_default_normalizer_disabled():
    cfg = Config()
    assert cfg.normalizer.enabled is False
    assert cfg.normalizer.glossary == {}


def test_normalizer_config_defaults():
    nc = NormalizerConfig()
    assert nc.model_repo == "Qwen/Qwen2.5-1.5B-Instruct-GGUF"
    assert nc.model_file == "qwen2.5-1.5b-instruct-q4_k_m.gguf"
    assert nc.n_gpu_layers == -1
    assert nc.n_ctx == 4096
    assert nc.temperature == 0.0
    assert nc.max_output_ratio == 1.5


def test_load_config_normalizer_enabled(tmp_path: Path):
    p = tmp_path / "config.toml"
    p.write_text('[normalizer]\nenabled = true\nn_gpu_layers = 0\n')
    cfg = load_config(p)
    assert cfg.normalizer.enabled is True
    assert cfg.normalizer.n_gpu_layers == 0
    # Other fields keep defaults
    assert cfg.normalizer.temperature == 0.0


def test_load_config_normalizer_glossary(tmp_path: Path):
    p = tmp_path / "config.toml"
    p.write_text(
        '[normalizer]\n'
        'enabled = true\n'
        '\n'
        '[normalizer.glossary]\n'
        'MAPPO = "Multi-Agent Proximal Policy Optimization"\n'
        'GCBF = "Graph Control Barrier Function"\n'
    )
    cfg = load_config(p)
    assert cfg.normalizer.enabled is True
    assert cfg.normalizer.glossary["MAPPO"] == "Multi-Agent Proximal Policy Optimization"
    assert cfg.normalizer.glossary["GCBF"] == "Graph Control Barrier Function"


def test_load_config_normalizer_glossary_inline_table(tmp_path: Path):
    """TOML inline table syntax for glossary should also work."""
    p = tmp_path / "config.toml"
    p.write_text(
        '[normalizer]\n'
        'enabled = true\n'
        'glossary = { GPU = "graphics processing unit" }\n'
    )
    cfg = load_config(p)
    assert cfg.normalizer.glossary["GPU"] == "graphics processing unit"


def test_load_config_unknown_normalizer_keys_ignored(tmp_path: Path):
    p = tmp_path / "config.toml"
    p.write_text('[normalizer]\nenabled = true\nfuture_key = "whatever"\n')
    cfg = load_config(p)
    assert cfg.normalizer.enabled is True
    assert not hasattr(cfg.normalizer, "future_key")


def test_load_config_without_normalizer_section(tmp_path: Path):
    """Config without [normalizer] should use defaults (disabled)."""
    p = tmp_path / "config.toml"
    p.write_text('[provider]\nvoice = "af_bella"\n')
    cfg = load_config(p)
    assert cfg.normalizer.enabled is False
    assert cfg.normalizer.glossary == {}
