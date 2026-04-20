#!/usr/bin/env bash
#
# Lexaloud installer — Phase A bootstrap.
#
# Creates a dedicated venv at ~/.local/share/lexaloud/venv/, installs the
# pinned dependency set (requirements-lock.cuda12.txt or requirements-lock.cpu.txt
# from Spike 0), then the lexaloud package itself.
#
# After this script succeeds:
#
#   ~/.local/share/lexaloud/venv/bin/lexaloud setup
#
# will finish the configuration (download models, render systemd unit,
# print hotkey binding walkthrough).
#
# Usage:
#   ./scripts/install.sh                    # auto-detect GPU, pick backend
#   ./scripts/install.sh --backend cuda12   # force NVIDIA GPU backend
#   ./scripts/install.sh --backend cpu      # force CPU-only backend
#   ./scripts/install.sh --backend auto     # equivalent to no flag

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DEFAULT="$HOME/.local/share/lexaloud/venv"
VENV="${LEXALOUD_VENV:-$VENV_DEFAULT}"

BACKEND="auto"
WITH_MATH_SPEECH=0

# --- parse arguments ----------------------------------------------------

while (( "$#" )); do
  case "$1" in
    --backend)
      BACKEND="$2"
      shift 2
      ;;
    --backend=*)
      BACKEND="${1#*=}"
      shift
      ;;
    --with-math-speech)
      WITH_MATH_SPEECH=1
      shift
      ;;
    -h|--help)
      sed -n '4,22p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      echo "Usage: $0 [--backend cpu|cuda12|auto] [--with-math-speech]" >&2
      exit 2
      ;;
  esac
done

if [[ "$BACKEND" != "cpu" && "$BACKEND" != "cuda12" && "$BACKEND" != "auto" ]]; then
  echo "Invalid --backend value: $BACKEND (must be cpu, cuda12, or auto)" >&2
  exit 2
fi

echo "=== Lexaloud installer ==="
echo "repo root: $REPO_ROOT"
echo "target venv: $VENV"
echo "backend: $BACKEND"
echo

# --- distro detection ---------------------------------------------------

DISTRO_ID="unknown"
DISTRO_LIKE=""
if [[ -f /etc/os-release ]]; then
  # shellcheck disable=SC1091
  DISTRO_ID="$(. /etc/os-release && echo "${ID:-unknown}")"
  DISTRO_LIKE="$(. /etc/os-release && echo "${ID_LIKE:-}")"
fi
echo "distro: $DISTRO_ID (like: ${DISTRO_LIKE:-none})"

# Classify into a package-manager family.
DISTRO_FAMILY="unknown"
case "$DISTRO_ID" in
  ubuntu|debian|linuxmint|pop|elementary|kali|zorin) DISTRO_FAMILY="debian" ;;
  fedora|rhel|centos|rocky|almalinux) DISTRO_FAMILY="fedora" ;;
  arch|manjaro|endeavouros|garuda|artix) DISTRO_FAMILY="arch" ;;
  opensuse*|sles) DISTRO_FAMILY="suse" ;;
esac
# Also check ID_LIKE for families that didn't hit the ID switch above.
if [[ "$DISTRO_FAMILY" == "unknown" && -n "$DISTRO_LIKE" ]]; then
  case "$DISTRO_LIKE" in
    *debian*|*ubuntu*) DISTRO_FAMILY="debian" ;;
    *fedora*|*rhel*)   DISTRO_FAMILY="fedora" ;;
    *arch*)            DISTRO_FAMILY="arch" ;;
    *suse*)            DISTRO_FAMILY="suse" ;;
  esac
fi
echo "distro family: $DISTRO_FAMILY"
echo

# --- Python version check (≥3.11) --------------------------------------

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 is not installed." >&2
  exit 1
fi
PY_VERSION="$(python3 -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')"
PY_MAJOR="$(echo "$PY_VERSION" | cut -d. -f1)"
PY_MINOR="$(echo "$PY_VERSION" | cut -d. -f2)"
if (( PY_MAJOR < 3 || ( PY_MAJOR == 3 && PY_MINOR < 11 ) )); then
  cat >&2 <<EOF
ERROR: Python $PY_VERSION is too old. Lexaloud requires Python >= 3.11.
       Please install a newer Python via your distro's package manager.
EOF
  exit 1
fi
echo "python3: $PY_VERSION (ok)"
echo

