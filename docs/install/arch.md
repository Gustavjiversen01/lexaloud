# Installing Lexaloud on Arch / Manjaro

Tier 2. The maintainer does not CI-test on Arch, but the installer
auto-detects Arch via `/etc/os-release` and uses the correct package
names. This guide is for Arch rolling as of early 2026.

## 1. System packages

```bash
sudo pacman -S \
    python \
    python-gobject \
    gtk3 \
    wl-clipboard \
    xclip \
    portaudio \
    libnotify
```

For the tray indicator, install `libayatana-appindicator` from the
official repos:

```bash
sudo pacman -S libayatana-appindicator
```

## 2. NVIDIA GPU (optional)

```bash
sudo pacman -S nvidia nvidia-utils
# Reboot
```

The installer's `--backend auto` detects `nvidia-smi` and picks
`cuda12`. On CPU-only machines or to force CPU:

```bash
./scripts/install.sh --backend cpu
```

## 3. Clone and install

```bash
git clone https://github.com/Gustavjiversen01/lexaloud.git
cd lexaloud
./scripts/install.sh
```

See [`ubuntu-debian.md`](ubuntu-debian.md) from step 3 onward.

## Arch-specific notes

- Arch moves quickly. The pinned lockfile was resolved against a
  specific snapshot of PyPI; if you run into a resolution error, file
  an issue with your `python3 --version` and the error.
- There is no AUR package yet. If someone volunteers to maintain one,
  we'll link to it here.
- Manjaro, EndeavourOS, Garuda, Artix, and CachyOS inherit from Arch
  and should work with the same `pacman` commands. The installer
  classifies them all as `arch` family via `/etc/os-release` ID_LIKE.

## Reporting issues

Please include the full output of `lexaloud bug-report` when filing an
Arch-specific issue.
