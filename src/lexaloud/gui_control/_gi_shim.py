"""GTK3 / gi import shim — single place for the system-site-packages hack.

Both ``keybindings.py`` and ``control_window.py`` import Gtk and Gdk from
here instead of duplicating the sys.path dance.
"""

import sys

try:
    import gi
except ImportError:
    from ..platform import system_site_packages_candidates

    for _candidate in system_site_packages_candidates():
        sys.path.append(str(_candidate))
        try:
            import gi  # noqa: F811

            break
        except ImportError:
            continue
    else:
        raise  # re-raise the original ImportError if no candidate worked

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk  # noqa: E402

__all__ = ["Gdk", "Gtk"]
