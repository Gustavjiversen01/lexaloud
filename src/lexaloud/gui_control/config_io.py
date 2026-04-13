"""Config-file read/write helpers for the control window."""

from __future__ import annotations

import logging
import tomllib

from ..config import config_path

log = logging.getLogger(__name__)


def _load_config_dict() -> dict:
    p = config_path()
    if not p.exists():
        return {}
    try:
        with p.open("rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        log.error("Config file %s has a syntax error: %s", p, e)
        return {}
    except OSError as e:
        log.error("Could not read %s: %s", p, e)
        return {}


def _toml_escape(s: str) -> str:
    """Escape a Python str for TOML basic-string syntax.

    Handles the full control-character set that TOML requires escaped:
    backslash, double-quote, \\b, \\t, \\n, \\f, \\r, plus any other
    code point in U+0000..U+001F or U+007F as a \\uXXXX escape.
    """
    out: list[str] = []
    for ch in s:
        cp = ord(ch)
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\b":
            out.append("\\b")
        elif ch == "\t":
            out.append("\\t")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\f":
            out.append("\\f")
        elif ch == "\r":
            out.append("\\r")
        elif cp < 0x20 or cp == 0x7F:
            out.append(f"\\u{cp:04X}")
        else:
            out.append(ch)
    return "".join(out)


def _save_config_dict(data: dict) -> None:
    """Serialize ``data`` back to config.toml.

    Only scalars (str, bool, int, float) are preserved. Arrays and nested
    tables are dropped with a WARNING log entry.
    """
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for section, fields in data.items():
        if not isinstance(fields, dict):
            continue
        section_lines: list[str] = []
        for key, value in fields.items():
            if isinstance(value, bool):
                section_lines.append(f"{key} = {'true' if value else 'false'}")
            elif isinstance(value, (int, float)):
                section_lines.append(f"{key} = {value}")
            elif isinstance(value, str):
                section_lines.append(f'{key} = "{_toml_escape(value)}"')
            else:
                log.warning(
                    "Dropping config key [%s].%s with unsupported type %s during GUI save",
                    section,
                    key,
                    type(value).__name__,
                )
        if section_lines:
            lines.append(f"[{section}]")
            lines.extend(section_lines)
            lines.append("")
    p.write_text("\n".join(lines))
