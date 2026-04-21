# MORNING-HANDOFF.md

Working log for `feat/math-markdown-preprocessing`. Kept in-tree while
the PR is open so reviewers can read the full story. Remove on merge.

## Current state

- **Branch**: `feat/math-markdown-preprocessing`
- **Tracks**: `origin/feat/math-markdown-preprocessing` (pushed)
- **PR**: https://github.com/Gustavjiversen01/lexaloud/pull/13
The commit list is deliberately omitted here to avoid going stale
after each push. Use `git log --oneline main..HEAD` to see the
current state of the branch. The commits group into three phases:

- **Original plan (phase 1–3)**: dedupe, markdown stripping,
  integration test, docs, SRE bridge, installer flag, benchmark
  corpus.
- **First-round fixups**: symbol-spacing (`x∈X` → `x in X`),
  markdown heuristic tightening, SRE stderr scrubbing + delimiter
  extension, install help, [sre_latex] config docs, image alt-text
  double-period.
- **Second-round fixups**: `\(...\) / \[...\]` preservation through
  markdown-it-py, per-call UUID sentinels (avoids PUA collision),
  lockfile regeneration for `markdown-it-py` + `mdurl`.

## Test counts

| Snapshot | Count | Notes |
|---|---|---|
| Preflight baseline on `main` | 329 passed in ~2s | (see exclusions below) |
| After initial PR (phase 1–3) | 392 passed | +63 new |
| After fixup rounds | 417+ passed in ~2s | each new regression from review adds a guard test |

Run the gate (below) for the exact current count.

Gate used throughout:

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
`bash -n scripts/install.sh`. All green on every commit.

### Known baseline exclusions (pre-existing, not introduced by this branch)

- `tests/test_audio_fixes.py` — baseline hang on this box (asyncio
  default-executor interaction with `SoundDeviceSink.begin_stream`).
- `tests/test_real_kokoro_smoke.py`, `tests/test_real_llm_normalize.py`,
  `tests/test_real_sre_latex.py`, `tests/benchmarks/test_benchmark_corpus_{sre,llm}.py`
  — opt-in integration tests, skipped by default.

### Gate-command correction

The original plan specified `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, but
that flag prevents pytest-asyncio from loading and broke 55 async
tests on this box. Dropped from the gate after preflight. `conftest.py`
already scrubs `PYTHONPATH` for ROS pollution, so the autoload-disable
is redundant here.

## Code-review findings addressed

First round (commits 9–12):

| # | Severity | Summary | Commit |
|---|---|---|---|
| 1 | H | `x∈X` → `xinX` glued output | 0d9408c |
| 2 | H | Markdown heuristic false-positives (`__init__` → `init`, `a*b*c` → `abc`) | 995e653 |
| 3 | M | SRE stderr logged raw (privacy leak) | 278e024 |
| 4 | M | SRE regex missed `\(...\)`, `\[...\]`, starred environments | 278e024 |
| 5 | M | Gate-command inconsistency between plan and implementation | documented here |
| 6 | M | Branch pushed despite "local only" plan clause | superseded by explicit user request |
| 7 | M | Production install still broken until lockfiles regenerated | deferred (see below) |
| 8 | L | `install.sh --help` missing `--with-math-speech`, leaking `set -euo pipefail` | 7f59af5 |
| 9 | L | `configuration.md` missing `[sre_latex]` section | 7f59af5 |
| 10 | L | Image alt text producing double period | 7f59af5 |

Second round (commit 13):

| # | Severity | Summary | Commit |
|---|---|---|---|
| 1 | H | Markdown stripping unescaped `\(` / `\[` before SRE saw them — bug only manifested in the full pipeline, not in direct `latex_to_speech()` calls | b4ec0b1 (sentinel protection via PUA codepoints) |
| 2 | M | Markdown heuristic still leaves inline-only `*word*` and `` `x` `` unresolved in non-markdown prose | documented as intentional trade-off in `docs/configuration.md` |
| 3 | M | Lockfiles remain unregenerated | deferred morning action (below) |
| 4 | L | This handoff file was stale after the fixup commits | now refreshed |
| 5 | L | `docs/install/math-speech.md` delimiter list was stale | synced with `docs/configuration.md` |

## Ready for morning review

- **Phase 1 (commits 1–4, 9, 10, 13)**: MathJax dedupe + markdown
  stripping + symbol spacing + heuristic tightening + SRE-delimiter
  protection. Default-on. Zero new runtime deps beyond `markdown-it-py`.
- **Phase 2 (commits 5, 6, 11)**: SRE LaTeX bridge with full delimiter
  coverage and privacy-safe error logging. Opt-in via `[sre_latex]
  enabled = true`. Gracefully no-ops when `sre` is not resolvable.
- **Phase 3 (commit 7)**: 21-case benchmark corpus + opt-in SRE and
  LLM variant runners.
- **Polish (commits 8, 12)**: docs, installer help, image double-period.

### Manual sanity check (no install needed)

```bash
env PYTHONPATH=src .venv-spike0/bin/python -c "
from pathlib import Path
from lexaloud.preprocessor import preprocess, PreprocessorConfig
text = Path('tests/fixtures/mathjax_rl_sample.txt').read_text()
for s in preprocess(text, PreprocessorConfig()):
    print('>>>', s)
"
```

Expected (after the symbol-spacing fix): 5 clean sentences with
`x in X`, `u in U`, and `rho` all spelled out. No duplicated symbols.
No zero-width chars.

## Deferred morning actions

1. **Verify lockfile regeneration is sufficient** — `markdown-it-py`
   4.0.0 and its `mdurl` 0.1.2 transitive dep were added by hand to
   both `requirements-lock.cpu.txt` and `requirements-lock.cuda12.txt`
   with their PyPI-published SHA-256 hashes (wheel + sdist). Both
   lockfiles were validated with `pip install --dry-run
   --require-hashes --no-deps -r <lockfile>` against a fresh venv.
   The maintainer may still want to run a full `pip-compile
   --generate-hashes` regeneration at the next release to pick up
   any drifted transitive pins — this is a cosmetic alignment, not
   a correctness fix.

2. **Optional: install the SRE runtime** if you want Phase 2
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
   Restart: `systemctl --user restart lexaloud.service`. Opt-in
   benchmark:
   ```bash
   LEXALOUD_REAL_SRE=1 env PYTHONPATH=src .venv-spike0/bin/python \
     -m pytest tests/benchmarks/test_benchmark_corpus_sre.py -v
   ```

3. **CHANGELOG.md** entries for the Unreleased section — deferred so
   the reviewer can frame them for the release.

## Verification commands

From the branch head:

```bash
env PYTHONPATH=src .venv-spike0/bin/python -m pytest tests/ \
    --ignore=tests/test_real_kokoro_smoke.py \
    --ignore=tests/test_real_llm_normalize.py \
    --ignore=tests/test_real_sre_latex.py \
    --ignore=tests/test_audio_fixes.py \
    --ignore=tests/benchmarks/test_benchmark_corpus_sre.py \
    --ignore=tests/benchmarks/test_benchmark_corpus_llm.py \
    -q
.venv-spike0/bin/python -m ruff check src/ tests/
.venv-spike0/bin/python -m ruff format --check src/ tests/
.venv-spike0/bin/python -m mypy src/lexaloud
bash -n scripts/install.sh
```

All should exit zero.
