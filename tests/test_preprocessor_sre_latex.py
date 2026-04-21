"""Mocked tests for the SRE LaTeX bridge (no Node required).

Every test that manipulates availability MUST call
``sre_executable_path.cache_clear()`` in an autouse fixture so the
cached result from a prior test does not leak.
"""

from __future__ import annotations

import subprocess

import pytest

from lexaloud.preprocessor import sre_latex
from lexaloud.preprocessor.sre_latex import (
    is_sre_available,
    latex_to_speech,
    sre_executable_path,
)


@pytest.fixture(autouse=True)
def _clear_sre_cache():
    """Reset the availability cache before AND after each test."""
    sre_executable_path.cache_clear()
    sre_latex._missing_logged = False
    yield
    sre_executable_path.cache_clear()


def test_no_sre_returns_unchanged(monkeypatch):
    """When sre is not on PATH and not in the venv, input is unchanged."""
    monkeypatch.setattr(sre_latex, "shutil", _FakeShutilWhichNone())
    # Patch Path(sys.executable).parent / "sre" to a non-existent file.
    # Easiest: force _candidate_ok to return False.
    monkeypatch.setattr(sre_latex, "_candidate_ok", lambda p: False)

    out = latex_to_speech("The identity $E=mc^2$ is famous.")
    assert out == "The identity $E=mc^2$ is famous."
    assert is_sre_available() is False


def test_no_latex_markers_skips_subprocess(monkeypatch):
    """Plain prose hits the hint-regex fast path — no subprocess spawn."""
    monkeypatch.setattr(sre_latex, "_candidate_ok", lambda p: True)
    monkeypatch.setattr(sre_latex, "sre_executable_path", lambda: "/fake/sre")

    calls: list = []

    def _bomb(*a, **kw):
        calls.append((a, kw))
        raise AssertionError("subprocess.run was called on plain prose")

    monkeypatch.setattr(subprocess, "run", _bomb)
    out = latex_to_speech("Plain prose with no LaTeX at all.")
    assert out == "Plain prose with no LaTeX at all."
    assert calls == []


def test_no_matched_spans_returns_unchanged(monkeypatch):
    """Text with a LaTeX hint but no matchable span returns unchanged."""
    sre_executable_path.cache_clear()
    monkeypatch.setattr(sre_latex, "_candidate_ok", lambda p: True)
    monkeypatch.setattr(sre_latex, "sre_executable_path", lambda: "/fake/sre")
    # Has a `\frac` hint but no matchable $..$ or env span.
    text = "Inline macro \\frac{1}{2} with no delimiters."
    out = latex_to_speech(text)
    assert out == text


def test_subprocess_timeout_graceful(monkeypatch):
    monkeypatch.setattr(sre_latex, "_candidate_ok", lambda p: True)
    monkeypatch.setattr(sre_latex, "sre_executable_path", lambda: "/fake/sre")

    def _timeout(*a, **kw):
        raise subprocess.TimeoutExpired(cmd=a[0], timeout=1.0)

    monkeypatch.setattr(subprocess, "run", _timeout)
    text = "Consider $x^2$."
    assert latex_to_speech(text) == text


def test_subprocess_nonzero_returncode_graceful(monkeypatch):
    monkeypatch.setattr(sre_latex, "_candidate_ok", lambda p: True)
    monkeypatch.setattr(sre_latex, "sre_executable_path", lambda: "/fake/sre")

    def _fail(*a, **kw):
        return subprocess.CompletedProcess(a[0], returncode=1, stdout=b"", stderr=b"bad")

    monkeypatch.setattr(subprocess, "run", _fail)
    text = "Consider $x^2$."
    assert latex_to_speech(text) == text


