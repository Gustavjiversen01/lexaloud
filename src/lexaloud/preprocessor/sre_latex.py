"""Speech Rule Engine (SRE) bridge for LaTeX-to-speech.

Optional, opt-in extra. Requires the user to install Node.js ≥18 and
``speech-rule-engine@4.1.3`` via ``scripts/install.sh --with-math-speech``.
If SRE is not resolvable, this module is a no-op and the daemon works
normally with rule-based Unicode math handling only.

Verified CLI flags (from the unpacked tarball of
speech-rule-engine@4.1.3):

- ``-t / --latex`` — accept LaTeX input (default is MathML)
- ``-p / --speech`` — generate speech output
- ``-d / --domain [name]`` — ``clearspeak`` or ``mathspeak``
- ``-s / --style [name]`` — e.g. ``default``, ``verbose``, ``short``

Canonical command this module issues:
``sre --latex --speech -d <domain> [-s <style>]`` — never ``-t`` for
style (``-t`` is the short form of ``--latex``).

Resolution order for the ``sre`` executable (cached, ``cache_clear()``
exposed for tests):

1. ``Path(sys.executable).parent / "sre"`` — the symlink that
   ``scripts/install.sh --with-math-speech`` drops into the venv's
   ``bin/`` directory so the daemon resolves it under systemd without
   depending on PATH.
2. ``shutil.which("sre")`` — PATH fallback for interactive shells.

Each candidate must satisfy ``is_file()`` AND ``os.access(X_OK)``.

Runs at position 3 in the preprocessor pipeline — BEFORE
``normalize_math_symbols``, so SRE handles Greek letters and operators
inside ``$...$`` spans and the Unicode stage handles anything left
outside.

Tests that mock availability MUST call
``sre_executable_path.cache_clear()`` between cases.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path


def _scrub(data: bytes) -> str:
    """Return a privacy-safe fingerprint of opaque subprocess output.

    SRE's stderr can echo user-supplied LaTeX — logging it raw would
    violate the same privacy posture the daemon enforces elsewhere
    (see ``_sentence_token`` in ``providers/kokoro.py``). We log only
    length plus SHA-1[:8] so operators can correlate across lines
    without leaking content.
    """
    if not data:
        return "empty"
    digest = hashlib.sha1(data).hexdigest()[:8]
    return f"{len(data)}B sha1={digest}"


log = logging.getLogger(__name__)

_LATEX_SPAN_RE = re.compile(
    # Display math via $$...$$ — MUST match before single $...$
    r"(?P<display>\$\$(?P<display_body>.+?)\$\$)"
    # MathJax-style display math \[...\]
    r"|(?P<bracket_display>\\\[(?P<bracket_display_body>.+?)\\\])"
    # MathJax-style inline math \(...\)
    r"|(?P<bracket_inline>\\\((?P<bracket_inline_body>.+?)\\\))"
    # Inline math via $...$, with escaped-$ and adjacent-$ guards
    r"|(?P<inline>(?<!\\)(?<!\$)\$(?!\$)(?P<inline_body>.+?)(?<!\\)(?<!\$)\$(?!\$))"
    # LaTeX math environments; the env name uses a named backreference
    # so open/close must agree. Covers equation, align, gather,
    # multline, eqnarray, and their starred variants.
    r"|(?P<env>"
    r"\\begin\{(?P<env_name>"
    r"equation\*?|align\*?|gather\*?|multline\*?|eqnarray\*?"
    r")\}"
    r"(?P<env_body>.+?)"
    r"\\end\{(?P=env_name)\})",
    re.DOTALL,
)

# Cheap first-pass gate. If there's no hint of LaTeX in the text, skip
# the full span scan. Extends the LLM normalizer's hint regex with the
# MathJax-style ``\(...\)`` / ``\[...\]`` delimiters and the additional
# math environments the span regex handles.
_LATEX_HINT_RE = re.compile(
    r"\\(?:frac|sum|int|sqrt|alpha|beta|gamma|begin|end|text|mathbf|mathrm)"
    r"|\$\$.+?\$\$"
    r"|\$[^$]+\$"
    r"|\\\(.+?\\\)"
    r"|\\\[.+?\\\]",
    re.DOTALL,
)

_missing_logged = False


def _candidate_ok(candidate: Path) -> bool:
    return candidate.is_file() and os.access(candidate, os.X_OK)


@lru_cache(maxsize=1)
def sre_executable_path() -> str | None:
    """Return the absolute path to the ``sre`` executable, or ``None``.

    Cached. Tests that mock availability must call
    ``sre_executable_path.cache_clear()`` between cases.
    """
    venv_bin = Path(sys.executable).parent / "sre"
    if _candidate_ok(venv_bin):
        return str(venv_bin)
    path_hit = shutil.which("sre")
    if path_hit is not None:
        candidate = Path(path_hit)
        if _candidate_ok(candidate):
            return str(candidate)
    return None


def is_sre_available() -> bool:
    return sre_executable_path() is not None


def _log_missing_once() -> None:
    global _missing_logged
    if not _missing_logged:
        log.info(
            "SRE (speech-rule-engine) not found on PATH or in the venv bin. "
            "LaTeX spans will be passed through unchanged. Install with "
            "`scripts/install.sh --with-math-speech` (requires Node.js >=18)."
        )
        _missing_logged = True


def _collect_spans(text: str) -> list[tuple[int, int, str]]:
    """Return ``(start, end, inner_latex)`` for each matched LaTeX span."""
    spans: list[tuple[int, int, str]] = []
    for m in _LATEX_SPAN_RE.finditer(text):
        body = (
            m.group("display_body")
            or m.group("bracket_display_body")
            or m.group("bracket_inline_body")
            or m.group("inline_body")
            or m.group("env_body")
        )
        if body is None:
            continue
        spans.append((m.start(), m.end(), body))
    return spans


def latex_to_speech(
    text: str,
    *,
    timeout_s: float = 10.0,
    domain: str = "clearspeak",
    style: str | None = None,
) -> str:
    """Replace every LaTeX span in ``text`` with its spoken English form.

    Returns ``text`` unchanged on any failure:

    - SRE not installed
    - No LaTeX markers detected
    - Non-zero exit code from ``sre`` on any span
    - ``subprocess.TimeoutExpired`` on any span
    - Unicode decode failure on stdout

    The behavior is deterministic fallback: if even one span fails, the
    whole text is returned as-is so the user never gets partial mangled
    output.
    """
    if not _LATEX_HINT_RE.search(text):
        return text

    sre_path = sre_executable_path()
    if sre_path is None:
        _log_missing_once()
        return text

    spans = _collect_spans(text)
    if not spans:
        return text

    cmd = [sre_path, "--latex", "--speech", "-d", domain]
    if style:
        cmd += ["-s", style]

    replacements: list[str] = []
    try:
        for _start, _end, inner in spans:
            proc = subprocess.run(
                cmd,
                input=inner.encode("utf-8"),
                capture_output=True,
                timeout=timeout_s,
                check=False,
            )
            if proc.returncode != 0:
                log.warning(
                    "SRE returned non-zero (rc=%d) for a LaTeX span; "
                    "falling back to original text (stderr=%s)",
                    proc.returncode,
                    _scrub(proc.stderr or b""),
                )
                return text
            spoken = proc.stdout.decode("utf-8").strip()
            if not spoken:
                log.warning("SRE returned empty speech for a LaTeX span; falling back")
                return text
            replacements.append(spoken)
    except subprocess.TimeoutExpired:
        log.warning("SRE timed out; falling back to original text")
        return text
    except UnicodeDecodeError:
        log.warning("SRE stdout was not valid UTF-8; falling back to original text")
        return text
    except OSError as e:
        log.warning("SRE subprocess error: %s; falling back to original text", e)
        return text

    out = text
    for (start, end, _), spoken in reversed(list(zip(spans, replacements, strict=True))):
        out = out[:start] + spoken + out[end:]
    return out


__all__ = [
    "is_sre_available",
    "latex_to_speech",
    "sre_executable_path",
]
