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

import json
import logging
import subprocess
import sys
from pathlib import Path

log = logging.getLogger(__name__)

# --- make the system-level gi module importable from inside the venv ------

try:
    import gi  # type: ignore
except ImportError:
    sys.path.append("/usr/lib/python3/dist-packages")
    try:
        import gi  # type: ignore
    except ImportError as e:
        print(
            "ReadAloud indicator: cannot import the 'gi' Python bindings. "
            "Install them with `sudo apt install python3-gi "
            "gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1` and ensure "
            "the 'ubuntu-appindicators' GNOME extension is enabled.",
            file=sys.stderr,
        )
        raise SystemExit(2) from e

try:
    gi.require_version("Gtk", "3.0")
    gi.require_version("AyatanaAppIndicator3", "0.1")
except ValueError as e:
    print(
        f"ReadAloud indicator: missing GIR typelib: {e}. "
        "Install with `sudo apt install gir1.2-gtk-3.0 "
        "gir1.2-ayatanaappindicator3-0.1`.",
        file=sys.stderr,
    )
    raise SystemExit(2) from e

from gi.repository import GLib, Gtk  # type: ignore  # noqa: E402
from gi.repository import AyatanaAppIndicator3 as AppIndicator3  # type: ignore  # noqa: E402

# --- paths ----------------------------------------------------------------

VENV_BIN = Path(sys.executable).parent
READALOUD_BIN = str(VENV_BIN / "readaloud")
SERVICE = "readaloud.service"

# Both icons are symbolic so they tint consistently with the GNOME panel
# theme instead of the tray flipping between colored and monochrome on
# state change.
ICON_RUNNING = "audio-headphones-symbolic"
ICON_WARMING = "audio-headphones-symbolic"
ICON_STOPPED = "audio-volume-muted-symbolic"


def _notify(summary: str, body: str = "") -> None:
    """Fire a best-effort notify-send; never raises."""
    try:
        args = ["notify-send", "--app-name", "ReadAloud", "--expire-time", "4000", "--", summary]
        if body:
            args.append(body)
        subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:  # noqa: BLE001
        log.debug("notify-send failed: %s", e)


