"""Tests for the LLM model download path (cli._download_llm_model).

Covers M3 (path traversal) and M4 (size cap) hardening.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

from lexaloud.cli import EXIT_GENERIC_ERROR, EXIT_OK, _download_llm_model
from lexaloud.config import Config, NormalizerConfig


def _cfg_with(model_file: str) -> Config:
    """Build a Config whose normalizer.model_file is the test's value."""
    cfg = Config()
    cfg.normalizer = NormalizerConfig(model_file=model_file)
    return cfg


def test_download_rejects_path_traversal(tmp_path, monkeypatch, capsys):
    """``model_file = '../../.bashrc'`` must refuse to download."""
    monkeypatch.setattr("lexaloud.config.load_config", lambda: _cfg_with("../../.bashrc"))
    monkeypatch.setattr("lexaloud.models.default_cache_dir", lambda: tmp_path)

    rc = _download_llm_model()
    assert rc == EXIT_GENERIC_ERROR
    err = capsys.readouterr().err
    assert "escapes the cache dir" in err
    # And no file was created inside or outside the cache dir.
    assert list(tmp_path.iterdir()) == []


def test_download_rejects_oversized_content_length(tmp_path, monkeypatch, capsys):
    """Server-announced Content-Length > cap → refuse."""
    monkeypatch.setattr("lexaloud.config.load_config", lambda: _cfg_with("model.gguf"))
    monkeypatch.setattr("lexaloud.models.default_cache_dir", lambda: tmp_path)
    import lexaloud.models as models_mod

    monkeypatch.setattr(models_mod, "MAX_MODEL_DOWNLOAD_BYTES", 1024)

    class _FakeResp:
        headers = {"Content-Length": "9999999"}

        def read(self, n):
            raise AssertionError("should not read once Content-Length rejected")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    @contextmanager
    def fake_urlopen(req):
        yield _FakeResp()

    # urlopen is imported inside _download_llm_model via the urllib.request
    # module, so patch that module's name.
    with patch("urllib.request.urlopen", fake_urlopen):
        # Exception propagates through the ``except BaseException`` path
        # that cleans up the tmp file — the CLI caller in practice
        # catches at a higher level; here we just verify tmp cleanup.
        import pytest

        with pytest.raises(RuntimeError, match="Content-Length exceeds cap"):
            _download_llm_model()
    assert not (tmp_path / "model.gguf").exists()
    assert not (tmp_path / "model.gguf.partial").exists()


def test_download_aborts_when_stream_exceeds_cap(tmp_path, monkeypatch):
    """Server lies or omits Content-Length and streams > cap → abort."""
    monkeypatch.setattr("lexaloud.config.load_config", lambda: _cfg_with("model.gguf"))
    monkeypatch.setattr("lexaloud.models.default_cache_dir", lambda: tmp_path)
    import lexaloud.models as models_mod

    monkeypatch.setattr(models_mod, "MAX_MODEL_DOWNLOAD_BYTES", 4 * 1024)

    class _FakeResp:
        headers: dict = {}  # no Content-Length

        def __init__(self):
            self._chunk = b"X" * 1024

        def read(self, n):
            return self._chunk

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    @contextmanager
    def fake_urlopen(req):
        yield _FakeResp()

    with patch("urllib.request.urlopen", fake_urlopen):
        import pytest

        with pytest.raises(RuntimeError, match="exceeded"):
            _download_llm_model()
    assert not (tmp_path / "model.gguf").exists()
    assert not (tmp_path / "model.gguf.partial").exists()


def test_download_accepts_valid_contained_path(tmp_path, monkeypatch):
    """A model_file that stays within the cache dir is accepted.

    This is the happy path — just a sanity check that the new
    containment logic hasn't broken it.
    """
    monkeypatch.setattr("lexaloud.config.load_config", lambda: _cfg_with("valid-model.gguf"))
    monkeypatch.setattr("lexaloud.models.default_cache_dir", lambda: tmp_path)

    # Pre-create the destination so the function takes the
    # "already exists" fast path instead of actually hitting the network.
    (tmp_path / "valid-model.gguf").write_bytes(b"stub")

    rc = _download_llm_model()
    assert rc == EXIT_OK