# --- system dependency check (distro-aware) -----------------------------

missing=()

if ! python3 -c 'import venv' 2>/dev/null; then
  missing+=("python3-venv")
fi
if ! command -v wl-paste >/dev/null 2>&1; then
  missing+=("wl-clipboard")
fi
if ! command -v xclip >/dev/null 2>&1; then
  missing+=("xclip")
fi
# libportaudio2 — probe via ldconfig
LDCONFIG_OUT="$(ldconfig -p 2>/dev/null || true)"
if [[ "$LDCONFIG_OUT" != *libportaudio.so.2* ]]; then
  missing+=("libportaudio2")
fi
unset LDCONFIG_OUT
if ! command -v notify-send >/dev/null 2>&1; then
  missing+=("libnotify-bin")
fi

if (( ${#missing[@]} > 0 )); then
  mapfile -t missing < <(printf "%s\n" "${missing[@]}" | awk '!seen[$0]++')
  echo "Missing system packages (conceptual names):" >&2
  for p in "${missing[@]}"; do echo "  - $p" >&2; done
  echo >&2
  case "$DISTRO_FAMILY" in
    debian)
      echo "Install them with:" >&2
      echo "  sudo apt install ${missing[*]}" >&2
      ;;
    fedora)
      # Translate Debian package names to Fedora equivalents
      fedora_pkgs=()
      for p in "${missing[@]}"; do
        case "$p" in
          python3-venv)   fedora_pkgs+=("python3") ;;
          wl-clipboard)   fedora_pkgs+=("wl-clipboard") ;;
          xclip)          fedora_pkgs+=("xclip") ;;
          libportaudio2)  fedora_pkgs+=("portaudio") ;;
          libnotify-bin)  fedora_pkgs+=("libnotify") ;;
          *)              fedora_pkgs+=("$p") ;;
        esac
      done
      echo "Install them with:" >&2
      echo "  sudo dnf install ${fedora_pkgs[*]}" >&2
      ;;
    arch)
      arch_pkgs=()
      for p in "${missing[@]}"; do
        case "$p" in
          python3-venv)   arch_pkgs+=("python") ;;
          wl-clipboard)   arch_pkgs+=("wl-clipboard") ;;
          xclip)          arch_pkgs+=("xclip") ;;
          libportaudio2)  arch_pkgs+=("portaudio") ;;
          libnotify-bin)  arch_pkgs+=("libnotify") ;;
          *)              arch_pkgs+=("$p") ;;
        esac
      done
      echo "Install them with:" >&2
      echo "  sudo pacman -S ${arch_pkgs[*]}" >&2
      ;;
    suse)
      suse_pkgs=()
      for p in "${missing[@]}"; do
        case "$p" in
          python3-venv)   suse_pkgs+=("python3") ;;
          wl-clipboard)   suse_pkgs+=("wl-clipboard") ;;
          xclip)          suse_pkgs+=("xclip") ;;
          libportaudio2)  suse_pkgs+=("portaudio") ;;
          libnotify-bin)  suse_pkgs+=("libnotify-tools") ;;
          *)              suse_pkgs+=("$p") ;;
        esac
      done
      echo "Install them with:" >&2
      echo "  sudo zypper install ${suse_pkgs[*]}" >&2
      ;;
    *)
      echo "Your distro ($DISTRO_ID) isn't in our package-name table. The conceptual" >&2
      echo "names above are what you need. File a PR against scripts/install.sh to" >&2
      echo "add the package-name translation for your distro." >&2
      ;;
  esac
  exit 1
fi

# --- backend auto-detection --------------------------------------------

if [[ "$BACKEND" == "auto" ]]; then
  if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L >/dev/null 2>&1; then
    BACKEND="cuda12"
    echo "nvidia-smi detected an NVIDIA GPU → backend=cuda12"
  else
    BACKEND="cpu"
    echo "no NVIDIA GPU found → backend=cpu"
  fi
  echo
fi

LOCK="$REPO_ROOT/requirements-lock.$BACKEND.txt"
if [[ ! -f "$LOCK" ]]; then
  echo "ERROR: lockfile not found: $LOCK" >&2
  exit 1
fi

# --- PYTHONPATH pollution warning ---------------------------------------

if [[ -n "${PYTHONPATH:-}" ]]; then
  cat >&2 <<WARN
