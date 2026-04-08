"""Detect the runtime session (Wayland vs X11, desktop environment, available
clipboard-capture tools). Used by the CLI selection module and the setup
command to tailor instructions.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass


@dataclass
class SessionInfo:
    session_type: str  # "wayland" | "x11" | "unknown"
    desktop: str  # e.g. "GNOME", "KDE", "sway"
    wl_paste: str | None
    xclip: str | None

    @property
    def is_wayland(self) -> bool:
        return self.session_type == "wayland"

    @property
    def is_x11(self) -> bool:
        return self.session_type == "x11"


def detect_session() -> SessionInfo:
    session_type = (os.environ.get("XDG_SESSION_TYPE") or "").lower() or "unknown"
    if session_type not in ("wayland", "x11", "unknown"):
        session_type = "unknown"

    desktop = (
        os.environ.get("XDG_CURRENT_DESKTOP")
        or os.environ.get("DESKTOP_SESSION")
        or "unknown"
    )

    return SessionInfo(
        session_type=session_type,
        desktop=desktop,
        wl_paste=shutil.which("wl-paste"),
        xclip=shutil.which("xclip"),
    )