def _systemctl(action: str) -> int:
    """Run `systemctl --user <action> readaloud.service` with full error
    handling. Returns the subprocess returncode, or -1 if the call
    couldn't be executed at all. Notifies on failure.
    """
    try:
        r = subprocess.run(
            ["systemctl", "--user", action, SERVICE],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        log.error("systemctl %s %s timed out", action, SERVICE)
        _notify(
            f"ReadAloud: systemctl {action} timed out",
            "systemd --user may be unresponsive. Check `systemctl --user status`.",
        )
        return -1
    except (OSError, subprocess.SubprocessError) as e:
        log.error("systemctl %s %s failed to execute: %s", action, SERVICE, e)
        _notify(
            "ReadAloud: cannot invoke systemctl",
            f"Is systemctl on PATH? {e}",
        )
        return -1
    if r.returncode != 0:
        stderr = (r.stderr or b"").decode("utf-8", errors="replace").strip()
        log.error("systemctl %s exited %d: %s", action, r.returncode, stderr)
        _notify(
            f"ReadAloud: systemctl {action} failed",
            stderr[:200] or f"Exit code {r.returncode}",
        )
    return r.returncode


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


def _daemon_state() -> str:
    """Ask the daemon what state it is in via GET /state.

    Returns the state string ("idle", "warming", "speaking", "paused")
    if the daemon answers, or "" on any failure (daemon down, HTTP
    error, bad JSON). The indicator uses this to distinguish the
    "warming" state from plain "idle" so the menu can grey out the
    Speak item during cold-start. 500 ms connect / read timeouts keep
    the GTK main loop responsive.
    """
    try:
        from urllib.request import urlopen

        with urlopen("http://127.0.0.1:5487/state", timeout=0.5) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        return str(data.get("state", ""))
    except Exception:  # noqa: BLE001
        return ""


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

        # Cached current icon to avoid re-calling set_icon_full every
        # poll (which was causing unnecessary DBus traffic and, on some
        # versions of libayatana-appindicator, visible icon flicker).
        self._current_icon: str | None = None
        # Cached control window so the menu opens the SAME window every
        # time instead of leaking a new GtkWindow on each click.
        self._control_window = None

        # Prime the state so the menu label and icon reflect reality.
        self._refresh_state()
        # Poll every 3 seconds so external systemctl changes show up
        # without waking the CPU too often.
        GLib.timeout_add_seconds(3, self._refresh_state)

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
        # Distinguish warming from plain active by asking the daemon
        # directly. If the daemon isn't responding yet (fresh start,
        # warming in progress, or HTTP error), fall back to the
        # systemctl is-active result.
        state_str = _daemon_state() if active else ""
        warming = state_str == "warming"

        if warming:
            desired_icon = ICON_WARMING
            desired_tooltip = "ReadAloud: warming up"
            desired_toggle_label = "Stop daemon (warming…)"
        elif active:
            desired_icon = ICON_RUNNING
            desired_tooltip = "ReadAloud: running"
            desired_toggle_label = "Stop daemon (free GPU)"
        else:
            desired_icon = ICON_STOPPED
            desired_tooltip = "ReadAloud: stopped"
            desired_toggle_label = "Start daemon"

        # Only update the icon if it actually changed, to avoid DBus
        # churn and tray flicker.
        if desired_icon != self._current_icon:
            self.indicator.set_icon_full(desired_icon, desired_tooltip)
            self._current_icon = desired_icon
        if self.item_toggle_daemon.get_label() != desired_toggle_label:
            self.item_toggle_daemon.set_label(desired_toggle_label)

        # Grey out playback actions unless the daemon is fully ready.
        ready_for_playback = active and not warming
        for it in (self.item_speak, self.item_pause, self.item_stop):
            it.set_sensitive(ready_for_playback)

        # Toggling while warming is always allowed (user may want to
        # abort the warmup), but the Control window needs the daemon
        # running at all, not just warmed up — leave it sensitive
        # whenever the daemon is active or stopped (never disabled).
        return True  # keep polling

    # ---------- menu handlers ----------

    def _on_toggle_daemon(self, _src) -> None:
        action = "stop" if _daemon_active() else "start"
        _systemctl(action)
        # Poll state again in 500ms to catch up with systemd.
        GLib.timeout_add(500, self._refresh_state)

    def _spawn_detached(self, args: list[str]) -> None:
        """Launch a CLI subcommand from a menu click.

        `start_new_session=True` detaches the child into its own process
        group so it won't become a zombie under the indicator process.
        stdin/stdout/stderr are redirected to /dev/null so a closed
        terminal doesn't SIGPIPE the child.
        """
        try:
            subprocess.Popen(
                args,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except (OSError, subprocess.SubprocessError) as e:
            log.error("Popen %s failed: %s", args[0], e)
            _notify("ReadAloud: could not invoke CLI", str(e))

    def _on_speak_selection(self, _src) -> None:
        self._spawn_detached([READALOUD_BIN, "speak-selection"])

    def _on_pause_resume(self, _src) -> None:
        self._spawn_detached([READALOUD_BIN, "toggle"])

    def _on_stop_playback(self, _src) -> None:
        self._spawn_detached([READALOUD_BIN, "stop"])

    def _on_control(self, _src) -> None:
        # Import here so the indicator starts even if the control window
        # has a transient issue (e.g., gsettings schema missing).
        try:
            from .gui_control import ControlWindow
        except Exception as e:  # noqa: BLE001
            log.error("failed to import ControlWindow: %s", e)
            _notify("ReadAloud: control window unavailable", str(e))
            return
        # Reuse an existing window instance so repeated menu clicks
        # don't leak new windows on every open.
        if self._control_window is None or not self._control_window.get_visible():
            try:
                self._control_window = ControlWindow()
                self._control_window.connect(
                    "destroy", lambda *_: setattr(self, "_control_window", None)
                )
            except Exception as e:  # noqa: BLE001
                log.exception("ControlWindow construction failed: %s", e)
                _notify("ReadAloud: control window error", str(e)[:200])
                self._control_window = None
                return
        self._control_window.present()

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
