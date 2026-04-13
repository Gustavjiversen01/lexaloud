"""Config loader for ~/.config/lexaloud/config.toml.

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
    # Resolve so that a malicious XDG_CONFIG_HOME like '../../etc' can't
    # walk the resulting path outside a canonical location. We only
    # resolve the base, not the full path — the caller is free to append
    # whatever lexaloud/config.toml suffix they want; we just want the
    # base to be a real absolute path.
    root = Path(base).resolve() if base else Path.home() / ".config"
    return root / "lexaloud" / "config.toml"


def runtime_dir() -> Path:
    """Return the XDG_RUNTIME_DIR for the current user.

    Falls back to /run/user/<uid> if $XDG_RUNTIME_DIR is unset, which is
    where systemd-logind normally creates it anyway. Used by
    `socket_path()` to locate the daemon's Unix domain socket parent dir.
    """
    base = os.environ.get("XDG_RUNTIME_DIR")
    if base:
        return Path(base)
    return Path(f"/run/user/{os.getuid()}")


def socket_path() -> Path:
    """Return the absolute path to the daemon's Unix domain socket.

    The systemd user unit template sets `RuntimeDirectory=lexaloud` with
    `RuntimeDirectoryMode=0700`, which causes systemd to create
    `$XDG_RUNTIME_DIR/lexaloud/` with mode 0700 before the daemon starts
    and remove it on service stop. The socket lives at
    `$XDG_RUNTIME_DIR/lexaloud/lexaloud.sock` inside that dir.

    We intentionally do NOT `.resolve()` the path here — `$XDG_RUNTIME_DIR`
    is expected to be `/run/user/<uid>`, a systemd-managed tmpfs that the
    kernel creates per-login, and the daemon asserts the path is under it
    before binding.
    """
    return runtime_dir() / "lexaloud" / "lexaloud.sock"


@dataclass
class CaptureConfig:
    max_bytes: int = 200 * 1024  # 200 KB
    # Per-tool timeout in seconds for the capture subprocess calls.
    subprocess_timeout_s: float = 2.0


@dataclass
class DaemonConfig:
    # host/port are deprecated in v0.1.0. The daemon binds a Unix domain
    # socket at $XDG_RUNTIME_DIR/lexaloud/lexaloud.sock; these fields are
    # kept only for forward compatibility with older config files and are
    # ignored at runtime. Will be removed in v0.3.
    host: str = "127.0.0.1"
    port: int = 5487
    # Bounded ready-queue depth (number of completed sentence chunks between
    # the provider task and the sink consumer).
    ready_queue_depth: int = 3


@dataclass
class AdvancedConfig:
    # Show the floating overlay when speaking. Off by default to keep
    # Lexaloud discreet — enable in config.toml under [advanced].
    overlay: bool = False


@dataclass
class ProviderConfig:
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
    expand_academic_abbreviations: bool = True
    normalize_numbers: bool = True
    normalize_urls: bool = True
    normalize_math_symbols: bool = True
    pdf_cleanup: bool = True


@dataclass
class Config:
    capture: CaptureConfig = field(default_factory=CaptureConfig)
    daemon: DaemonConfig = field(default_factory=DaemonConfig)
    provider: ProviderConfig = field(default_factory=ProviderConfig)
    preprocessor: PreprocessorCfg = field(default_factory=PreprocessorCfg)
    advanced: AdvancedConfig = field(default_factory=AdvancedConfig)


_NESTED_TYPES = (CaptureConfig, DaemonConfig, ProviderConfig, PreprocessorCfg, AdvancedConfig)


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
        # lexaloud` makes the cause obvious, and fall back to defaults.
        log.error(
            "Failed to parse %s: %s. Using default configuration; edit the file to fix the syntax.",
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
    if isinstance(data.get("advanced"), dict):
        _merge(cfg.advanced, data["advanced"])
    return cfg
