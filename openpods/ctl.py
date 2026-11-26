"""Single-instance control socket: `openpods ctl <command>` talks to the running app (for KDE shortcuts, scripts)."""
from __future__ import annotations

import json
import logging
import os
import socket

from gi.repository import GLib

log = logging.getLogger("ctl")

SOCK = os.path.join(os.environ.get("XDG_RUNTIME_DIR", f"/tmp/openpods-{os.getuid()}"), "openpods.sock")


def send(cmd: str, arg: str | None = None, timeout=3.0):
    """-> reply dict, or None when no instance runs."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(SOCK)
    except OSError:
        s.close()
        return None
    try:
        s.sendall((json.dumps({"cmd": cmd, "arg": arg}) + "\n").encode())
        data = b""
        while not data.endswith(b"\n"):
            chunk = s.recv(65536)
            if not chunk:
                break
            data += chunk
        return json.loads(data or b"{}")
    except (OSError, ValueError):
        return {"error": "no reply"}
    finally:
        s.close()


class ControlServer:
    def __init__(self, handler):
        self._handler = handler
        try:
            os.unlink(SOCK)
        except FileNotFoundError:
            pass
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.bind(SOCK)
        os.chmod(SOCK, 0o600)
        self.sock.listen(4)
        self.sock.setblocking(False)
        self._watch = GLib.io_add_watch(self.sock.fileno(), GLib.IO_IN, self._accept)

    def _accept(self, *_):
        try:
            conn, _ = self.sock.accept()
        except OSError:
            return True
        conn.settimeout(2.0)
        try:
            data = b""
            while not data.endswith(b"\n"):
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
            req = json.loads(data or b"{}")
            if not isinstance(req, dict):
                raise ValueError("request is not an object")
            arg = req.get("arg")
            try:
                reply = self._handler(str(req.get("cmd", "")), None if arg is None else str(arg))
            except Exception:  # noqa: BLE001 - a failing command must never kill the socket (GLib drops the watch)
                log.exception("ctl command %r failed", req.get("cmd"))
                reply = {"error": "internal error"}
            conn.sendall((json.dumps(reply if reply is not None else {"ok": True}) + "\n").encode())
        except (OSError, ValueError) as e:
            log.info("ctl request failed: %s", e)
        except Exception:  # noqa: BLE001
            log.exception("ctl request failed")
        finally:
            conn.close()
        return True

    def close(self):
        GLib.source_remove(self._watch)
        self.sock.close()
        try:
            os.unlink(SOCK)
        except FileNotFoundError:
            pass
