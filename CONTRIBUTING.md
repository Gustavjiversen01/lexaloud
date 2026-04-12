# Contributing to Lexaloud

Thanks for your interest. Lexaloud is a solo-maintained side project, so
please be patient with response times.

## Before you open a PR

1. **Open an issue first** if you're proposing a non-trivial change. A
   30-minute discussion up front can save hours of rework later.
2. **Check the ROADMAP** — items marked "deferred to v0.2+" are by design
   not in the current release. If you're planning work on one, check the
   issues list and claim the ticket so we don't duplicate.

## Dev environment

```bash
git clone https://github.com/Gustavjiversen01/lexaloud.git
cd lexaloud
./scripts/install.sh       # sets up the production venv
python3 -m venv .venv-dev  # separate dev venv for tests + tooling
source .venv-dev/bin/activate
pip install -e .[dev,test]
```

Run the test suite:

```bash
env -u PYTHONPATH .venv-dev/bin/python -m pytest tests/ \
    --ignore=tests/test_real_kokoro_smoke.py -q
```

Target: 206 tests passing, under 3 seconds. No GPU or audio device needed
(tests use `FakeProvider` + `NullSink` + `ASGITransport`).

For a full end-to-end test with the real Kokoro model and real
`sounddevice`:

```bash
LEXALOUD_REAL_TTS=1 .venv-dev/bin/python -m pytest tests/test_real_kokoro_smoke.py -s
```

## Coding style

- `ruff check .` and `ruff format .` must pass. Config is in `pyproject.toml`.
- `mypy src/lexaloud` should pass without new errors. Stub gaps in `pysbd`,
  `sounddevice`, `gi`, and `kokoro_onnx` are allow-listed.
- Python 3.11+ syntax. Use `from __future__ import annotations` at the top
  of new modules.
- Keep imports sorted; ruff does this.

## Commits

- **Sign off** every commit with `git commit -s` (DCO). This adds a
  `Signed-off-by:` trailer confirming you have the right to contribute
  the change under the project's MIT license.
- Conventional Commits style is encouraged but not enforced:
  `feat(scope): ...`, `fix(scope): ...`, `docs(scope): ...`,
  `chore(scope): ...`, `refactor(scope): ...`, `test(scope): ...`.
- Keep commits small and focused. Atomic commits are easier to review and
  bisect.

## Pull request checklist

- [ ] Tests pass locally
- [ ] `ruff check .` and `ruff format --check .` pass
- [ ] Added or updated tests for new behavior
- [ ] Updated `CHANGELOG.md` under `[Unreleased]`
- [ ] Commits are signed off (DCO)
- [ ] PR description explains *why* more than *what*

## Not currently accepting

The following are explicitly deferred per the `ROADMAP.md` — if you want
to contribute one of these, please open a discussion first:

- Karaoke word-level highlighting
- Browser extension
- LLM-based text normalization
- Additional TTS providers (Piper, Chatterbox, etc.)
- Flatpak / Snap / AppImage / AUR / COPR packaging

## Questions?

Open a GitHub Discussion (once Discussions are enabled on the repo) or
file an issue with the `question` label.
