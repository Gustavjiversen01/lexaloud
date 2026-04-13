#!/usr/bin/env bash
#
# Record a ~15-second screen capture and convert it to docs/demo.gif.
#
# Workflow:
#   1. Run this script.
#   2. When prompted, trigger a Lexaloud speak (e.g., select text + hotkey).
#   3. The script stops recording after DURATION seconds.
#   4. ffmpeg converts the recording to an optimised GIF.
#
# Prerequisites:
#   - wf-recorder (Wayland) or ffmpeg + x11grab (X11)
#   - ffmpeg (for GIF conversion in both cases)
#
# Usage:
#   ./scripts/record-demo.sh              # 15-second recording
#   ./scripts/record-demo.sh --duration 20

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="$REPO_ROOT/docs"
OUT_GIF="$OUT_DIR/demo.gif"
DURATION=15
WIDTH=800
FPS=15

# --- parse arguments -------------------------------------------------------

while (( "$#" )); do
  case "$1" in
    --duration)  DURATION="$2"; shift 2 ;;
    --duration=*) DURATION="${1#*=}"; shift ;;
    -h|--help)   sed -n '3,17p' "$0"; exit 0 ;;
    *)           echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

# --- tool check ------------------------------------------------------------

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ERROR: ffmpeg is required. Install with: sudo apt install ffmpeg" >&2
  exit 1
fi

SESSION_TYPE="${XDG_SESSION_TYPE:-x11}"
RECORDER=""

if [[ "$SESSION_TYPE" == "wayland" ]]; then
  if command -v wf-recorder >/dev/null 2>&1; then
    RECORDER="wf-recorder"
  else
    echo "ERROR: wf-recorder is required on Wayland." >&2
    echo "Install with: sudo apt install wf-recorder" >&2
    exit 1
  fi
else
  # X11 — use ffmpeg x11grab directly
  RECORDER="x11grab"
fi

mkdir -p "$OUT_DIR"

TMP_VIDEO="$(mktemp --suffix=.mp4)"
trap 'rm -f "$TMP_VIDEO"' EXIT

echo "=== Lexaloud demo recorder ==="
echo "session type: $SESSION_TYPE"
echo "recorder: $RECORDER"
echo "duration: ${DURATION}s"
echo "output: $OUT_GIF"
echo
echo "Press Enter to start recording, then trigger a Lexaloud speak."
read -r

echo "Recording for ${DURATION}s..."

if [[ "$RECORDER" == "wf-recorder" ]]; then
  timeout "$DURATION" wf-recorder -f "$TMP_VIDEO" -c libx264 \
    --codec-param crf=23 2>/dev/null || true
else
  # x11grab: capture the full screen
  SCREEN_RES="$(xdpyinfo 2>/dev/null | awk '/dimensions:/{print $2}' || echo "1920x1080")"
  timeout "$DURATION" ffmpeg -y -f x11grab -framerate "$FPS" \
    -video_size "$SCREEN_RES" -i "$DISPLAY" \
    -c:v libx264 -crf 23 "$TMP_VIDEO" 2>/dev/null || true
fi

echo "Recording complete. Converting to GIF..."

# Two-pass palette-optimised GIF for small file size.
PALETTE="$(mktemp --suffix=.png)"
trap 'rm -f "$TMP_VIDEO" "$PALETTE"' EXIT

FILTERS="fps=$FPS,scale=$WIDTH:-1:flags=lanczos"

ffmpeg -y -i "$TMP_VIDEO" -vf "$FILTERS,palettegen=stats_mode=diff" "$PALETTE" 2>/dev/null
ffmpeg -y -i "$TMP_VIDEO" -i "$PALETTE" \
  -lavfi "$FILTERS [x]; [x][1:v] paletteuse=dither=bayer:bayer_scale=3" \
  "$OUT_GIF" 2>/dev/null

SIZE="$(du -h "$OUT_GIF" | cut -f1)"
echo
echo "=== Done ==="
echo "GIF saved to: $OUT_GIF ($SIZE)"
echo
echo "To use in README.md, uncomment the demo GIF line:"
echo '  ![demo](docs/demo.gif)'
