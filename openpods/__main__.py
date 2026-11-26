"""OpenPods - AirPods controls for Linux (based on WPods). Usage:

  openpods [--hidden] [--debug]      start (or show the running instance)
  openpods ctl <command> [arg]       control the running instance:
      show | toggle | quit | status
      noise.cycle | noise.off | noise.nc | noise.transparency | noise.adaptive
      conversation.on | conversation.off
      connect [MAC] | disconnect [MAC] | connection.toggle
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import os
import signal
import sys


def _setup_logging(debug: bool):
    state = os.path.join(os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state")), "openpods")
    os.makedirs(state, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname).1s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if debug else logging.INFO)
    fh = logging.handlers.RotatingFileHandler(os.path.join(state, "openpods.log"), maxBytes=2_000_000, backupCount=2,
                                              encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    root.addHandler(sh)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    from . import ctl
    if argv and argv[0] == "ctl":
        if len(argv) < 2:
            print(__doc__)
            return 2
        reply = ctl.send(argv[1], argv[2] if len(argv) > 2 else None)
        if reply is None:
            print("OpenPods läuft nicht.", file=sys.stderr)
            return 1
        print(json.dumps(reply, indent=1, ensure_ascii=False))
        return 0 if "error" not in reply else 1
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        return 0
    hidden = "--hidden" in argv
    if ctl.send("show" if not hidden else "status") is not None:
        print("OpenPods läuft schon" + ("" if hidden else " – Fenster wird gezeigt") + ".")
        return 0
    _setup_logging("--debug" in argv)
    import dbus.mainloop.glib
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import GLib, Gtk
    GLib.set_prgname("openpods")
    GLib.set_application_name("OpenPods")
    from .app import App
    app = App(start_hidden=hidden)
    try:
        gi.require_version("GLibUnix", "2.0")
        from gi.repository import GLibUnix
        signal_add = GLibUnix.signal_add
    except (ValueError, ImportError):
        signal_add = GLib.unix_signal_add
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal_add(GLib.PRIORITY_DEFAULT, sig, lambda: (app.quit(), False)[1])
    logging.getLogger("app").info("OpenPods started")
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