def test_successful_single_span_substitution(monkeypatch):
    monkeypatch.setattr(sre_latex, "_candidate_ok", lambda p: True)
    monkeypatch.setattr(sre_latex, "sre_executable_path", lambda: "/fake/sre")

    def _ok(*a, **kw):
        return subprocess.CompletedProcess(a[0], returncode=0, stdout=b"x squared", stderr=b"")

    monkeypatch.setattr(subprocess, "run", _ok)
    out = latex_to_speech("Consider $x^2$ for all x.")
    assert "x squared" in out
    assert "$x^2$" not in out
    assert "Consider " in out
    assert " for all x." in out


def test_multiple_spans_substituted_right_to_left(monkeypatch):
    monkeypatch.setattr(sre_latex, "_candidate_ok", lambda p: True)
    monkeypatch.setattr(sre_latex, "sre_executable_path", lambda: "/fake/sre")

    outputs = [b"first spoken", b"second spoken"]

    def _ok(*a, **kw):
        return subprocess.CompletedProcess(a[0], returncode=0, stdout=outputs.pop(0), stderr=b"")

    monkeypatch.setattr(subprocess, "run", _ok)
    out = latex_to_speech("A $x$ then $y$ end.")
    assert "first spoken" in out
    assert "second spoken" in out
    assert out.index("first spoken") < out.index("second spoken")
    assert "$x$" not in out
    assert "$y$" not in out


def test_executable_resolution_prefers_venv_bin(tmp_path, monkeypatch):
    """sys.executable parent is checked BEFORE shutil.which."""
    fake_venv_bin = tmp_path
    fake_exe = fake_venv_bin / "python"
    fake_exe.write_text("")
    fake_exe.chmod(0o755)
    fake_sre = fake_venv_bin / "sre"
    fake_sre.write_text("")
    fake_sre.chmod(0o755)

    sre_executable_path.cache_clear()
    monkeypatch.setattr(sre_latex.sys, "executable", str(fake_exe))

    resolved = sre_executable_path()
    assert resolved == str(fake_sre)


def test_executable_must_be_executable(tmp_path, monkeypatch):
    """A non-executable file named ``sre`` must NOT be treated as available."""
    fake_venv_bin = tmp_path
    fake_exe = fake_venv_bin / "python"
    fake_exe.write_text("")
    fake_exe.chmod(0o755)
    fake_sre = fake_venv_bin / "sre"
    fake_sre.write_text("")
    fake_sre.chmod(0o644)  # not executable

    sre_executable_path.cache_clear()
    monkeypatch.setattr(sre_latex.sys, "executable", str(fake_exe))
    monkeypatch.setattr(sre_latex.shutil, "which", lambda _: None)

    assert sre_executable_path() is None


class _FakeShutilWhichNone:
    def which(self, name):
        return None

    # Expose the rest of shutil for any other attribute access.
    def __getattr__(self, name):
        import shutil

        return getattr(shutil, name)


def test_domain_and_style_passed_to_subprocess(monkeypatch):
    """Verify the canonical command shape: --latex --speech -d <domain> -s <style>."""
    monkeypatch.setattr(sre_latex, "_candidate_ok", lambda p: True)
    monkeypatch.setattr(sre_latex, "sre_executable_path", lambda: "/fake/sre")

    captured: dict = {}

    def _capture(cmd, *a, **kw):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, returncode=0, stdout=b"spoken", stderr=b"")

    monkeypatch.setattr(subprocess, "run", _capture)
    latex_to_speech("$x$ y", domain="mathspeak", style="verbose")

    cmd = captured["cmd"]
    assert cmd[0] == "/fake/sre"
    assert "--latex" in cmd
    assert "--speech" in cmd
    assert "-d" in cmd
    assert cmd[cmd.index("-d") + 1] == "mathspeak"
    assert "-s" in cmd
    assert cmd[cmd.index("-s") + 1] == "verbose"


def test_empty_style_omits_s_flag(monkeypatch):
    monkeypatch.setattr(sre_latex, "_candidate_ok", lambda p: True)
    monkeypatch.setattr(sre_latex, "sre_executable_path", lambda: "/fake/sre")

    captured: dict = {}

    def _capture(cmd, *a, **kw):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, returncode=0, stdout=b"spoken", stderr=b"")

    monkeypatch.setattr(subprocess, "run", _capture)
    latex_to_speech("$x$ y", style=None)

    assert "-s" not in captured["cmd"]


