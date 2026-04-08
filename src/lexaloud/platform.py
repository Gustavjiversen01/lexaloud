"""Platform detection helpers for distro/desktop/GPU/site-packages path.

These are intentionally lightweight: no external dependencies, no
subprocess calls beyond `nvidia-smi` (which is optional and cleanly
handles its absence). Each helper returns a small dataclass or list
of paths that the rest of the package can use to adapt behavior
without hardcoding distro-specific assumptions.

Used by:
- `indicator.py` and `gui_control.py` for the system-site-packages `gi`
  import shim (instead of the Debian-only hardcode).
- `scripts/install.sh` (via `lexaloud --version`'s distro branching —
  future v0.2 work).
- `bug_report.py` for `lexaloud bug-report` diagnostics.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DistroInfo:
    """Result of `detect_distro()`.

    `id` is the lowercase ID from /etc/os-release (e.g. "ubuntu", "debian",
    "fedora", "arch", "manjaro", "linuxmint", "pop").

    `like` is the ID_LIKE list from /etc/os-release, also lowercase. For
    example, Linux Mint has `id="linuxmint"` and `like=["ubuntu", "debian"]`,
    letting distro detection match on the broader family.

    `version_id` is whatever /etc/os-release reports (e.g. "24.04", "41",
    "rolling") or empty string if absent.

    `pretty_name` is the human-readable name for display.
    """

    id: str
    like: tuple[str, ...]
    version_id: str
    pretty_name: str

    def matches(self, *needles: str) -> bool:
        """True if id or any like entry matches one of the given needles."""
        targets = {n.lower() for n in needles}
        if self.id in targets:
            return True
        return bool(targets.intersection(self.like))


@dataclass(frozen=True)
class DesktopInfo:
    """Result of `detect_desktop()`."""

    name: str              # e.g. "GNOME", "KDE", "XFCE", "sway", "unknown"
    session_type: str      # "wayland" | "x11" | "tty" | "unknown"

    @property
    def is_wayland(self) -> bool:
        return self.session_type == "wayland"

    @property
    def is_x11(self) -> bool:
        return self.session_type == "x11"

    @property
    def is_gnome(self) -> bool:
        return "GNOME" in self.name.upper()

    @property
    def is_kde(self) -> bool:
        name_upper = self.name.upper()
        return "KDE" in name_upper or "PLASMA" in name_upper


@dataclass(frozen=True)
class GpuInfo:
    """Result of `detect_gpu()`."""

    vendor: str   # "nvidia" | "amd" | "intel" | "none"
    device: str   # free-form device name, or "" if unknown/none


def detect_distro() -> DistroInfo:
    """Parse /etc/os-release into a DistroInfo.

    Falls back to an "unknown" record if the file is missing or malformed
    — this should only happen on containers with a minimal rootfs.
    """
    path = Path("/etc/os-release")
    if not path.is_file():
        return DistroInfo(id="unknown", like=(), version_id="", pretty_name="unknown")

    fields: dict[str, str] = {}
    try:
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            # /etc/os-release values are usually quoted with "..."
            value = value.strip().strip('"').strip("'")
            fields[key.strip()] = value
    except OSError:
        return DistroInfo(id="unknown", like=(), version_id="", pretty_name="unknown")

    like_raw = fields.get("ID_LIKE", "")
    like = tuple(part.strip().lower() for part in like_raw.split() if part.strip())

    return DistroInfo(
        id=fields.get("ID", "unknown").lower(),
        like=like,
        version_id=fields.get("VERSION_ID", ""),
        pretty_name=fields.get("PRETTY_NAME", fields.get("NAME", "unknown")),
    )


def detect_desktop() -> DesktopInfo:
    """Detect desktop environment + session type from XDG environment.

    `XDG_CURRENT_DESKTOP` can contain multiple entries separated by colons
    (e.g. "ubuntu:GNOME"); we collapse to the first non-empty one and
    normalize to uppercase-friendly form.
    """
    current = (
        os.environ.get("XDG_CURRENT_DESKTOP")
        or os.environ.get("DESKTOP_SESSION")
        or "unknown"
    )
    # XDG_CURRENT_DESKTOP may be colon-separated; prefer a well-known DE name.
    parts = [p for p in current.split(":") if p]
    preferred = ""
    for candidate in parts:
        upper = candidate.upper()
        if any(known in upper for known in ("GNOME", "KDE", "PLASMA", "XFCE", "CINNAMON", "MATE", "LXQT", "LXDE", "SWAY", "HYPRLAND", "I3")):
            preferred = candidate
            break
    name = preferred or (parts[0] if parts else "unknown")

    session_type = (os.environ.get("XDG_SESSION_TYPE") or "").lower() or "unknown"
    if session_type not in ("wayland", "x11", "tty", "unknown"):
        session_type = "unknown"

    return DesktopInfo(name=name, session_type=session_type)


def detect_gpu() -> GpuInfo:
    """Detect the primary GPU vendor.

    Tries `nvidia-smi --query-gpu=name --format=csv,noheader` first; if
    that fails, falls back to parsing `/proc/bus/pci/devices` for vendor
    IDs (0x10de = NVIDIA, 0x1002 = AMD, 0x8086 = Intel). Returns
    `GpuInfo(vendor="none", device="")` if nothing useful is found.

    Short timeouts keep this safe to call during `bug-report` even on
    broken systems.
    """
    # 1. nvidia-smi is authoritative when present.
    if shutil.which("nvidia-smi"):
        try:
            r = subprocess.run(
                ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if r.returncode == 0 and r.stdout.strip():
                device = r.stdout.splitlines()[0].strip()
                return GpuInfo(vendor="nvidia", device=device)
        except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError):
            pass

    # 2. Fall back to /proc/bus/pci/devices vendor ID sniffing.
    try:
        data = Path("/proc/bus/pci/devices").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return GpuInfo(vendor="none", device="")

    vendor_ids = {"10de": "nvidia", "1002": "amd", "8086": "intel"}
    for line in data.splitlines():
        fields = line.split()
        if len(fields) < 2:
            continue
        # Column 2 is "vendorID_deviceID" packed as 8 hex chars.
        vendor_device = fields[1]
        if len(vendor_device) < 8:
            continue
        vid = vendor_device[:4].lower()
        if vid in vendor_ids:
            return GpuInfo(vendor=vendor_ids[vid], device="")

    return GpuInfo(vendor="none", device="")


def system_site_packages_candidates() -> list[Path]:
    """Return candidate paths for the system-wide python site-packages dir.

    Different distros install python3-gi (and other C-extension modules)
    into different site-packages directories:
        - Debian/Ubuntu:  /usr/lib/python3/dist-packages
        - Fedora/RHEL:    /usr/lib64/python3.X/site-packages
        - Arch/Manjaro:   /usr/lib/python3.X/site-packages
        - openSUSE:       /usr/lib64/python3.X/site-packages

    Returns a list of *existing* paths in preference order. The
    indicator and control-window modules iterate over this list and
    append the first existing entry to `sys.path` to make the system
    `gi` module importable from inside the project venv.
    """
    ver = sys.version_info
    candidates: list[Path] = [
        # Debian/Ubuntu convention — version-agnostic
        Path("/usr/lib/python3/dist-packages"),
        # Fedora/RHEL/openSUSE 64-bit convention
        Path(f"/usr/lib64/python{ver.major}.{ver.minor}/site-packages"),
        # Arch/Manjaro convention
        Path(f"/usr/lib/python{ver.major}.{ver.minor}/site-packages"),
    ]
    return [p for p in candidates if p.is_dir()]
