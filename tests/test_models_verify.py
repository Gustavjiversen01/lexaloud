"""Tests for models.py — artifact cache and ONNX Runtime environment guard."""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest

from lexaloud.models import (
    ARTIFACTS,
    ArtifactError,
    OnnxruntimeEnvironmentError,
    assert_onnxruntime_environment,
    default_cache_dir,
    ensure_artifacts,
    sha256_of,
)


def test_default_cache_dir_respects_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    d = default_cache_dir()
    assert d == tmp_path / "lexaloud" / "models"


def test_sha256_of_matches_hashlib(tmp_path: Path):
    f = tmp_path / "test.bin"
    payload = b"abcdef1234567890" * 100
    f.write_bytes(payload)
    assert sha256_of(f) == hashlib.sha256(payload).hexdigest()


def test_ensure_artifacts_raises_if_missing_and_download_disabled(tmp_path):
    with pytest.raises(ArtifactError, match="missing artifact"):
        ensure_artifacts(tmp_path, download_if_missing=False)


def test_ensure_artifacts_raises_on_hash_mismatch(tmp_path):
    # Write a file with the right name but wrong content.
    for art in ARTIFACTS:
        (tmp_path / art.filename).write_bytes(b"wrong content")
    with pytest.raises(ArtifactError, match="SHA256 mismatch"):
        ensure_artifacts(tmp_path, download_if_missing=False)


def test_ensure_artifacts_happy_path_uses_real_cache():
    """Integration check against the real cached artifacts from Spike 0."""
    # The spike ran on the machine and populated the real cache dir; if the
    # cache exists and the hashes match, this should pass.
    cache = default_cache_dir()
    if not all((cache / a.filename).exists() for a in ARTIFACTS):
        pytest.skip("real artifact cache not populated on this machine")
    out = ensure_artifacts(cache, download_if_missing=False)
    assert len(out) == len(ARTIFACTS)
    for name in out:
        assert any(a.filename == name for a in ARTIFACTS)


def test_assert_onnxruntime_env_detects_gpu_only():
    with patch("lexaloud.models._is_installed", side_effect=lambda name: name == "onnxruntime-gpu"):
        assert assert_onnxruntime_environment() == "onnxruntime-gpu"


def test_assert_onnxruntime_env_detects_cpu_only():
    with patch("lexaloud.models._is_installed", side_effect=lambda name: name == "onnxruntime"):
        assert assert_onnxruntime_environment() == "onnxruntime"


def test_assert_onnxruntime_env_rejects_both_installed():
    # Multi-install = "onnxruntime" and "onnxruntime-gpu" both present.
    def _both(name: str) -> bool:
        return name in ("onnxruntime", "onnxruntime-gpu")

    with patch("lexaloud.models._is_installed", side_effect=_both):
        with pytest.raises(OnnxruntimeEnvironmentError, match="Multiple"):
            assert_onnxruntime_environment()


def test_assert_onnxruntime_env_rejects_neither_installed():
    with patch("lexaloud.models._is_installed", return_value=False):
        with pytest.raises(OnnxruntimeEnvironmentError, match="No ONNX Runtime"):
            assert_onnxruntime_environment()


def test_assert_onnxruntime_env_detects_corrupted_install():
    """A package is declared but `import onnxruntime` is broken."""

    def _only_gpu(name: str) -> bool:
        return name == "onnxruntime-gpu"

    with patch("lexaloud.models._is_installed", side_effect=_only_gpu):
        with patch("builtins.__import__", side_effect=ImportError("broken")):
            with pytest.raises(OnnxruntimeEnvironmentError, match="unusable"):
                assert_onnxruntime_environment()


def test_real_environment_is_gpu_only():
    """Integration check: the actual venv should have onnxruntime-gpu alone."""
    dist = assert_onnxruntime_environment()
    assert dist == "onnxruntime-gpu"


# --- M4 regression: _download has a size cap ---


def test_download_aborts_on_cap(tmp_path, monkeypatch):
    """``models._download`` must abort + clean up its tmp file when the
    server streams more than MAX_MODEL_DOWNLOAD_BYTES."""
    from contextlib import contextmanager

    import lexaloud.models as models_mod

    # Shrink the cap so the test runs in milliseconds instead of
    # allocating 4 GiB.
    monkeypatch.setattr(models_mod, "MAX_MODEL_DOWNLOAD_BYTES", 4 * 1024)

    class _FakeResp:
        """Returns 1 MiB blocks forever — a misbehaving server."""

        def __init__(self):
            self._block = b"X" * (1 << 10)  # 1 KiB per read (keeps test fast)

        def read(self, n: int) -> bytes:
            return self._block

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    @contextmanager
    def fake_urlopen(url):
        yield _FakeResp()

    monkeypatch.setattr(models_mod, "urlopen", fake_urlopen)

    dest = tmp_path / "evil.bin"
    with pytest.raises(ArtifactError, match="exceeded"):
        models_mod._download("https://example.invalid/evil.bin", dest)
    assert not dest.exists()
    # tmp (`.partial`) should also be gone
    assert not (tmp_path / "evil.bin.partial").exists()
