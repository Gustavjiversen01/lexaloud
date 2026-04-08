"""Tests for lexaloud.platform — distro / desktop / GPU / site-packages detection."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from lexaloud.platform import (
    DesktopInfo,
    DistroInfo,
    GpuInfo,
    detect_desktop,
    detect_distro,
    detect_gpu,
    system_site_packages_candidates,
)


# ---------- detect_distro ----------


def test_detect_distro_parses_ubuntu_24_04(tmp_path: Path, monkeypatch):
    os_release = tmp_path / "os-release"
    os_release.write_text(
        """NAME="Ubuntu"
VERSION="24.04.1 LTS (Noble Numbat)"
ID=ubuntu
ID_LIKE=debian
PRETTY_NAME="Ubuntu 24.04.1 LTS"
VERSION_ID="24.04"
"""
    )
    with patch("lexaloud.platform.Path") as mock_path:
        mock_path.return_value = os_release
        info = detect_distro()
    assert info.id == "ubuntu"
    assert info.like == ("debian",)
    assert info.version_id == "24.04"
    assert "Ubuntu" in info.pretty_name
    assert info.matches("ubuntu")
    assert info.matches("debian")
    assert not info.matches("fedora")


def test_detect_distro_parses_fedora(tmp_path: Path):
    os_release = tmp_path / "os-release"
    os_release.write_text(
        """NAME="Fedora Linux"
VERSION="41 (Workstation Edition)"
ID=fedora
VERSION_ID=41
PRETTY_NAME="Fedora Linux 41 (Workstation Edition)"
"""
    )
    with patch("lexaloud.platform.Path") as mock_path:
        mock_path.return_value = os_release
        info = detect_distro()
    assert info.id == "fedora"
    assert info.like == ()
    assert info.version_id == "41"


def test_detect_distro_matches_via_like():
    # Linux Mint reports id=linuxmint but likes ubuntu + debian
    info = DistroInfo(
        id="linuxmint",
        like=("ubuntu", "debian"),
        version_id="21",
        pretty_name="Linux Mint 21",
    )
    assert info.matches("ubuntu")
    assert info.matches("debian")
    assert info.matches("linuxmint")
    assert not info.matches("fedora", "arch")


def test_detect_distro_missing_file_returns_unknown(tmp_path: Path):
    with patch("lexaloud.platform.Path") as mock_path:
        mock_path.return_value = tmp_path / "nonexistent"
        info = detect_distro()
    assert info.id == "unknown"
    assert info.pretty_name == "unknown"


# ---------- detect_desktop ----------


def test_detect_desktop_gnome_wayland(monkeypatch):
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "ubuntu:GNOME")
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    info = detect_desktop()
    assert info.is_wayland
    assert info.is_gnome
    assert not info.is_kde


def test_detect_desktop_kde_x11(monkeypatch):
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    info = detect_desktop()
    assert info.is_x11
    assert info.is_kde
    assert not info.is_gnome


def test_detect_desktop_unknown_when_empty(monkeypatch):
    monkeypatch.delenv("XDG_CURRENT_DESKTOP", raising=False)
    monkeypatch.delenv("DESKTOP_SESSION", raising=False)
    monkeypatch.delenv("XDG_SESSION_TYPE", raising=False)
    info = detect_desktop()
    assert info.name == "unknown"
    assert info.session_type == "unknown"
    assert not info.is_wayland
    assert not info.is_x11


# ---------- detect_gpu ----------


def test_detect_gpu_nvidia_smi_succeeds():
    fake_run = type("_R", (), {"returncode": 0, "stdout": "NVIDIA GeForce RTX 5080\n"})()
    with (
        patch("lexaloud.platform.shutil.which", return_value="/usr/bin/nvidia-smi"),
        patch("lexaloud.platform.subprocess.run", return_value=fake_run),
    ):
        info = detect_gpu()
    assert info.vendor == "nvidia"
    assert "RTX 5080" in info.device


def test_detect_gpu_none_when_no_drivers():
    with (
        patch("lexaloud.platform.shutil.which", return_value=None),
        patch(
            "lexaloud.platform.Path.read_text",
            side_effect=OSError("no proc bus pci"),
        ),
    ):
        info = detect_gpu()
    assert info.vendor == "none"
    assert info.device == ""


# ---------- system_site_packages_candidates ----------


def test_system_site_packages_returns_only_existing(tmp_path: Path):
    existing = tmp_path / "usr" / "lib" / "python3" / "dist-packages"
    existing.mkdir(parents=True)
    # Monkeypatch Path.is_dir to return True only for our fake path
    original_is_dir = Path.is_dir

    def fake_is_dir(self: Path) -> bool:
        return self == existing

    with patch("lexaloud.platform.Path") as mock_path_cls:
        def make_path(value: str) -> Path:
            p = Path(str(value))
            # Replace the Debian path candidate with our tmp_path one
            if str(value) == "/usr/lib/python3/dist-packages":
                p = existing
            return p

        mock_path_cls.side_effect = make_path
        # Use the real Path.is_dir
        with patch.object(Path, "is_dir", fake_is_dir):
            candidates = system_site_packages_candidates()

    assert existing in candidates
