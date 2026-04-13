# Configuration

Lexaloud reads `~/.config/lexaloud/config.toml` (or
`$XDG_CONFIG_HOME/lexaloud/config.toml`) at daemon startup. An example
file lives at [`src/lexaloud/templates/config.example.toml`](../src/lexaloud/templates/config.example.toml);
copy it and edit to taste. The daemon must be restarted after any
config change.

```bash
cp src/lexaloud/templates/config.example.toml ~/.config/lexaloud/config.toml
# edit ~/.config/lexaloud/config.toml
systemctl --user restart lexaloud.service
```

## Sections

### `[capture]`

| Key | Default | Description |
|-----|---------|-------------|
| `max_bytes` | `204800` | Maximum selection size in bytes. Larger selections are truncated on a UTF-8 boundary. |
| `subprocess_timeout_s` | `2.0` | Timeout for `wl-paste`/`xclip`/`xsel` subprocess calls. |

### `[daemon]`

| Key | Default | Description |
|-----|---------|-------------|
| `host` | `"127.0.0.1"` | **Deprecated.** The daemon binds a Unix domain socket at `$XDG_RUNTIME_DIR/lexaloud/lexaloud.sock`. Kept for forward compat; ignored at runtime. Will be removed in v0.3. |
| `port` | `5487` | **Deprecated.** Same as `host`. Will be removed in v0.3. |
| `ready_queue_depth` | `3` | Max completed sentence chunks buffered between the provider and the audio sink. Bounds memory during pause or slow playback. Increase to 5-10 if you hear audible gaps between sentences on a slower CPU. |

### `[provider]`

| Key | Default | Description |
|-----|---------|-------------|
| `voice` | `"af_heart"` | Any Kokoro v1.0 voice. Curated subset in the control window; full list at the Kokoro-82M Hugging Face model card. |
| `lang` | `"en-us"` | Phonemizer language code. Only `en-us` and `en-gb` are tested. |
| `speed` | `1.0` | Playback speed multiplier. Safe range for dense academic prose is 0.85-1.3. The control window slider enforces 0.5-2.0. |

### `[preprocessor]`

| Key | Default | Description |
|-----|---------|-------------|
| `strip_numeric_bracket_citations` | `true` | Strip `[3]` or `[1-4]` style citations. |
| `strip_parenthetical_citations` | `false` | Strip `(Smith 2023)` style citations. Off by default because it can over-match ordinary parentheticals. |
| `expand_latin_abbreviations` | `true` | Expand `i.e.`, `e.g.`, `etc.` to full forms. |
| `expand_academic_abbreviations` | `true` | Expand `Fig.`, `Eq.`, `Sec.`, `Thm.`, `w.r.t.`, `i.i.d.`, etc. to full forms. Helps pysbd sentence splitting and TTS pronunciation. |
| `normalize_numbers` | `true` | Convert numbers to spoken English: ordinals (`1st` -> first), cardinals with commas (`1,234`), decimals, percentages, currency, years. Numbers after reference words (Figure 3, Section 2.1) are left as digits. IP addresses, version strings, and phone numbers are protected. |
| `pdf_cleanup` | `true` | Handle line-break hyphenation and other PDF paste artifacts. |

### `[advanced]`

| Key | Default | Description |
|-----|---------|-------------|
| `overlay` | `false` | Show the floating overlay when speaking. The overlay is an always-on-top sentence caption bar. Enable via `overlay = true` under `[advanced]` or from the control window's Settings tab. On wlroots compositors and KWin, the overlay uses `gtk-layer-shell` for proper stacking; on X11 and GNOME Wayland it falls back to a `NOTIFICATION` type hint. |

## Voice selection

The control window (`lexaloud-control` or the tray menu → Control
window…) offers a curated voice dropdown. For the full Kokoro voice
catalog, edit `voice` directly in `config.toml` — any string the
installed voices pack recognizes will work.

## Speed guidance

| Speed | Experience |
|-------|------------|
| `0.5` – `0.84` | Slow. Can feel dragged. Good for non-native listeners or very dense material. |
| `0.85` – `1.00` | Natural. |
| `1.00` – `1.30` | Faster than natural. Safe range for reading-along when you're already familiar with the domain. |
| `1.30` – `1.50` | Risky on unfamiliar material. Comprehension drops. |
| `> 1.50` | Very risky. Useful for skimming, not reading. |

## Hot-reloading

The daemon does not hot-reload `config.toml`. Restart via:

```bash
systemctl --user restart lexaloud.service
```

The control window has an "Apply & restart daemon" button that does the
restart for you.
