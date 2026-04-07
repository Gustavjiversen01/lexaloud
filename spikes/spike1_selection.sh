#!/usr/bin/env bash
#
# Spike 1 — Selection capture matrix.
#
# Goal: find out, empirically, on THIS machine, which of the four clipboard
# read methods return text when something is selected or copied inside each
# app the user actually uses. The output is auto-saved to
# docs/capture-matrix.raw.md so Spike 1 results cannot be lost by forgetting
# to copy the terminal output.
#
# Usage:
#   1. Log in to the target session (Ubuntu on Wayland or Ubuntu on Xorg).
#   2. cd /home/gji/Documents/ReadAloud
#   3. ./spikes/spike1_selection.sh
#   4. For each app, select text when prompted and press Enter. Press 's' to
#      skip apps you don't use.
#
# The script intentionally does not *automate* the selection — manually
# selecting text in each app is the only way to exercise the real GUI path.

set -u -o pipefail  # not -e: we WANT to see non-zero exits from xclip/wl-paste

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
RAW_OUT="$REPO_ROOT/docs/capture-matrix.raw.md"
TIMESTAMP="$(date -Iseconds)"

mkdir -p "$(dirname "$RAW_OUT")"

# If a prior raw file exists, archive it rather than overwriting silently.
if [[ -f "$RAW_OUT" ]]; then
  mv "$RAW_OUT" "${RAW_OUT%.md}.$(date +%Y%m%dT%H%M%S).md"
fi

# tee everything (stdout AND the prompts) into the raw output file via a
# process substitution, so the saved log matches what the user saw.
exec > >(tee -a "$RAW_OUT") 2>&1

APPS=(
  "Firefox (regular text)"
  "Firefox (PDF.js viewer)"
  "Chromium"
  "VS Code (editor)"
  "Obsidian"
  "Okular (PDF)"
  "Zathura (PDF)"
  "Evince (PDF)"
  "LibreOffice Writer"
  "gnome-terminal"
  "Konsole"
  "Kate"
)

TOOLS=(
  "wl-paste --primary --no-newline"
  "wl-paste --no-newline"
  "xclip -o -selection primary"
  "xclip -o -selection clipboard"
)

echo "# Spike 1 — Selection capture matrix (raw log)"
echo
echo "Run timestamp: $TIMESTAMP"
echo "Session type: \`${XDG_SESSION_TYPE:-unknown}\`"
echo "Desktop: \`${XDG_CURRENT_DESKTOP:-unknown}\`"
echo "Display server env: \`DISPLAY=${DISPLAY:-}\`, \`WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-}\`"
echo

echo "## Tool availability"
echo
for tool in wl-paste xclip xsel notify-send; do
  if command -v "$tool" >/dev/null 2>&1; then
    echo "- \`$tool\`: $(command -v "$tool")"
  else
    echo "- \`$tool\`: **NOT INSTALLED**"
  fi
done
echo

run_tool() {
  local cmd="$1"
  local result
  # shellcheck disable=SC2086
  result="$(timeout 2 $cmd 2>/dev/null || true)"
  if [[ -z "$result" ]]; then
    echo "    [empty]"
  else
    local flat
    flat="$(printf '%s' "$result" | tr '\n' ' ' | cut -c1-80)"
    echo "    \"${flat}\""
  fi
}

prompt_user() {
  # Prompt reads must go to the real terminal, not the tee'd stream, and we
  # should NOT record the prompt reply in the saved log.
  local reply
  read -rp "$1" reply < /dev/tty > /dev/tty
  echo "$reply"
}

for app in "${APPS[@]}"; do
  echo
  echo "## $app"
  echo
  reply="$(prompt_user "  Select some text in $app (do NOT press Ctrl+C). Press Enter when ready, or 's' to skip: ")"
  if [[ "$reply" == "s" ]]; then
    echo "  (skipped)"
    continue
  fi
  echo "  ### Reads WITHOUT Ctrl+C (PRIMARY selection)"
  echo
  for tool in "${TOOLS[@]}"; do
    echo "  \`\$ $tool\`"
    run_tool "$tool"
  done
  echo
  prompt_user "  Now press Ctrl+C in $app to copy the selection, then press Enter: " >/dev/null
  echo "  ### Reads AFTER Ctrl+C (CLIPBOARD)"
  echo
  for tool in "${TOOLS[@]}"; do
    echo "  \`\$ $tool\`"
    run_tool "$tool"
  done
done

echo
echo "---"
echo "Spike 1 complete. Saved to \`$RAW_OUT\`."
echo "Review and distill into a summary matrix in \`docs/capture-matrix.md\`."
