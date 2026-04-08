# Installing Lexaloud on Fedora

Tier 2. The maintainer does not CI-test on Fedora, but the installer
auto-detects Fedora via `/etc/os-release` and uses the correct package
names. This guide is for Fedora 41 Workstation.

## 1. System packages

```bash
sudo dnf install \
    python3 \
    python3-pip \
    python3-gobject \
    gtk3 \
    wl-clipboard \
    xclip \
    portaudio \
    libnotify
```

For the tray indicator, you additionally need the Ayatana AppIndicator
support. Fedora's `libayatana-appindicator` is in the `rpmfusion` repo:

```bash
sudo dnf install https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-$(rpm -E %fedora).noarch.rpm
sudo dnf install libayatana-appindicator-gtk3
```

If you'd rather skip the tray, the CLI works without it.

## 2. NVIDIA GPU (optional)

If you have an NVIDIA card and want the CUDA backend:

```bash
# RPM Fusion nonfree has the NVIDIA driver
sudo dnf install akmod-nvidia xorg-x11-drv-nvidia-cuda
# Reboot or modprobe nvidia
```

The installer's `--backend auto` will detect the NVIDIA driver via
`nvidia-smi -L`. On CPU-only systems or if you want to force CPU:

```bash
./scripts/install.sh --backend cpu
```

## 3. Clone and install

```bash
git clone https://github.com/Gustavjiversen01/lexaloud.git
cd lexaloud
./scripts/install.sh
```

See [`ubuntu-debian.md`](ubuntu-debian.md) from step 3 onward for the
`lexaloud setup` flow — it is distro-agnostic.

## Known Fedora differences

- GNOME ships without `ubuntu-appindicators` by default. The tray
  requires the AppIndicator support extension from extensions.gnome.org.
- SELinux does not interfere with `systemd --user` services under
  normal targeted policy.
- Fedora 41 ships Python 3.13, which pysbd and phonemizer-fork may not
  yet have wheels for; the CPU install path should still work since pip
  will build from source if needed.

## Reporting issues

Please include the full output of `lexaloud bug-report` when filing a
Fedora-specific issue so the maintainer can add the distro to the CI
matrix.
