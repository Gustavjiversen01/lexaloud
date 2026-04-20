"""Opt-in integration test for the real SRE LaTeX bridge.

Requires:
  - Node.js >=18 installed
  - speech-rule-engine installed (scripts/install.sh --with-math-speech)
  - LEXALOUD_REAL_SRE=1 environment variable

Run:
  LEXALOUD_REAL_SRE=1 python -m pytest tests/test_real_sre_latex.py -s
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("LEXALOUD_REAL_SRE") != "1",
    reason="Set LEXALOUD_REAL_SRE=1 to run real SRE integration tests",
)

from lexaloud.preprocessor.sre_latex import (  # noqa: E402
    is_sre_available,
    latex_to_speech,
)


@pytest.fixture(autouse=True)
def _require_sre():
    if not is_sre_available():
        pytest.skip(
            "SRE executable not resolvable — install with scripts/install.sh --with-math-speech"
        )


def test_inline_fraction_spoken():
    out = latex_to_speech(r"The value $\frac{a}{b}$ is a fraction.")
    assert "over" in out.lower() or "fraction" in out.lower()
    assert r"\frac" not in out


def test_subscript_spoken():
    out = latex_to_speech(r"Consider $E_{x_0}$ as expectation.")
    assert "sub" in out.lower()


def test_squared_spoken():
    out = latex_to_speech(r"The quantity $x^2$ is squared.")
    assert "squared" in out.lower() or "square" in out.lower()
