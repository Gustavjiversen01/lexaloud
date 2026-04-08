"""
Spike 0 — Kokoro standalone on target hardware.

Goal: verify that kokoro-onnx can load a model on the RTX 5080 via an
explicitly-constructed onnxruntime InferenceSession, synthesize a 30-second
dense-academic passage, and play it through sounddevice.

This script is intentionally verbose: it records every piece of state that
might matter for a bug report or a future dependency-drift debug. It writes
the results to spike0_results.md alongside this script so the repo has a
provenance record of what worked on the target machine.

Usage (from a venv that has kokoro-onnx and onnxruntime-gpu installed):

    cd spikes/
    python spike0_kokoro.py [--cpu]  # --cpu forces CPUExecutionProvider
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path

# The model artifacts live in ~/.cache/lexaloud/models/ so we have a stable
# path that doesn't depend on the venv or the source checkout.
CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "lexaloud" / "models"

# --- Artifact sources (Spike 0 picks one; both are documented) -----------
#
# Option A: thewh1teagle/kokoro-onnx GitHub release assets
#   - URL pattern: https://github.com/thewh1teagle/kokoro-onnx/releases/download/<tag>/<file>
#   - Pin a tag (e.g. "model-files-v1.0") and verify SHA256.
#
# Option B: onnx-community/Kokoro-82M-v1.0-ONNX on Hugging Face
#   - Fetch via huggingface_hub.hf_hub_download with a pinned `revision` commit SHA.
#   - Adjust filenames to what that repo ships.
#
# This script starts with Option A because it's simpler (no extra dependency
# on huggingface_hub). If Option A's asset names or hashes don't match the
# installed kokoro-onnx version, fall back to Option B.
#
# NOTE: these SHA256 values are placeholders until the spike is run for real.
# The spike will print the actual hash of what it downloaded so the constant
# can be committed after verification.
OPTION_A_TAG = "model-files-v1.0"
OPTION_A_BASE = f"https://github.com/thewh1teagle/kokoro-onnx/releases/download/{OPTION_A_TAG}"
# SHA256 pinned from the first successful download on 2026-04-07.
# If either mismatches, fail loudly — do NOT silently re-download.
ARTIFACTS = {
    "kokoro-v1.0.onnx": {
        "url": f"{OPTION_A_BASE}/kokoro-v1.0.onnx",
        "sha256": "7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5",
    },
    "voices-v1.0.bin": {
        "url": f"{OPTION_A_BASE}/voices-v1.0.bin",
        "sha256": "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d",
    },
}

# A dense academic passage for the subjective quality check.
TEST_PASSAGE = """
Reading-while-listening is a technique with a contested empirical basis. Hui and
Godfroid (2026), in a preregistered within-subjects study of eighty-six
intermediate-advanced second-language English learners, found that the
reading-while-listening condition produced lower comprehension scores than
reading alone, contrary to the long-standing assumption that orthographic input
scaffolds auditory comprehension. The authors propose that, for advanced
readers of alphabetic scripts, the segmentation support that reading-while-
listening is thought to provide is already automatic; the concurrent auditory
stream becomes a minor cognitive load rather than a support. Their result does
not contradict the earlier Chang corpus of findings on lower-intermediate
learners, but it does suggest that the mechanism of benefit is population-
specific. For a first-language reader of dense academic text, the attentional
benefits of being paced by a voice are likely more relevant than the
orthographic scaffolding long claimed in the literature.
""".strip()


# --- Helpers ------------------------------------------------------------


@dataclass
class SpikeResults:
    python_version: str
    platform: str
    onnxruntime_version: str | None
    onnxruntime_distribution: str | None
    available_providers: list[str]
    session_providers: list[str]
    cuda_provider_ok: bool
    kokoro_from_session_ok: bool
    artifact_sha256: dict[str, str]
    synth_latency_ms: float | None
    synth_sample_rate: int | None
    synth_num_samples: int | None
    notes: list[str]


def pip_show(package: str) -> str | None:
    """Return the `pip show` output for a package, or None if not installed."""
    try:
        out = subprocess.run(
            [sys.executable, "-m", "pip", "show", package],
            capture_output=True,
            text=True,
            check=False,
        )
        if out.returncode != 0:
            return None
        return out.stdout
    except Exception:
        return None


def installed_onnxruntime_distribution() -> str | None:
    """
    ONNX Runtime is distributed as multiple distinct PyPI packages:
    `onnxruntime`, `onnxruntime-gpu`, `onnxruntime-openvino`, etc. Only one
    should be present in a given venv. Detect which one by checking pip show.
    """
    for name in ("onnxruntime-gpu", "onnxruntime", "onnxruntime-openvino", "onnxruntime-directml"):
        if pip_show(name) is not None:
            return name
    return None


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download_artifact(name: str, url: str, dest: Path) -> Path:
    """
    Download an artifact to the cache dir if it isn't already present. Uses
    urllib so we don't take a dependency on `requests` for a spike script.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        print(f"[cache] {name} already present at {dest}")
        return dest
    print(f"[download] {name} <- {url}")
    from urllib.request import urlopen
    with urlopen(url) as resp, dest.open("wb") as f:
        while True:
            block = resp.read(1 << 20)
            if not block:
                break
            f.write(block)
    print(f"[download] {name} saved to {dest} ({dest.stat().st_size:,} bytes)")
    return dest