def test_bracket_display_math_matched(monkeypatch):
    """MathJax-style ``\\[...\\]`` display math must be handled."""
    monkeypatch.setattr(sre_latex, "_candidate_ok", lambda p: True)
    monkeypatch.setattr(sre_latex, "sre_executable_path", lambda: "/fake/sre")

    calls: list[bytes] = []

    def _capture(cmd, *a, input=None, **kw):
        calls.append(input)
        return subprocess.CompletedProcess(cmd, returncode=0, stdout=b"spoken", stderr=b"")

    monkeypatch.setattr(subprocess, "run", _capture)
    latex_to_speech(r"Display: \[a + b\] done.")
    assert calls == [b"a + b"]


def test_bracket_inline_math_matched(monkeypatch):
    """MathJax-style ``\\(...\\)`` inline math must be handled."""
    monkeypatch.setattr(sre_latex, "_candidate_ok", lambda p: True)
    monkeypatch.setattr(sre_latex, "sre_executable_path", lambda: "/fake/sre")

    calls: list[bytes] = []

    def _capture(cmd, *a, input=None, **kw):
        calls.append(input)
        return subprocess.CompletedProcess(cmd, returncode=0, stdout=b"spoken", stderr=b"")

    monkeypatch.setattr(subprocess, "run", _capture)
    latex_to_speech(r"Inline: \(x + 1\) here.")
    assert calls == [b"x + 1"]


def test_starred_equation_environment_matched(monkeypatch):
    """``\\begin{equation*}`` closes with ``\\end{equation*}`` (named backref)."""
    monkeypatch.setattr(sre_latex, "_candidate_ok", lambda p: True)
    monkeypatch.setattr(sre_latex, "sre_executable_path", lambda: "/fake/sre")

    calls: list[bytes] = []

    def _capture(cmd, *a, input=None, **kw):
        calls.append(input)
        return subprocess.CompletedProcess(cmd, returncode=0, stdout=b"spoken", stderr=b"")

    monkeypatch.setattr(subprocess, "run", _capture)
    latex_to_speech(r"\begin{equation*}E = mc^2\end{equation*}")
    assert calls == [b"E = mc^2"]


def test_gather_environment_matched(monkeypatch):
    """``\\begin{gather}`` must be recognized."""
    monkeypatch.setattr(sre_latex, "_candidate_ok", lambda p: True)
    monkeypatch.setattr(sre_latex, "sre_executable_path", lambda: "/fake/sre")

    calls: list[bytes] = []

    def _capture(cmd, *a, input=None, **kw):
        calls.append(input)
        return subprocess.CompletedProcess(cmd, returncode=0, stdout=b"spoken", stderr=b"")

    monkeypatch.setattr(subprocess, "run", _capture)
    latex_to_speech(r"\begin{gather}a = b\\c = d\end{gather}")
    assert len(calls) == 1


def test_stderr_not_logged_raw_on_failure(monkeypatch, caplog):
    """SRE stderr must NOT appear verbatim in log output."""
    import logging

    monkeypatch.setattr(sre_latex, "_candidate_ok", lambda p: True)
    monkeypatch.setattr(sre_latex, "sre_executable_path", lambda: "/fake/sre")

    secret = b"<user LaTeX> \\frac{secret}{formula} <end>"

    def _fail(cmd, *a, **kw):
        return subprocess.CompletedProcess(cmd, returncode=1, stdout=b"", stderr=secret)

    monkeypatch.setattr(subprocess, "run", _fail)

    with caplog.at_level(logging.WARNING, logger="lexaloud.preprocessor.sre_latex"):
        latex_to_speech("$x^2$")

    # The warning line must reference a fingerprint (length + sha1)
    # but must not contain the raw bytes.
    joined = " ".join(rec.getMessage() for rec in caplog.records)
    assert "secret" not in joined
    assert "formula" not in joined
    # Length appears as "<N>B" and the sha1 prefix starts with "sha1="
    assert "sha1=" in joined


