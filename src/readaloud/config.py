"""Config loader for ~/.config/readaloud/config.toml.

Defaults are returned when the file does not exist. Unknown top-level keys
are ignored so forward-compatible config additions don't crash old daemons.
"""

from __future__ import annotations

import logging
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)


def config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / "readaloud" / "config.toml"


@dataclass
class CaptureConfig:
    max_bytes: int = 200 * 1024  # 200 KB
    # Per-tool timeout in seconds for the capture subprocess calls.
    subprocess_timeout_s: float = 2.0
    notify_timeout_s: float = 1.0


@dataclass
class DaemonConfig:
    host: str = "127.0.0.1"
    port: int = 5487
    # Bounded ready-queue depth (number of completed sentence chunks between
    # the provider task and the sink consumer).
    ready_queue_depth: int = 3
    # On startup, synthesize this string once to absorb cold-start cost.
    warmup_text: str = "Ready."


@dataclass
class ProviderConfig:
    name: str = "kokoro"
    voice: str = "af_heart"
    lang: str = "en-us"
    # Playback speed multiplier. 1.0 = normal; >1 faster; <1 slower.
    # Kokoro natively supports this; it's passed to Kokoro.create(speed=...).
    # Safe range for dense academic prose is ~0.85-1.3 per the design plan;
    # values outside that are tolerated but may hurt comprehension.
    speed: float = 1.0


@dataclass
class PreprocessorCfg:
    strip_numeric_bracket_citations: bool = True
    strip_parenthetical_citations: bool = False
    expand_latin_abbreviations: bool = True
    pdf_cleanup: bool = True


@dataclass
class Config:
    capture: CaptureConfig = field(default_factory=CaptureConfig)
    daemon: DaemonConfig = field(default_factory=DaemonConfig)
    provider: ProviderConfig = field(default_factory=ProviderConfig)
    preprocessor: PreprocessorCfg = field(default_factory=PreprocessorCfg)


_NESTED_TYPES = (CaptureConfig, DaemonConfig, ProviderConfig, PreprocessorCfg)


def _merge(dc, data: dict) -> None:
    """Copy scalar fields from a dict into a dataclass instance.

    Ignores unknown keys (forward-compat). Ignores nested-dataclass fields
    so a scalar override can't accidentally clobber a sub-config — those
    are dispatched by `load_config` from their own TOML section instead.
    """
    for key, value in data.items():
        if not hasattr(dc, key):
            continue
        current = getattr(dc, key)
        if isinstance(current, _NESTED_TYPES):
            continue
        setattr(dc, key, value)


def load_config(path: Path | None = None) -> Config:
    cfg = Config()
    p = path or config_path()
    if not p.exists():
        return cfg
    try:
        with p.open("rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        # A malformed config.toml MUST NOT crash the daemon in a systemd
        # restart loop. Log the error loudly so `journalctl --user -u
        # readaloud` makes the cause obvious, and fall back to defaults.
        log.error(
            "Failed to parse %s: %s. Using default configuration; edit the "
            "file to fix the syntax.",
            p,
            e,
        )
        return cfg
    except OSError as e:
        log.error("Could not read %s: %s. Using default configuration.", p, e)
        return cfg
    if isinstance(data.get("capture"), dict):
        _merge(cfg.capture, data["capture"])
    if isinstance(data.get("daemon"), dict):
        _merge(cfg.daemon, data["daemon"])
    if isinstance(data.get("provider"), dict):
        _merge(cfg.provider, data["provider"])
    if isinstance(data.get("preprocessor"), dict):
        _merge(cfg.preprocessor, data["preprocessor"])
    return cfg
