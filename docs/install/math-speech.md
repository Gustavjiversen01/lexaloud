# LaTeX-to-speech (optional)

By default Lexaloud reads Unicode math symbols (Greek letters, operators,
superscripts) via the rule-based `normalize_math_symbols` stage. That
handles `α ≤ β` → "alpha less than or equal to beta" but does not
understand LaTeX structure — subscripts, fractions, sums, integrals,
expectations — so dense academic prose can still sound nonsensical.

The `[sre_latex]` stage sends every LaTeX math span through
[Speech Rule Engine](https://github.com/Speech-Rule-Engine/speech-rule-engine).
Recognized delimiters:

- `$...$` — inline math (TeX/LaTeX)
- `$$...$$` — display math (TeX/LaTeX)
- `\(...\)` — inline math (MathJax convention)
- `\[...\]` — display math (MathJax convention)
- `\begin{equation}...\end{equation}`, and the starred variant `equation*`
- `\begin{align}...\end{align}`, and the starred variant `align*`
- `\begin{gather}...\end{gather}` / `gather*`
- `\begin{multline}...\end{multline}` / `multline*`
- `\begin{eqnarray}...\end{eqnarray}` / `eqnarray*`

Markdown stripping (when enabled) protects the `\(...\)` / `\[...\]`
delimiters from CommonMark's backslash-escape rule so they survive
into the SRE stage — you don't need to disable `strip_markdown` to
use them in a mixed-content document.
SRE is the same Apache-2.0 engine that powers MathJax and ChromeVox.
Examples of what it produces under the default `clearspeak` domain:

| LaTeX | Spoken |
|-------|--------|
| `\frac{a}{b}` | "a over b" |
| `x^2` | "x squared" |
| `x_{t+1}` | "x sub t plus 1" |
| `\sum_t r(x_t, u_t)` | "sum over t of r of x sub t comma u sub t" |
| `E_{x_0 \sim \rho_0}` | "E sub x sub 0 tilde rho sub 0" |

It is opt-in because it requires Node.js ≥18 at runtime and adds
~60 MB on disk for the SRE package + its mathmaps locale files.

## Install

Prerequisite: a working Lexaloud venv from `scripts/install.sh`.

```bash
# Install Node.js + npm (one-time)
sudo apt install nodejs npm        # Debian/Ubuntu
sudo dnf install nodejs npm        # Fedora
sudo pacman -S nodejs npm          # Arch

# Run the installer with the new flag
./scripts/install.sh --with-math-speech
```

The `--with-math-speech` flag:

- Verifies `node` and `npm` are on PATH
- Enforces Node.js major ≥ 18
- Runs `npm install --prefix ~/.local/share/lexaloud/sre speech-rule-engine@4.1.3`
  (exact version pin; the latest npm tag may point at a beta release)
- Symlinks the installed `sre` binary into the venv's `bin/` so the
  daemon can resolve it under systemd without any PATH configuration

## Enable

Add to `~/.config/lexaloud/config.toml`:

```toml
[sre_latex]
enabled = true
domain = "clearspeak"    # or "mathspeak"
# style = "verbose"      # optional; omit for domain default
# timeout_s = 10.0
```

Restart the daemon:

```bash
systemctl --user restart lexaloud.service
```

## Troubleshooting

Check whether the daemon can see the `sre` binary:

```bash
~/.local/share/lexaloud/venv/bin/python -c "
from lexaloud.preprocessor.sre_latex import is_sre_available, sre_executable_path
print('available:', is_sre_available())
print('path:', sre_executable_path())
"
```

If `is_sre_available()` prints `False`, verify:

1. The symlink exists and is executable:
   `ls -l ~/.local/share/lexaloud/venv/bin/sre`
2. The target exists and is executable:
   `ls -l ~/.local/share/lexaloud/sre/node_modules/.bin/sre`
3. Node is working: `node --version` reports ≥18

## License

`speech-rule-engine@4.1.3` is distributed under the Apache-2.0 license.
See [`THIRD_PARTY_LICENSES.md`](../../THIRD_PARTY_LICENSES.md#optional-runtime-dependencies)
for Lexaloud's disclosure.