def make_session(model_path: Path, force_cpu: bool) -> tuple[object, list[str], list[str]]:
    """
    Construct an onnxruntime InferenceSession explicitly. Returns
    (session, available_providers, session.get_providers()).

    Note: on Linux with NVIDIA CUDA/cuDNN wheels installed via pip (rather than
    system CUDA), onnxruntime >= 1.24 requires `preload_dlls(cuda=True,
    cudnn=True)` to be called BEFORE constructing the session so that CUDA
    providers can find libcublasLt.so.12, libcudnn.so.9, etc. If we don't do
    this, session construction silently falls back to CPU-only — with no
    exception, just a stderr warning about libcublasLt.so.12 — and
    session.get_providers() returns ['CPUExecutionProvider']. This was
    empirically verified on the target RTX 5080 box during Spike 0.
    """
    import onnxruntime as ort  # type: ignore

    available = list(ort.get_available_providers())

    # Always call preload_dlls on CUDA paths, before session construction.
    # Newer onnxruntime-gpu exposes this; older versions don't (fall through).
    preload = getattr(ort, "preload_dlls", None)
    if preload is not None and not force_cpu:
        try:
            preload(cuda=True, cudnn=True, msvc=False)
            print("[session] onnxruntime.preload_dlls(cuda=True, cudnn=True) OK")
        except Exception as e:
            print(f"[session] preload_dlls raised (continuing anyway): {e}")

    if force_cpu:
        providers: list = ["CPUExecutionProvider"]
    else:
        providers = [("CUDAExecutionProvider", {}), "CPUExecutionProvider"]

    try:
        session = ort.InferenceSession(str(model_path), providers=providers)
    except Exception as e:
        print(f"[session] failed to construct with providers={providers}: {e}")
        raise

    return session, available, list(session.get_providers())


def build_kokoro(session, voices_path: Path):
    """
    Build a Kokoro object from an externally-constructed InferenceSession.
    The exact constructor may vary between kokoro-onnx versions; this tries
    Kokoro.from_session first, then a fallback via direct attribute injection
    if that's not present.
    """
    from kokoro_onnx import Kokoro  # type: ignore

    from_session = getattr(Kokoro, "from_session", None)
    if from_session is not None:
        try:
            return Kokoro.from_session(session, voices_path=str(voices_path))
        except TypeError:
            # Older or newer signature — try the other common shape
            return Kokoro.from_session(session=session, voices_path=str(voices_path))

    raise RuntimeError(
        "kokoro-onnx on this machine does not expose Kokoro.from_session(...). "
        "Pin a version that has it, or patch via a thin wrapper before running Spike 0."
    )


def synthesize_and_play(kokoro, passage: str) -> tuple[int, int, float]:
    """
    Synthesize the passage with Kokoro.create() (not create_stream, per the
    design) and play it through sounddevice. Returns (sample_rate, num_samples,
    latency_seconds).
    """
    import sounddevice as sd  # type: ignore

    print("[synth] starting Kokoro.create() ...")
    t0 = time.perf_counter()
    samples, sample_rate = kokoro.create(passage, voice="af_heart", lang="en-us")
    latency = time.perf_counter() - t0
    n = int(samples.shape[0]) if hasattr(samples, "shape") else len(samples)
    print(f"[synth] done: {n:,} samples @ {sample_rate} Hz in {latency:.2f}s")

    print("[play] playing audio (blocking) ...")
    sd.play(samples, samplerate=sample_rate)
    sd.wait()
    print("[play] done")
    return sample_rate, n, latency