Warning: \$PYTHONPATH is set in your shell:
  PYTHONPATH=$PYTHONPATH

This typically comes from sourcing ROS 2, a game engine, or similar. We
will scrub PYTHONPATH while installing so it does not pollute the venv
lockfile, and the rendered systemd unit will also scrub it so the daemon
runs in a clean environment.
WARN
fi

# --- venv creation ------------------------------------------------------

if [[ -d "$VENV" ]]; then
  echo "venv already exists at $VENV; checking state."
  if [[ "$BACKEND" == "cuda12" ]]; then
    # Refuse to install into a venv that already has the broken dual-install
    # state Spike 0 flagged.
    if env -u PYTHONPATH "$VENV/bin/pip" show onnxruntime >/dev/null 2>&1 \
         && env -u PYTHONPATH "$VENV/bin/pip" show onnxruntime-gpu >/dev/null 2>&1; then
      cat >&2 <<BROKEN
ERROR: both 'onnxruntime' and 'onnxruntime-gpu' are installed in $VENV.
       This is the broken coexistence state Spike 0 flagged:
       - imports will silently shadow CUDAExecutionProvider to CPU
       - \`pip uninstall onnxruntime\` will break BOTH packages.

Fix: recreate the venv from scratch.

   rm -rf "$VENV"
   $0 --backend cuda12
BROKEN
      exit 1
    fi
    # Also refuse if only the CPU package is present — the lockfile install
    # below will bring onnxruntime-gpu in alongside it, producing the broken
    # state.
    if env -u PYTHONPATH "$VENV/bin/pip" show onnxruntime >/dev/null 2>&1; then
      cat >&2 <<STALE_CPU
ERROR: stale 'onnxruntime' (CPU) package detected in $VENV.
       Installing the cuda12 lockfile on top would create the broken
       dual-install state Spike 0 flagged.

Fix: recreate the venv from scratch.

   rm -rf "$VENV"
   $0 --backend cuda12
STALE_CPU
      exit 1
    fi
  else
    # cpu backend: refuse if onnxruntime-gpu is already installed (the
    # opposite case)
    if env -u PYTHONPATH "$VENV/bin/pip" show onnxruntime-gpu >/dev/null 2>&1; then
      cat >&2 <<STALE_GPU
ERROR: stale 'onnxruntime-gpu' package detected in $VENV.
       Installing the cpu lockfile on top would create a mixed install.

Fix: recreate the venv from scratch.

   rm -rf "$VENV"
   $0 --backend cpu
STALE_GPU
      exit 1
    fi
  fi
else
  echo "creating venv at $VENV"
  mkdir -p "$(dirname "$VENV")"
  python3 -m venv "$VENV"
fi

PIP="env -u PYTHONPATH $VENV/bin/pip"

echo "upgrading pip"
$PIP install --upgrade pip >/dev/null

# --- install the pinned runtime set -------------------------------------

echo "installing pinned runtime dependencies from $(basename "$LOCK")"
# Install --no-deps kokoro-onnx separately so pip doesn't re-resolve it and
# pull in the broken [gpu]-extra coexistence state Spike 0 flagged.
#
# The lockfiles contain --hash=sha256:... lines for supply-chain integrity.
# With hashed lockfiles, each package entry spans multiple lines:
#   kokoro-onnx==0.5.0 \
#       --hash=sha256:abc123 \
#       --hash=sha256:def456
# The awk filters below handle these multi-line entries correctly.

# Check that kokoro-onnx is present in the lockfile.
if ! grep -q '^kokoro-onnx==' "$LOCK"; then
  echo "ERROR: kokoro-onnx pin missing from $LOCK" >&2
  exit 1
fi

# Stage temp files before registering the trap so a signal arriving between
# mktemp and trap can't leak them.
LOCK_NO_KOKORO=""
KOKORO_REQ=""
trap '[[ -n "${LOCK_NO_KOKORO:-}" ]] && rm -f "$LOCK_NO_KOKORO"; [[ -n "${KOKORO_REQ:-}" ]] && rm -f "$KOKORO_REQ"' EXIT

# Filter OUT kokoro-onnx (and its hash continuation lines) for the main install.
LOCK_NO_KOKORO="$(mktemp)"
awk '/^kokoro-onnx==/{skip=1; next} /^[^ \t]/{skip=0} !skip' "$LOCK" > "$LOCK_NO_KOKORO"

# Extract the full kokoro-onnx entry (package line + all hash lines) for
# the separate --no-deps install. pip only accepts --hash inside -r files,
# not on the command line.
KOKORO_REQ="$(mktemp)"
awk '/^kokoro-onnx==/{found=1} found{print} found && !/\\$/{if(found) exit}' "$LOCK" > "$KOKORO_REQ"

$PIP install --require-hashes -r "$LOCK_NO_KOKORO"
$PIP install --no-deps --require-hashes -r "$KOKORO_REQ"

# --- install the lexaloud package --------------------------------------

echo "installing the lexaloud package (editable)"
$PIP install --no-deps -e "$REPO_ROOT"

# --- smoke check: the expected ORT distribution is present --------------

if [[ "$BACKEND" == "cuda12" ]]; then
  if $PIP show onnxruntime >/dev/null 2>&1; then
    echo "ERROR: 'onnxruntime' (CPU) was pulled into the venv somehow; aborting." >&2
    exit 1
  fi
  if ! $PIP show onnxruntime-gpu >/dev/null 2>&1; then
    echo "ERROR: 'onnxruntime-gpu' is missing after install; aborting." >&2
    exit 1
  fi
else
  if $PIP show onnxruntime-gpu >/dev/null 2>&1; then
    echo "ERROR: 'onnxruntime-gpu' was pulled into the venv unexpectedly; aborting." >&2
    exit 1
  fi
  if ! $PIP show onnxruntime >/dev/null 2>&1; then
    echo "ERROR: 'onnxruntime' is missing after install; aborting." >&2
    exit 1
  fi
fi

# --- optional: Speech Rule Engine (SRE) for LaTeX-to-speech -------------

if (( WITH_MATH_SPEECH == 1 )); then
  echo
  echo "--- installing Speech Rule Engine (SRE) for LaTeX-to-speech ---"

  if ! command -v node >/dev/null 2>&1; then
    cat >&2 <<NODE_MISSING
ERROR: --with-math-speech requires node (>=18).
Install it with one of:
  sudo apt install nodejs npm          # Debian/Ubuntu
  sudo dnf install nodejs npm          # Fedora
  sudo pacman -S nodejs npm            # Arch
NODE_MISSING
    exit 1
  fi
  if ! command -v npm >/dev/null 2>&1; then
    cat >&2 <<NPM_MISSING
ERROR: --with-math-speech requires npm.
Install it with one of:
  sudo apt install npm
  sudo dnf install npm
  sudo pacman -S npm
NPM_MISSING
    exit 1
  fi

  NODE_MAJOR="$(node -p 'Number(process.versions.node.split(".")[0])' 2>/dev/null || echo 0)"
  if (( NODE_MAJOR < 18 )); then
    echo "ERROR: --with-math-speech requires Node.js >= 18 (found major=$NODE_MAJOR)" >&2
    exit 1
  fi

  SRE_PREFIX="$(dirname "$VENV")/sre"
  echo "installing speech-rule-engine@4.1.3 into $SRE_PREFIX"
  mkdir -p "$SRE_PREFIX"
  npm install --prefix "$SRE_PREFIX" speech-rule-engine@4.1.3

  # Symlink the sre binary into the venv's bin directory so the daemon
  # can resolve it via Path(sys.executable).parent / "sre" without
  # depending on PATH (systemd unit runs with a minimal environment).
  SRE_BIN="$SRE_PREFIX/node_modules/.bin/sre"
  if [[ ! -x "$SRE_BIN" ]]; then
    echo "ERROR: expected sre binary not found at $SRE_BIN" >&2
    exit 1
  fi
  ln -sf "$SRE_BIN" "$VENV/bin/sre"
  echo "symlinked: $VENV/bin/sre -> $SRE_BIN"
  echo
  echo "Enable via config.toml:"
  echo "  [sre_latex]"
  echo "  enabled = true"
  echo "  domain = \"clearspeak\"    # or \"mathspeak\""
fi

echo
echo "=== install complete ==="
echo "backend: $BACKEND"
if (( WITH_MATH_SPEECH == 1 )); then
  echo "math-speech: speech-rule-engine@4.1.3 installed"
fi
echo
echo "Next:"
echo "  $VENV/bin/lexaloud setup"
echo
echo "Add the venv to your PATH (optional):"
echo "  ln -s $VENV/bin/lexaloud ~/.local/bin/lexaloud"
