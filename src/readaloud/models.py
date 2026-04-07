"""Model artifact download/verify + ONNX Runtime environment guard.

Pinned URLs + SHA256 hashes come from Spike 0 (see `spikes/spike0_results.md`).

Two jobs:

1. `ensure_artifacts(cache_dir)` — make sure the Kokoro ONNX model and voices
   pack are present and hash-verified. Downloads missing files to a
   `.partial` staging path and renames on success; unlinks the partial on
   any error so a failed download doesn't leave stale bytes behind.

2. `assert_onnxruntime_environment()` — detect the known-broken states where
   - both `onnxruntime` and `onnxruntime-gpu` (or other variants) are
     installed in the same venv, and
   - the shared `onnxruntime/` directory has been corrupted by a
     `pip uninstall onnxruntime` that also ripped out files shared with
     `onnxruntime-gpu`.

   Spike 0 demonstrated both failure modes on the target Ubuntu 24.04 +
   RTX 5080 box.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.request import urlopen

log = logging.getLogger(__name__)


# ---------- artifact pins (from Spike 0) --------------------------------


OPTION_A_TAG = "model-files-v1.0"
OPTION_A_BASE = f"https://github.com/thewh1teagle/kokoro-onnx/releases/download/{OPTION_A_TAG}"


@dataclass(frozen=True)
class Artifact:
    filename: str
    url: str
    sha256: str
    expected_size: int  # informational; SHA256 is the authoritative check


ARTIFACTS: tuple[Artifact, ...] = (
    Artifact(
        filename="kokoro-v1.0.onnx",
        url=f"{OPTION_A_BASE}/kokoro-v1.0.onnx",
        sha256="7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5",
        expected_size=325_532_387,
    ),
    Artifact(
        filename="voices-v1.0.bin",
        url=f"{OPTION_A_BASE}/voices-v1.0.bin",
        sha256="bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d",
        expected_size=28_214_398,
    ),
)


def default_cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME")
    root = Path(base) if base else Path.home() / ".cache"
    return root / "readaloud" / "models"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class ArtifactError(RuntimeError):
    """Raised for missing-or-corrupt model artifacts."""


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".partial")
    log.info("downloading %s -> %s", url, dest)
    try:
        with urlopen(url) as resp, tmp.open("wb") as f:
            while True:
                block = resp.read(1 << 20)
                if not block:
                    break
                f.write(block)
        tmp.replace(dest)
    except BaseException:
        # Never leave a half-written .partial behind on failure.
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise


def ensure_artifacts(
    cache_dir: Path | None = None, *, download_if_missing: bool = True
) -> dict[str, Path]:
    """Ensure the Kokoro artifacts are present and hash-verified.

    Returns a mapping of filename -> absolute path.

    Raises:
        ArtifactError: if files are missing and `download_if_missing=False`,
            or if a file exists but has the wrong SHA256.
    """
    cache = (cache_dir or default_cache_dir()).expanduser().resolve()
    cache.mkdir(parents=True, exist_ok=True)

    out: dict[str, Path] = {}
    for art in ARTIFACTS:
        path = cache / art.filename
        if not path.exists():
            if not download_if_missing:
                raise ArtifactError(
                    f"missing artifact: {path}. Run `readaloud download-models` to fetch it."
                )
            _download(art.url, path)
        digest = sha256_of(path)
        if digest != art.sha256:
            raise ArtifactError(
                f"SHA256 mismatch for {path}\n"
                f"  expected: {art.sha256}\n"
                f"  got:      {digest}\n"
                f"  delete the file and re-run `readaloud download-models`."
            )
        out[art.filename] = path
    return out


# ---------- ONNX Runtime environment guard ------------------------------


class OnnxruntimeEnvironmentError(RuntimeError):
    """The onnxruntime/onnxruntime-gpu environment is in a broken state."""


# Every ONNX Runtime distribution known to ship its Python module under
# `onnxruntime/` — installing more than one into the same venv silently
# shadows the others.
KNOWN_ORT_DISTS: tuple[str, ...] = (
    "onnxruntime",
    "onnxruntime-gpu",
    "onnxruntime-openvino",
    "onnxruntime-directml",
    "onnxruntime-rocm",
    "onnxruntime-qnn",
    "onnxruntime-migraphx",
)


def _is_installed(name: str) -> bool:
    try:
        importlib.metadata.version(name)
        return True
    except importlib.metadata.PackageNotFoundError:
        return False


def assert_onnxruntime_environment() -> str:
    """Verify the ONNX Runtime install shape is usable.

    Returns the name of the installed distribution (e.g., "onnxruntime-gpu").

    Raises:
        OnnxruntimeEnvironmentError: if zero or more than one ONNX Runtime
            distribution is installed in the venv, OR if the one that is
            installed is unusable (missing `__version__`, import raises,
            etc.) — typically a post-`pip uninstall` corruption state.
    """
    installed = [n for n in KNOWN_ORT_DISTS if _is_installed(n)]

    if len(installed) == 0:
        raise OnnxruntimeEnvironmentError(
            "No ONNX Runtime distribution is installed. "
            "Install the ReadAloud package via scripts/install.sh."
        )

    if len(installed) > 1:
        raise OnnxruntimeEnvironmentError(
            f"Multiple ONNX Runtime distributions installed: {installed}. "
            "ONNX Runtime does not support this configuration; the Python "
            "module directory is shared and imports will silently shadow "
            "each other. Do NOT try to `pip uninstall` one of them — that "
            "will corrupt the shared directory and break both.\n\n"
            "Fix: delete the venv and rerun scripts/install.sh."
        )

    # Finally, verify the one installed distribution is actually importable.
    # This catches the post-`pip uninstall onnxruntime` corruption Spike 0
    # flagged, where dist-info survives but the shared directory is broken.
    try:
        import onnxruntime as ort  # type: ignore

        _ = ort.__version__
        _ = ort.get_available_providers()
    except Exception as e:  # noqa: BLE001
        raise OnnxruntimeEnvironmentError(
            f"ONNX Runtime ({installed[0]}) is installed but unusable "
            f"({type(e).__name__}: {e}). "
            "This often happens after `pip uninstall onnxruntime` on a venv "
            "that previously had both onnxruntime and onnxruntime-gpu.\n\n"
            "Fix: delete the venv and rerun scripts/install.sh."
        ) from e

    if installed[0] not in ("onnxruntime", "onnxruntime-gpu"):
        log.warning(
            "Detected %s; ReadAloud v1 only tests onnxruntime-gpu and "
            "onnxruntime (CPU). CUDA EP path may not be used.",
            installed[0],
        )

    return installed[0]