def test_display_math_matched_before_inline(monkeypatch):
    """``$$...$$`` must be matched as a whole, not as two inline $...$."""
    monkeypatch.setattr(sre_latex, "_candidate_ok", lambda p: True)
    monkeypatch.setattr(sre_latex, "sre_executable_path", lambda: "/fake/sre")

    calls: list[bytes] = []

    def _capture(cmd, *a, input=None, **kw):
        calls.append(input)
        return subprocess.CompletedProcess(cmd, returncode=0, stdout=b"display spoken", stderr=b"")

    monkeypatch.setattr(subprocess, "run", _capture)
    latex_to_speech("Block: $$a + b$$ done.")
    assert len(calls) == 1
    assert calls[0] == b"a + b"


def test_preprocess_pipeline_passthrough_without_sre(monkeypatch):
    """preprocess() with sre_latex_enabled=False must not invoke the module."""
    from lexaloud.preprocessor import PreprocessorConfig, preprocess

    cfg = PreprocessorConfig(sre_latex_enabled=False)
    # No mocking of subprocess — if it fires, the test fails fast.
    sents = preprocess("Plain prose.", cfg)
    assert sents == ["Plain prose."]


def test_pipeline_preserves_bracket_delimiters_through_markdown(monkeypatch):
    """Regression: markdown stripping must not unescape \\(...\\) / \\[...\\].

    CommonMark treats ``\\(`` as a backslash-escape for ``(``, which
    would destroy the MathJax-style delimiters before SRE sees them.
    ``markdown_to_tts_prose`` protects them with PUA sentinels.
    """
    from lexaloud.preprocessor import PreprocessorConfig, preprocess

    monkeypatch.setattr(sre_latex, "_candidate_ok", lambda p: True)
    monkeypatch.setattr(sre_latex, "sre_executable_path", lambda: "/fake/sre")

    seen_inputs: list[bytes] = []

    def _capture(cmd, *a, input=None, **kw):
        seen_inputs.append(input)
        return subprocess.CompletedProcess(cmd, returncode=0, stdout=b"SPOKEN", stderr=b"")

    monkeypatch.setattr(subprocess, "run", _capture)

    cfg = PreprocessorConfig(sre_latex_enabled=True)

    # Inline \(...\) inside markdown-heading-triggered document.
    seen_inputs.clear()
    preprocess(r"# Math" "\n\n" r"\(x_0\)", cfg)
    assert seen_inputs == [b"x_0"]

    # Display \[...\] inside markdown-heading-triggered document.
    seen_inputs.clear()
    preprocess(r"# Math" "\n\n" r"\[a + b\]", cfg)
    assert seen_inputs == [b"a + b"]

    # Mixed $...$ still works (sanity check we didn't regress).
    seen_inputs.clear()
    preprocess(r"# Math" "\n\n" r"$x_0$", cfg)
    assert seen_inputs == [b"x_0"]


def test_preprocess_pipeline_calls_sre_when_enabled(monkeypatch):
    """Pipeline with sre_latex_enabled=True invokes latex_to_speech."""
    from lexaloud.preprocessor import PreprocessorConfig, preprocess

    called = {"n": 0}
    orig = sre_latex.latex_to_speech

    def _spy(text, **kw):
        called["n"] += 1
        return orig(text, **kw)

    monkeypatch.setattr(sre_latex, "latex_to_speech", _spy)
    # Also patch the re-exported symbol used inside preprocess()
    from lexaloud.preprocessor import __init__ as preproc_init  # noqa: F401

    cfg = PreprocessorConfig(sre_latex_enabled=True)
    # Force no SRE so we don't actually hit a subprocess.
    monkeypatch.setattr(sre_latex, "_candidate_ok", lambda p: False)
    preprocess("Some text without LaTeX.", cfg)
    assert called["n"] == 1
