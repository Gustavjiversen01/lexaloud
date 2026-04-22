"""LLM-based text normalizer for edge cases the rule-based pipeline misses.

Uses llama-cpp-python (optional dependency) to run a small quantized LLM
locally. The model is loaded lazily on first use and kept resident in VRAM.

If llama-cpp-python is not installed or the model file is missing,
``normalize()`` returns the input unchanged and logs a warning once.

Stress-test-driven design:
- ``_infer_lock`` serializes LLM access (Llama is not thread-safe) [H5]
- Dedicated ThreadPoolExecutor to avoid contention with audio pipeline [M1]
- ``shutdown()`` explicitly frees CUDA memory [H6]
- ``_needs_llm()`` allowlist of common acronyms to reduce false positives [H7]
- ``_postprocess()`` strips preambles, validates output length (0.1x-3x) [M7]
- Glossary values validated as strings at init time [M15]
"""

from __future__ import annotations

import asyncio
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..config import NormalizerConfig

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt for the LLM
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a text preprocessor for a text-to-speech system. Your ONLY job is to \
rewrite the input text so it reads naturally when spoken aloud.

Rules:
1. Expand abbreviations to full words
2. Expand acronyms on first use (e.g. RLHF -> Reinforcement Learning from Human Feedback)
3. Normalize math expressions to spoken form (e.g. x^2 -> x squared)
4. Convert bullet points and numbered lists into flowing prose
5. Fix OCR artifacts: broken words, stray characters, garbled Unicode
6. Remove table formatting; describe the content in natural sentences
7. Keep the meaning EXACTLY the same. Do not add commentary, opinions, or explanations
8. Output ONLY the normalized text, nothing else

