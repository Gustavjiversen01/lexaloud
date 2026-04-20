# MORNING-HANDOFF.md

Overnight run of `feat/math-markdown-preprocessing` completed successfully.
All 7 planned commits landed. Every commit passes the verification gate.

## Branch state

- **Branch**: `feat/math-markdown-preprocessing` (local only — not pushed)
- **Parent**: `main` at `7b55724`
- **Commits landed** (oldest → newest):
  1. `2b53f85` `feat(preprocessor): add MathJax selection dedupe`
  2. `59aa55f` `feat(preprocessor): add markdown stripping via markdown-it-py`
  3. `f5d1101` `test(preprocessor): end-to-end integration test on RL sample`
  4. `9c2d097` `docs: document MathJax dedupe and markdown stripping options`
  5. `dc18407` `feat(preprocessor): add SRE LaTeX bridge (opt-in, Node required)`
  6. `6f3c456` `feat(install): add --with-math-speech flag to install.sh`
  7. `bc66f9c` `test(benchmarks): add math/markdown benchmark corpus and runner`

## Test counts

| State | Count | Notes |
|---|---|---|
| Preflight baseline on `main` | 329 passed in 2.01s | (see exclusions below) |
| After commit 7 | 392 passed in 2.06s | +63 new tests |

Delta: 12 dedupe + 15 markdown + 1 integration + 14 SRE (mocked) + 21 benchmark = **63 new tests**.

The gate used throughout the run:

```bash
env PYTHONPATH=src .venv-spike0/bin/python -m pytest tests/ \
    --ignore=tests/test_real_kokoro_smoke.py \
    --ignore=tests/test_real_llm_normalize.py \
    --ignore=tests/test_real_sre_latex.py \
    --ignore=tests/test_audio_fixes.py \
    --ignore=tests/benchmarks/test_benchmark_corpus_sre.py \
    --ignore=tests/benchmarks/test_benchmark_corpus_llm.py \
    -q
```

Plus `ruff check`, `ruff format --check`, `mypy src/lexaloud`, and
`bash -n scripts/install.sh` (after commit 6). All green on every commit.

### Known baseline exclusions (pre-existing)

- `tests/test_audio_fixes.py` — hangs on this box (asyncio default
  executor interaction with `SoundDeviceSink.begin_stream`). Excluded
  as a documented baseline issue, NOT introduced by this branch.
- `tests/test_real_kokoro_smoke.py`, `tests/test_real_llm_normalize.py`,
  `tests/test_real_sre_latex.py`, `tests/benchmarks/test_benchmark_corpus_{sre,llm}.py`
  — opt-in integration tests, skipped by default.

### Gate-command correction

The original plan specified `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, but that
flag prevents pytest-asyncio from loading and broke all 55 async tests
on this box. It was dropped from the gate after preflight. `conftest.py`
already scrubs `PYTHONPATH` for ROS pollution, so the autoload-disable
is redundant on the current machine.

## Ready for morning review

The branch is fully testable right now:

- **Phase 1 (Commits 1–4)**: MathJax dedupe + markdown stripping.
  Default-on. Zero new runtime deps beyond `markdown-it-py` (already
  a transitive dep via `rich`, now a direct dep in `pyproject.toml`).
- **Phase 2 (Commits 5–6)**: SRE LaTeX bridge. Opt-in via
  `[sre_latex] enabled = true` in `config.toml`. Gracefully no-ops
  when the `sre` binary is not resolvable, so Phase 2 code is safe
  to merge without installing Node.
- **Phase 3 (Commit 7)**: Benchmark corpus (21 cases) running under
  the rule-only pipeline. Opt-in SRE and LLM variants ready to run
  once the respective runtimes are available.

### Manual sanity check (run without installing anything)

```bash
env PYTHONPATH=src .venv-spike0/bin/python -c "
from pathlib import Path
from lexaloud.preprocessor import preprocess, PreprocessorConfig
text = Path('tests/fixtures/mathjax_rl_sample.txt').read_text()
for s in preprocess(text, PreprocessorConfig()):
    print('>>>', s)
"
```

Expected output (verified during the run): 5 clean sentences with
`rho` expanded, no duplicated math symbols, no zero-width chars.

## Deferred morning actions

1. **Regenerate the hashed lockfiles** before the next release so
   `scripts/install.sh` actually installs `markdown-it-py`:
   ```bash
   .venv-spike0/bin/pip install pip-tools
   .venv-spike0/bin/pip-compile --generate-hashes \
       --output-file=requirements-lock.cpu.txt pyproject.toml
   .venv-spike0/bin/pip-compile --generate-hashes \
       --output-file=requirements-lock.cuda12.txt pyproject.toml \
       --extra=gpu   # or whatever extra the cuda12 path uses
   ```
   (Exact pip-compile invocation may need adjustment — check the
   existing lockfile headers for the command that generated them.)
   Until this is done, the branch is **not production-installable
   via `scripts/install.sh`** — the Python dependency on
   `markdown-it-py` will not be present in a fresh install.
2. **Optional: install the SRE runtime** if you want to try Phase 2
   end-to-end:
   ```bash
   sudo apt install nodejs npm   # or dnf/pacman equivalent
   ./scripts/install.sh --with-math-speech
   ```
   Then enable in `~/.config/lexaloud/config.toml`:
   ```toml
   [sre_latex]
   enabled = true
   domain = "clearspeak"
   ```
   Restart: `systemctl --user restart lexaloud.service`. Run the
   opt-in benchmark:
   ```bash
   LEXALOUD_REAL_SRE=1 env PYTHONPATH=src .venv-spike0/bin/python \
     -m pytest tests/benchmarks/test_benchmark_corpus_sre.py -v
   ```
3. **Push the branch and open a PR** if desired:
   ```bash
   git push -u origin feat/math-markdown-preprocessing
   gh pr create --fill
   ```
4. **Update `CHANGELOG.md`** with the Unreleased section entries.
   Deferred so the morning reviewer can frame them for a release note.

## Verification commands (reproduce any commit's gate)

From the branch head:

```bash
# Standard test gate
env PYTHONPATH=src .venv-spike0/bin/python -m pytest tests/ \
    --ignore=tests/test_real_kokoro_smoke.py \
    --ignore=tests/test_real_llm_normalize.py \
    --ignore=tests/test_real_sre_latex.py \
    --ignore=tests/test_audio_fixes.py \
    --ignore=tests/benchmarks/test_benchmark_corpus_sre.py \
    --ignore=tests/benchmarks/test_benchmark_corpus_llm.py \
    -q

# Style + types
.venv-spike0/bin/python -m ruff check src/ tests/
.venv-spike0/bin/python -m ruff format --check src/ tests/
.venv-spike0/bin/python -m mypy src/lexaloud

# Installer syntax
bash -n scripts/install.sh
```

All should exit zero.