# --- Main ---------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cpu", action="store_true", help="force CPUExecutionProvider")
    parser.add_argument("--no-play", action="store_true", help="skip audio playback")
    args = parser.parse_args()

    results = SpikeResults(
        python_version=sys.version.split()[0],
        platform=platform.platform(),
        onnxruntime_version=None,
        onnxruntime_distribution=installed_onnxruntime_distribution(),
        available_providers=[],
        session_providers=[],
        cuda_provider_ok=False,
        kokoro_from_session_ok=False,
        artifact_sha256={},
        synth_latency_ms=None,
        synth_sample_rate=None,
        synth_num_samples=None,
        notes=[],
    )

    print(f"[env] python={results.python_version} platform={results.platform}")
    print(f"[env] onnxruntime distribution: {results.onnxruntime_distribution}")

    try:
        import onnxruntime as ort  # type: ignore
        results.onnxruntime_version = ort.__version__
        results.available_providers = list(ort.get_available_providers())
        print(f"[env] onnxruntime.__version__ = {results.onnxruntime_version}")
        print(f"[env] ort.get_available_providers() = {results.available_providers}")
    except ImportError as e:
        print(f"[env] onnxruntime not importable: {e}")
        results.notes.append(f"ImportError: {e}")
        write_results(results)
        return 2

    # Download (or cache-hit) the artifacts.
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for name, meta in ARTIFACTS.items():
        dest = CACHE_DIR / name
        try:
            download_artifact(name, meta["url"], dest)
        except Exception as e:
            print(f"[download] FAILED for {name}: {e}")
            results.notes.append(f"download {name} failed: {e}")
            write_results(results)
            return 3
        digest = sha256_of(dest)
        results.artifact_sha256[name] = digest
        expected = meta["sha256"]
        if expected is None:
            print(f"[sha256] {name} = {digest}  (unpinned; paste this into ARTIFACTS after review)")
        elif expected == digest:
            print(f"[sha256] {name} OK")
        else:
            print(f"[sha256] {name} MISMATCH: got {digest}, expected {expected}")
            results.notes.append(f"sha256 mismatch for {name}")
            write_results(results)
            return 4
        paths[name] = dest

    # Build an explicit InferenceSession.
    try:
        session, avail, sess_providers = make_session(paths["kokoro-v1.0.onnx"], force_cpu=args.cpu)
        results.available_providers = avail
        results.session_providers = sess_providers
        results.cuda_provider_ok = "CUDAExecutionProvider" in sess_providers and not args.cpu
        print(f"[session] session.get_providers() = {sess_providers}")
    except Exception as e:
        print(f"[session] FAILED: {e}")
        results.notes.append(f"session construction failed: {e}")
        write_results(results)
        return 5

    # Pass into Kokoro via from_session.
    try:
        kokoro = build_kokoro(session, paths["voices-v1.0.bin"])
        results.kokoro_from_session_ok = True
    except Exception as e:
        print(f"[kokoro] from_session FAILED: {e}")
        results.notes.append(f"Kokoro.from_session failed: {e}")
        write_results(results)
        return 6

    # Synthesize + play.
    try:
        if args.no_play:
            # Still call create() so we time it, just skip sd.play
            import time as _time
            t0 = _time.perf_counter()
            samples, sr = kokoro.create(TEST_PASSAGE, voice="af_heart", lang="en-us")
            latency = _time.perf_counter() - t0
            n = int(samples.shape[0]) if hasattr(samples, "shape") else len(samples)
            results.synth_latency_ms = latency * 1000.0
            results.synth_sample_rate = sr
            results.synth_num_samples = n
            print(f"[synth] {n:,} samples @ {sr} Hz in {latency:.2f}s (playback skipped)")
        else:
            sr, n, latency = synthesize_and_play(kokoro, TEST_PASSAGE)
            results.synth_latency_ms = latency * 1000.0
            results.synth_sample_rate = sr
            results.synth_num_samples = n
    except Exception as e:
        print(f"[synth] FAILED: {e}")
        results.notes.append(f"synthesis/playback failed: {e}")
        write_results(results)
        return 7

    write_results(results)
    print("[spike0] done.")
    return 0


def write_results(results: SpikeResults) -> None:
    """Write results to spike0_results.json next to this script."""
    out = Path(__file__).parent / "spike0_results.json"
    out.write_text(json.dumps(asdict(results), indent=2))
    print(f"[results] wrote {out}")


if __name__ == "__main__":
    sys.exit(main())