If the input is already natural spoken prose, return it unchanged."""

# ---------------------------------------------------------------------------
# Common acronyms that should NOT trigger LLM normalization
# ---------------------------------------------------------------------------

_COMMON_ACRONYMS = frozenset(
    {
        "AI",
        "API",
        "CEO",
        "CFO",
        "CIA",
        "CTO",
        "CV",
        "DNS",
        "EU",
        "FAQ",
        "FBI",
        "GDP",
        "GPS",
        "GPU",
        "HR",
        "HTML",
        "HTTP",
        "ID",
        "IEEE",
        "IP",
        "IT",
        "JSON",
        "MBA",
        "NASA",
        "NATO",
        "NFL",
        "NGO",
        "NHS",
        "NSA",
        "OECD",
        "OK",
        "OS",
        "PDF",
        "PhD",
        "PR",
        "RAM",
        "SQL",
        "SSH",
        "TV",
        "UK",
        "UN",
        "URL",
        "US",
        "USA",
        "USB",
        "VPN",
        "WHO",
        "XML",
    }
)

# ---------------------------------------------------------------------------
# Heuristic gate: does this text need LLM normalization?
# ---------------------------------------------------------------------------

# Sequences of 3+ uppercase letters that might be domain-specific acronyms
_UPPERCASE_ACRONYM = re.compile(r"\b[A-Z]{3,}\b")

# LaTeX-like patterns (unambiguous markers)
_LATEX_MARKERS = re.compile(
    r"\\(?:frac|sum|int|sqrt|alpha|beta|gamma|begin|end|text|mathbf|mathrm)"
    r"|\$\$.+?\$\$"
    r"|\$[^$]+\$"
)

# Table formatting (pipes between content)
_TABLE_PIPE = re.compile(r"\|.*\|.*\|")

# OCR artifact heuristic: isolated single non-ASCII chars or repeated junk
_OCR_JUNK = re.compile(r"(?:\s[^\x00-\x7F]\s){2,}")


def _needs_llm(text: str) -> bool:
    """Return True if the text likely contains tokens the rules missed.

    Uses a threshold: at least 2 distinct unknown-acronym triggers, or
    any LaTeX / table / OCR marker.
    """
    # LaTeX, tables, and OCR artifacts always trigger
    if _LATEX_MARKERS.search(text):
        return True
    if _TABLE_PIPE.search(text):
        return True
    if _OCR_JUNK.search(text):
        return True

    # Count unknown uppercase acronyms (not in the common allowlist)
    unknown = set()
    for m in _UPPERCASE_ACRONYM.finditer(text):
        word = m.group()
        if word not in _COMMON_ACRONYMS:
            unknown.add(word)
    return len(unknown) >= 2


# ---------------------------------------------------------------------------
# LlmNormalizer class
# ---------------------------------------------------------------------------


class LlmNormalizer:
    """LLM-based text normalizer using llama-cpp-python.

    Loaded lazily at first use. If llama-cpp-python is not installed
    or the model file is missing, ``normalize()`` returns the input
    unchanged and logs a warning once.
    """

    def __init__(self, config: NormalizerConfig) -> None:
        self._config = config
        self._llm: Any = None
        self._init_lock = asyncio.Lock()
        self._infer_lock = asyncio.Lock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="llm")
        self._available: bool | None = None  # None = not yet checked
        self._warned = False

        # Compile glossary patterns, validate values are strings [M15]
        self._glossary: list[tuple[re.Pattern[str], str]] = []
        for abbr, expansion in config.glossary.items():
            if not isinstance(expansion, str):  # defensive: TOML may have non-string values
                log.warning(  # type: ignore[unreachable]
                    "Glossary value for %r is %s, not str; skipping",
                    abbr,
                    type(expansion).__name__,
                )
                continue
            self._glossary.append(
                (
                    re.compile(r"\b" + re.escape(str(abbr)) + r"\b"),
                    expansion,
                )
            )

    def _apply_glossary(self, text: str) -> str:
        """Apply user-defined acronym expansions deterministically."""
        for pat, repl in self._glossary:
            text = pat.sub(repl, text)
        return text

    async def _ensure_initialized(self) -> bool:
        """Lazy-load the Llama model. Returns True if available."""
        if self._available is not None:
            return self._available

        async with self._init_lock:
            if self._available is not None:  # double-checked locking
                return self._available  # type: ignore[unreachable]

            try:
                from llama_cpp import Llama
            except ImportError:
                if not self._warned:
                    log.warning(
                        "LLM normalizer requires llama-cpp-python. "
                        "Install with: pip install lexaloud[llm]"
                    )
                    self._warned = True
                self._available = False
                return False

            # Resolve model path
            model_path = self._config.model_path
            if not model_path:
                import os

                from ..models import default_cache_dir

                # Path-containment check (M3): reject model_file values
                # that resolve outside the cache dir — prevents a
                # hostile config.toml from pointing the daemon at an
                # arbitrary user-readable file.
                cache = default_cache_dir().resolve()
                try:
                    candidate = (cache / self._config.model_file).resolve()
                except (OSError, ValueError) as e:
                    log.error("invalid model_file path: %s", e)
                    self._available = False
                    return False
                if not str(candidate).startswith(str(cache) + os.sep):
                    log.error(
                        "model_file %r escapes cache dir; refusing to load",
                        self._config.model_file,
                    )
                    self._available = False
                    return False
                model_path = str(candidate)

            from pathlib import Path

            if not Path(model_path).is_file():
                log.error(
                    "LLM model file not found: %s. "
                    "Run 'lexaloud download-models --llm' to fetch it.",
                    model_path,
                )
                self._available = False
                return False

            loop = asyncio.get_running_loop()

            def _load() -> Any:
                return Llama(
                    model_path=model_path,
                    n_gpu_layers=self._config.n_gpu_layers,
                    n_ctx=self._config.n_ctx,
                    verbose=False,
                )

            try:
                self._llm = await loop.run_in_executor(self._executor, _load)
            except Exception as e:
                log.error("Failed to load LLM model: %s", e)
                self._available = False
                return False

            log.info(
                "LLM normalizer loaded: %s (n_gpu_layers=%d)",
                self._config.model_file,
                self._config.n_gpu_layers,
            )
            self._available = True
            return True

    async def warmup(self) -> None:
        """Pre-load the model during daemon startup."""
        ok = await self._ensure_initialized()
        if not ok:
            return
        # Optional: run a short test inference to warm CUDA kernels
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(
                self._executor,
                lambda: self._llm.create_chat_completion(
                    messages=[
                        {"role": "system", "content": "Reply with OK."},
                        {"role": "user", "content": "Test."},
                    ],
                    max_tokens=5,
                    temperature=0.0,
                ),
            )
            log.info("LLM normalizer warmup complete")
        except Exception as e:
            log.warning("LLM warmup inference failed (non-fatal): %s", e)

    async def normalize(self, text: str) -> str:
        """Normalize text using glossary + optional LLM fallback.

        Returns the input unchanged on any failure (graceful degradation).
        """
        # Step 1: deterministic glossary
        text = self._apply_glossary(text)

        # Step 2: heuristic gate — skip LLM for plain prose
        if not _needs_llm(text):
            return text

        # Step 3: ensure model is loaded
        if not await self._ensure_initialized():
            return text

        # Step 4: run LLM inference under the infer lock [H5]
        async with self._infer_lock:
            loop = asyncio.get_running_loop()

            def _infer() -> str:
                # Use actual tokenizer for token count [M7]
                input_tokens = self._llm.tokenize(text.encode("utf-8"))
                max_tokens = int(len(input_tokens) * self._config.max_output_ratio)
                max_tokens = max(max_tokens, 64)  # minimum floor

                result = self._llm.create_chat_completion(
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": text},
                    ],
                    max_tokens=max_tokens,
                    temperature=self._config.temperature,
                )
                return result["choices"][0]["message"]["content"]

            try:
                raw_output = await loop.run_in_executor(self._executor, _infer)
            except Exception as e:
                log.warning("LLM inference failed, returning original text: %s", e)
                return text

        # Step 5: post-process and validate
        return self._postprocess(text, raw_output)

    def _postprocess(self, original: str, llm_output: str) -> str:
        """Validate and clean the LLM output."""
        output = llm_output.strip()

        # Strip common LLM preambles
        for prefix in (
            "Here is the",
            "Here's the",
            "Sure,",
            "Sure!",
            "The normalized",
            "The rewritten",
        ):
            if output.startswith(prefix):
                idx = output.find("\n")
                if idx != -1:
                    output = output[idx + 1 :].strip()

        # Length sanity check [M7]: 0.1x to 3x
        if not output:
            log.warning("LLM returned empty output; using original text")
            return original

        ratio = len(output) / max(len(original), 1)
        if ratio < 0.1 or ratio > 3.0:
            log.warning(
                "LLM output length ratio %.2f outside [0.1, 3.0]; using original text",
                ratio,
            )
            return original

        return output

    def shutdown(self) -> None:
        """Free CUDA memory and the executor. Called on daemon shutdown [H6]."""
        if self._llm is not None:
            del self._llm
            self._llm = None
            self._available = None
            import gc

            gc.collect()
            log.info("LLM normalizer shut down")
        self._executor.shutdown(wait=False, cancel_futures=True)
