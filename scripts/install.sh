#!/usr/bin/env bash
#
# ReadAloud installer — Phase A bootstrap.
#
# Creates a dedicated venv at ~/.local/share/readaloud/venv/, installs the
# pinned dependency set (requirements-lock.txt from Spike 0), then the
# readaloud package itself.
#
# After this script succeeds:
#
#   ~/.local/share/readaloud/venv/bin/readaloud setup
#
# will finish the configuration (download models, render systemd unit,
# print hotkey binding walkthrough).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DEFAULT="$HOME/.local/share/readaloud/venv"
VENV="${READALOUD_VENV:-$VENV_DEFAULT}"

echo "=== ReadAloud installer ==="
echo "repo root: $REPO_ROOT"
echo "target venv: $VENV"
echo

# --- system dependency check --------------------------------------------

missing=()

if ! command -v python3 >/dev/null 2>&1; then
  missing+=("python3")
fi
# python3-venv is the Debian/Ubuntu package that provides the `venv` module.
if ! python3 -c 'import venv' 2>/dev/null; then
  missing+=("python3-venv")
fi
if ! command -v wl-paste >/dev/null 2>&1; then
  missing+=("wl-clipboard")
fi
if ! command -v xclip >/dev/null 2>&1; then
  missing+=("xclip")
fi
if ! ldconfig -p | grep -q libportaudio.so.2; then
  missing+=("libportaudio2")
fi
if ! command -v notify-send >/dev/null 2>&1; then
  missing+=("libnotify-bin")
fi

# dedupe
if (( ${#missing[@]} > 0 )); then
  mapfile -t missing < <(printf "%s\n" "${missing[@]}" | awk '!seen[$0]++')
  echo "Missing system packages:" >&2
  for p in "${missing[@]}"; do echo "  - $p" >&2; done
  echo >&2
  echo "Install them with:" >&2
  echo "  sudo apt install ${missing[*]}" >&2
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
  # Refuse to install into a venv that already has the broken dual-install
  # state Spike 0 flagged.
  if env -u PYTHONPATH "$VENV/bin/pip" show onnxruntime >/dev/null 2>&1 \
       && env -u PYTHONPATH "$VENV/bin/pip" show onnxruntime-gpu >/dev/null 2>&1; then
    cat >&2 <<BROKEN
ERROR: both 'onnxruntime' and 'onnxruntime-gpu' are installed in $VENV.
       This is the broken coexistence state Spike 0 flagged:
       - imports will silently shadow CUDAExecutionProvider to CPU
       - `pip uninstall onnxruntime` will break BOTH packages.

Fix: recreate the venv from scratch.

   rm -rf "$VENV"
   $0
BROKEN
    exit 1
  fi
  # Also refuse if only the CPU package is present — the lockfile install
  # below will bring onnxruntime-gpu in alongside it, producing the broken
  # state.
  if env -u PYTHONPATH "$VENV/bin/pip" show onnxruntime >/dev/null 2>&1; then
    cat >&2 <<STALE_CPU
ERROR: stale 'onnxruntime' (CPU) package detected in $VENV.
       Installing the lockfile on top would create the broken dual-install
       state Spike 0 flagged.

Fix: recreate the venv from scratch.

   rm -rf "$VENV"
   $0
STALE_CPU
    exit 1
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

LOCK="$REPO_ROOT/requirements-lock.txt"
if [[ ! -f "$LOCK" ]]; then
  echo "requirements-lock.txt not found at $LOCK" >&2
  exit 1
fi

echo "installing pinned runtime dependencies from requirements-lock.txt"
# Install --no-deps kokoro-onnx separately so pip doesn't re-resolve it and
# pull in the broken [gpu]-extra coexistence state Spike 0 flagged.
KOKORO_PIN="$(grep -E '^kokoro-onnx==' "$LOCK" || true)"
if [[ -z "$KOKORO_PIN" ]]; then
  echo "kokoro-onnx pin missing from requirements-lock.txt" >&2
  exit 1
fi

# Stage the filtered lockfile before registering the trap so that a signal
# arriving between mktemp and trap can't leak the file.
LOCK_NO_KOKORO=""
trap '[[ -n "${LOCK_NO_KOKORO:-}" ]] && rm -f "$LOCK_NO_KOKORO"' EXIT
LOCK_NO_KOKORO="$(mktemp)"
grep -v -E '^kokoro-onnx==' "$LOCK" > "$LOCK_NO_KOKORO"

$PIP install -r "$LOCK_NO_KOKORO"
$PIP install --no-deps "$KOKORO_PIN"

# --- install the readaloud package --------------------------------------

echo "installing the readaloud package (editable)"
$PIP install --no-deps -e "$REPO_ROOT"

# --- smoke check: onnxruntime-gpu is the single ORT distribution --------

if $PIP show onnxruntime >/dev/null 2>&1; then
  echo "ERROR: 'onnxruntime' (CPU) was pulled into the venv somehow; aborting." >&2
  exit 1
fi

echo
echo "=== install complete ==="
echo
echo "Next:"
echo "  $VENV/bin/readaloud setup"
echo
echo "Add the venv to your PATH (optional):"
echo "  ln -s $VENV/bin/readaloud ~/.local/bin/readaloud"
