"""Kokoro-82M provider via kokoro-onnx.

Design, per the plan and Spike 0 findings:

1. Before constructing any InferenceSession, call
   `onnxruntime.preload_dlls(cuda=True, cudnn=True, msvc=False)` so the CUDA
   EP can find libcublasLt / libcudnn via the NVIDIA pip wheels. If the
   call raises, log and continue: the explicit session construction may
   still succeed (system-wide CUDA), and otherwise we cleanly fall back
   to CPU.

2. After session construction, VERIFY `session.get_providers()` actually
   contains CUDAExecutionProvider when we asked for it. Spike 0 showed
   that without `preload_dlls`, CUDA EP construction *silently* falls
   back to CPU — the exception path does not fire. We detect the silent
   degradation explicitly and log loudly.

3. Synthesis is per-sentence via `Kokoro.create()` inside an asyncio
   executor. We do NOT use `create_stream()`, because its internal
   background task and unbounded queue would defeat our bounded ready-queue
   backpressure and our job-id cancellation.

4. Cancellation is cooperative via a `is_current_job(job_id)` callback
   passed in by the player. If the job id is superseded before we submit
   to the executor OR after the executor returns, we return `None`.

5. Warmup is serialized with synthesis via an asyncio lock. While warmup
   is running, real /speak calls wait. If warmup fails, `_warmed` stays
   False and the next `synthesize()` call opportunistically retries it,
   so the cold-start cost is not silently deferred onto a user request.

6. ONNX Runtime's C++ stderr warnings at session-load time ("39 Memcpy
   nodes added", "ScatterND with reduction=='none'") are suppressed by
   setting `SessionOptions.log_severity_level=3` (ERROR only). Both are
   informational per Spike 0 and they leak to journald otherwise.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from .._privacy import sentence_token
from .base import AudioChunk

log = logging.getLogger(__name__)


class KokoroProvider:
    name = "kokoro"

    def __init__(
        self,
        model_path: Path,
        voices_path: Path,
        *,
        voice: str = "af_heart",
        lang: str = "en-us",
        speed: float = 1.0,
        prefer_cuda: bool = True,
    ) -> None:
        self.model_path = Path(model_path)
        self.voices_path = Path(voices_path)
        self.voice = voice
        self.lang = lang
        self.speed = speed
        self.prefer_cuda = prefer_cuda

        self._kokoro: Any = None
        self._session: Any = None
        self._session_providers: list[str] = []
        self._init_lock = asyncio.Lock()
        self._synth_lock = asyncio.Lock()
        self._warmed = False

    # ---------- init ----------

    def _preload_cuda_dlls(self) -> None:
        """Best-effort preload of CUDA/cuDNN via onnxruntime's helper.

        Spike 0 demonstrated that without this call, `InferenceSession`
        construction on CUDA EP silently falls back to CPU on the target
        Ubuntu 24.04 machine. If the helper is missing or raises, we log
        and continue — the silent-degradation detector in `_build_session`
        will still catch the CPU fallback and log loudly.
        """
        try:
            import onnxruntime as ort
        except Exception as e:  # noqa: BLE001
            log.error("onnxruntime import failed: %s", e)
            raise
        preload = getattr(ort, "preload_dlls", None)
        if preload is None:
            log.info("ort.preload_dlls is unavailable in this onnxruntime build; skipping")
            return
        try:
            preload(cuda=True, cudnn=True, msvc=False)
            log.info("ort.preload_dlls(cuda=True, cudnn=True) OK")
        except Exception as e:  # noqa: BLE001
            log.warning("ort.preload_dlls raised (continuing): %s", e)

    def _build_session(self) -> tuple[Any, list[str]]:
        import onnxruntime as ort

        # Suppress C++ stderr warnings at session load. ORT emits two
        # warnings on Kokoro load ("39 Memcpy nodes added",
        # "ScatterND reduction=='none'") that Spike 0 verified are
        # informational. Setting severity=3 keeps ERROR-level logs visible
        # while silencing WARNING/INFO/VERBOSE.
        sess_options = ort.SessionOptions()
        sess_options.log_severity_level = 3

        if self.prefer_cuda:
            cuda_providers: list = [
                ("CUDAExecutionProvider", {}),
                "CPUExecutionProvider",
            ]
            try:
                session = ort.InferenceSession(
                    str(self.model_path),
                    sess_options=sess_options,
                    providers=cuda_providers,
                )
                providers = list(session.get_providers())
                if "CUDAExecutionProvider" not in providers:
                    # Spike 0's exact failure mode: session built but CUDA
                    # EP silently degraded to CPU. Log loudly so operators
                    # see it in journalctl.
                    log.error(
                        "Requested CUDAExecutionProvider but session reports %s. "
                        "Likely cause: preload_dlls did not load CUDA/cuDNN "
                        "runtime libraries (check NVIDIA pip wheels are installed). "
                        "Continuing on CPU; expect ~6x slower synthesis.",
                        providers,
                    )
                else:
                    log.info("Kokoro session providers: %s", providers)
                return session, providers
            except Exception as e:  # noqa: BLE001
                log.warning("CUDA session construction failed, falling back to CPU: %s", e)

        # CPU fallback
        session = ort.InferenceSession(
            str(self.model_path),
            sess_options=sess_options,
            providers=["CPUExecutionProvider"],
        )
        providers = list(session.get_providers())
        log.info("Kokoro session providers (CPU fallback): %s", providers)
        return session, providers

    async def _ensure_initialized(self) -> None:
        if self._kokoro is not None:
            return
        async with self._init_lock:
            if self._kokoro is not None:  # double-checked locking
                return  # type: ignore[unreachable]
            loop = asyncio.get_running_loop()

            def _do_init() -> tuple[Any, Any, list[str]]:
                # Only preload CUDA/cuDNN when we're going to try CUDA EP;
                # no reason to emit CUDA log noise in CPU-only runs.
                if self.prefer_cuda:
                    self._preload_cuda_dlls()
                session, providers = self._build_session()
                from kokoro_onnx import Kokoro  # deferred import

                kokoro = Kokoro.from_session(session, voices_path=str(self.voices_path))
                return kokoro, session, providers

            (
                self._kokoro,
                self._session,
                self._session_providers,
            ) = await loop.run_in_executor(None, _do_init)

    # ---------- public API ----------

    @property
    def session_providers(self) -> list[str]:
        return list(self._session_providers)

    @property
    def is_warming(self) -> bool:
        return self._kokoro is None or not self._warmed

    async def warmup(self) -> None:
        """Run a short synthesis so CUDA kernel JIT happens before first request.

        Acquires both the init lock (via _ensure_initialized) and the
        synth lock, so user /speak requests that arrive during warmup
        wait until warmup is complete. On failure, leaves `_warmed=False`
        so the next `synthesize` call will retry.
        """
        if self._warmed:
            return
        await self._ensure_initialized()
        async with self._synth_lock:
            if self._warmed:  # double-checked locking
                return  # type: ignore[unreachable]
            loop = asyncio.get_running_loop()

            def _do_warmup() -> None:
                # Short string: exercise the graph/CUDA kernels once.
                self._kokoro.create(
                    "Ready.",
                    voice=self.voice,
                    speed=self.speed,
                    lang=self.lang,
                )

            try:
                await loop.run_in_executor(None, _do_warmup)
                self._warmed = True
                log.info(
                    "Kokoro warmup complete (providers=%s)",
                    self._session_providers,
                )
            except Exception as e:  # noqa: BLE001
                log.error("Kokoro warmup failed: %s", e)
                # Leave `_warmed=False`; `synthesize` will retry opportunistically.

    async def synthesize(
        self,
        sentence: str,
        job_id: int,
        is_current_job: Callable[[int], bool],
    ) -> AudioChunk | None:
        """Synthesize one sentence. Returns None if the job was superseded.

        Note: `loop.run_in_executor` is not interruptible. If the producer
        task is cancelled while this call is inside the executor, the
        executor thread continues until `Kokoro.create()` returns; the
        result is discarded. Expected cancellation latency is
        approximately "time to finish synthesizing the current sentence".
        """
        if not is_current_job(job_id):
            return None
        await self._ensure_initialized()
        if not is_current_job(job_id):
            return None

        # Opportunistic warmup retry: if background warmup failed, retry
        # on the first real request rather than forcing the user to eat
        # the ~30s cold-start with no log line.
        if not self._warmed:
            try:
                await self.warmup()
            except Exception:  # noqa: BLE001
                pass  # warmup() already logs; continue anyway

        loop = asyncio.get_running_loop()

        def _do_synthesize() -> tuple[np.ndarray, int]:
            samples, sr = self._kokoro.create(
                sentence,
                voice=self.voice,
                speed=self.speed,
                lang=self.lang,
            )
            if not isinstance(samples, np.ndarray):
                samples = np.asarray(samples, dtype=np.float32)
            else:
                samples = samples.astype(np.float32, copy=False)
            return samples, int(sr)

        async with self._synth_lock:
            if not is_current_job(job_id):
                return None
            try:
                samples, sr = await loop.run_in_executor(None, _do_synthesize)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                log.error("Kokoro synthesis failed for sentence: %s", e)
                return None

        if not is_current_job(job_id):
            log.debug(
                "Kokoro synthesis result discarded: job %d is no longer current",
                job_id,
            )
            return None

        # Filter out degenerate very-short outputs. Kokoro can produce
        # ~5-10 ms of residual noise for sentences that phonemize to
        # almost nothing (e.g., a stripped citation "[3]" or a stray
        # "Fig.") — audible as a pop and useless as speech. The
        # preprocessor should ideally catch these first, but this is a
        # second line of defense in the provider.
        min_samples = max(1, int(0.05 * sr))
        if samples.shape[0] < min_samples:
            log.debug(
                "Kokoro returned a very short (%d-sample, %.1fms) output for %s; "
                "dropping the chunk to avoid audio artifacts",
                samples.shape[0],
                samples.shape[0] * 1000.0 / sr,
                sentence_token(sentence),
            )
            return None

        return AudioChunk(samples=samples, sample_rate=sr, metadata={"voice": self.voice})
