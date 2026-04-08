# HTTP API reference

The Lexaloud daemon exposes a small HTTP API over a Unix domain socket
at `$XDG_RUNTIME_DIR/lexaloud/lexaloud.sock` (mode 0700 on the parent
dir via systemd's `RuntimeDirectory=`). The CLI and the tray indicator
both talk to this API; there is no authentication because the socket
permissions restrict access to the owner user's processes.

To experiment by hand, use `curl --unix-socket`:

```bash
SOCK="$XDG_RUNTIME_DIR/lexaloud/lexaloud.sock"
curl --unix-socket "$SOCK" http://lexaloud/state
```

## Endpoints

### `GET /healthz`

Liveness probe. Always returns 200.

```json
{"status": "ok"}
```

### `GET /state`

Returns the player's current state.

```json
{
  "state": "idle",
  "current_sentence": null,
  "pending_count": 0,
  "ready_count": 0,
  "provider_name": "kokoro",
  "session_providers": ["CUDAExecutionProvider", "CPUExecutionProvider"],
  "last_error": null
}
```

Fields:

| Field | Type | Description |
|-------|------|-------------|
| `state` | `"idle" \| "warming" \| "speaking" \| "paused"` | Player state |
| `current_sentence` | `string \| null` | Sentence currently being written to the audio sink |
| `pending_count` | `int` | Sentences waiting to be synthesized |
| `ready_count` | `int` | Completed sentence chunks in the bounded ready queue |
| `provider_name` | `string` | Currently-active TTS provider (always `"kokoro"` in v0.1.0) |
| `session_providers` | `string[]` | ORT execution providers the session was built with |
| `last_error` | `string \| null` | Human-readable error from the last failed synthesis attempt |

### `POST /speak`

Submit text for speaking.

Request body:

```json
{"text": "The first sentence. The second sentence.", "mode": "replace"}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `text` | `string` | yes | Text to speak. Must be non-empty (`min_length=1`). |
| `mode` | `"replace" \| "append"` | no | `"replace"` (default) clears the pending queue; `"append"` adds to it if the player is already speaking. |

Response: the same `StateResponse` shape as `GET /state`, reflecting
the state after the command was processed.

Errors:

| Status | Condition |
|--------|-----------|
| `400` | `text` contains a null byte, or a post-preprocess sentence exceeds `MAX_SENTENCE_CHARS=4096` |
| `413` | `text` exceeds `capture.max_bytes` (default 200 KB) |
| `422` | Pydantic validation error (e.g., `text` is empty) |

### `POST /pause`

Pause playback at the next sub-chunk boundary (~100 ms latency).

Response: `StateResponse` with `state="paused"` (or unchanged if the
player was not speaking).

### `POST /resume`

Resume paused playback.

Response: `StateResponse` with `state="speaking"` (or unchanged if
the player was not paused).

### `POST /toggle`

Flip between speaking and paused. No-op when idle or warming.

### `POST /stop`

Stop the current job, flush the audio sink, drop all pending sentences.

Response: `StateResponse` with `state="idle"`.

### `POST /skip`

Skip the currently-playing sentence. Pre-fetched ready chunks are
preserved so the next sentence plays immediately.

### `POST /back`

Rewind to the previously-finished sentence (or restart the current one
if no previous sentence exists).

## Content-Length cap

The `/speak` route is protected by a middleware-level `Content-Length`
cap at `capture.max_bytes + 4096` bytes (the envelope allowance covers
JSON keys, quotes, and escapes). Clients that send more than this see
a 413 before the body is parsed.

## State transitions

```
idle ──/speak──> speaking
idle <──sentinel── speaking (job complete)

speaking ──/pause──> paused
paused ──/resume──> speaking

speaking ──/stop──> idle
paused   ──/stop──> idle

speaking/paused ──/skip──> speaking (or idle if last sentence skipped)
speaking/paused ──/back──> speaking (rewinds one sentence)

(warming is entered during daemon lifespan startup and exits to idle
when Kokoro's first create() call completes.)
```
