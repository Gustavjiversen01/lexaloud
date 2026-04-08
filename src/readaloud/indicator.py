"""GNOME top-bar tray indicator for ReadAloud.

Requires the `ubuntu-appindicators` GNOME Shell extension (installed and
enabled by default on Ubuntu 24.04) and the system packages `python3-gi`
and `gir1.2-ayatanaappindicator3-0.1`.

The venv does not include --system-site-packages, so we prepend
`/usr/lib/python3/dist-packages` to sys.path before importing gi. This
scopes the system-site-packages dependency to this single process — the
daemon, CLI, and tests are unaffected.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# --- make the system-level gi module importable from inside the venv ------

try:  # pragma: no cover
    import gi  # type: ignore
except ImportError:  # pragma: no cover
    sys.path.append("/usr/lib/python3/dist-packages")
    import gi  # type: ignore

gi.require_version("Gtk", "3.0")
gi.require_version("AyatanaAppIndicator3", "0.1")
from gi.repository import GLib, Gtk  # type: ignore  # noqa: E402
from gi.repository import AyatanaAppIndicator3 as AppIndicator3  # type: ignore  # noqa: E402

# --- paths ----------------------------------------------------------------

VENV_BIN = Path(sys.executable).parent
READALOUD_BIN = str(VENV_BIN / "readaloud")
SERVICE = "readaloud.service"

ICON_RUNNING = "audio-headphones"
ICON_STOPPED = "audio-headphones-symbolic"


def _systemctl(action: str) -> int:
    return subprocess.run(
        ["systemctl", "--user", action, SERVICE],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
    ).returncode


def _daemon_active() -> bool:
    try:
        r = subprocess.run(
            ["systemctl", "--user", "is-active", SERVICE],
            capture_output=True,
            text=True,
            timeout=2,
        )
        return r.stdout.strip() == "active"
    except Exception:  # noqa: BLE001
        return False


class ReadAloudIndicator:
    def __init__(self) -> None:
        self.indicator = AppIndicator3.Indicator.new(
            "readaloud",
            ICON_STOPPED,
            AppIndicator3.IndicatorCategory.APPLICATION_STATUS,
        )
        self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
        self.indicator.set_title("ReadAloud")

        self.menu = Gtk.Menu()
        self._build_menu()
        self.indicator.set_menu(self.menu)

        # Prime the state so the menu label and icon reflect reality.
        self._refresh_state()
        # Poll every 2 seconds so external systemctl changes show up too.
        GLib.timeout_add_seconds(2, self._refresh_state)

    # ---------- menu ----------

    def _build_menu(self) -> None:
        self.item_toggle_daemon = Gtk.MenuItem(label="Start daemon")
        self.item_toggle_daemon.connect("activate", self._on_toggle_daemon)
        self.menu.append(self.item_toggle_daemon)

        self.item_speak = Gtk.MenuItem(label="Speak highlighted selection")
        self.item_speak.connect("activate", self._on_speak_selection)
        self.menu.append(self.item_speak)

        self.item_pause = Gtk.MenuItem(label="Pause / resume")
        self.item_pause.connect("activate", self._on_pause_resume)
        self.menu.append(self.item_pause)

        self.item_stop = Gtk.MenuItem(label="Stop current playback")
        self.item_stop.connect("activate", self._on_stop_playback)
        self.menu.append(self.item_stop)

        self.menu.append(Gtk.SeparatorMenuItem())

        self.item_control = Gtk.MenuItem(label="Control window…")
        self.item_control.connect("activate", self._on_control)
        self.menu.append(self.item_control)

        self.menu.append(Gtk.SeparatorMenuItem())

        self.item_quit = Gtk.MenuItem(label="Quit indicator")
        self.item_quit.connect("activate", self._on_quit)
        self.menu.append(self.item_quit)

        self.menu.show_all()

    # ---------- state polling ----------

    def _refresh_state(self) -> bool:
        active = _daemon_active()
        if active:
            self.item_toggle_daemon.set_label("Stop daemon (free GPU)")
            self.indicator.set_icon_full(ICON_RUNNING, "ReadAloud: running")
        else:
            self.item_toggle_daemon.set_label("Start daemon")
            self.indicator.set_icon_full(ICON_STOPPED, "ReadAloud: stopped")
        # Gray out actions that require the daemon.
        for it in (self.item_speak, self.item_pause, self.item_stop):
            it.set_sensitive(active)
        return True  # keep polling

    # ---------- menu handlers ----------

    def _on_toggle_daemon(self, _src) -> None:
        action = "stop" if _daemon_active() else "start"
        _systemctl(action)
        # Poll state again in 500ms to catch up with systemd.
        GLib.timeout_add(500, self._refresh_state)

    def _on_speak_selection(self, _src) -> None:
        subprocess.Popen([READALOUD_BIN, "speak-selection"])

    def _on_pause_resume(self, _src) -> None:
        subprocess.Popen([READALOUD_BIN, "toggle"])

    def _on_stop_playback(self, _src) -> None:
        subprocess.Popen([READALOUD_BIN, "stop"])

    def _on_control(self, _src) -> None:
        # Import here so the indicator starts even if the control window
        # has a transient issue.
        from .gui_control import ControlWindow

        win = ControlWindow()
        win.present()

    def _on_quit(self, _src) -> None:
        Gtk.main_quit()


def _acquire_single_instance_lock():
    """Take an exclusive flock on $XDG_RUNTIME_DIR/readaloud-indicator.lock.

    Returns the open file descriptor (int) on success — the caller keeps it
    alive for the process lifetime. Returns None if another indicator is
    already running. Returns "skip" if we couldn't even create the runtime
    dir (rare; we then proceed without single-instance enforcement).

    Implementation notes:
    - We open with `O_RDWR | O_CREAT` (NOT "w" mode), so a second launcher
      does NOT truncate the winner's PID file while probing for the lock.
    - We only truncate and write the PID AFTER flock succeeds, so an
      informational `cat` of the lockfile shows the real winner's PID.
    - flock is released by the kernel when the process exits for any
      reason, including SIGKILL, so the lockfile is never stale.
    """
    import fcntl
    import os

    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/readaloud-{os.getuid()}"
    try:
        os.makedirs(runtime, exist_ok=True)
    except OSError:
        return "skip"
    lock_path = os.path.join(runtime, "readaloud-indicator.lock")
    try:
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    except OSError:
        return "skip"
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return None
    # We have the lock. Safe to truncate and write our PID for humans.
    try:
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode())
    except OSError:
        pass
    return fd


def main() -> int:
    """Entry point for `readaloud-indicator`."""
    lock = _acquire_single_instance_lock()
    if lock is None:
        print(
            "ReadAloud indicator is already running. Exiting.",
            file=sys.stderr,
        )
        return 0
    # If lock is "skip" we couldn't check; proceed anyway. If it's a real
    # file descriptor (int), keep it alive for the process lifetime by
    # stashing it on the module so the GC doesn't close it.
    if isinstance(lock, int):
        globals()["_instance_lock_fd"] = lock

    ReadAloudIndicator()
    try:
        Gtk.main()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
