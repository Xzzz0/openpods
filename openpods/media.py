"""Host-side helpers: MPRIS pause/resume (ear detection), PipeWire/Pulse volume (conversation awareness)."""
from __future__ import annotations

import logging
import os
import re
import subprocess

import dbus
from gi.repository import GLib

from .state import Change, EAR_IN

log = logging.getLogger("media")

MPRIS = "org.mpris.MediaPlayer2."
PLAYER = "org.mpris.MediaPlayer2.Player"


def _pactl(*args, timeout=3) -> str | None:
    try:
        r = subprocess.run(["pactl", *args], capture_output=True, text=True, timeout=timeout,
                           env={**os.environ, "LC_ALL": "C"})
        return r.stdout if r.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def default_sink() -> str | None:
    out = _pactl("get-default-sink")
    return out.strip() if out else None


def is_default_output(mac: str) -> bool:
    sink = default_sink() or ""
    return mac.replace(":", "_").upper() in sink.upper()


def sink_volume(sink: str) -> int | None:
    out = _pactl("get-sink-volume", sink)
    if not out:
        return None
    m = re.findall(r"(\d+)%", out)
    return round(sum(int(x) for x in m) / len(m)) if m else None


def set_sink_volume(sink: str, pct: int):
    _pactl("set-sink-volume", sink, f"{max(0, int(pct))}%")


class Mpris:
    def __init__(self):
        self.bus = dbus.SessionBus()
        self._paused: list[str] = []

    def _players(self):
        try:
            names = self.bus.list_names()
        except dbus.DBusException:
            return []
        return [str(n) for n in names if str(n).startswith(MPRIS)]

    def _status(self, name):
        try:
            obj = self.bus.get_object(name, "/org/mpris/MediaPlayer2")
            return str(dbus.Interface(obj, "org.freedesktop.DBus.Properties").Get(PLAYER, "PlaybackStatus"))
        except dbus.DBusException:
            return None

    def _call(self, name, method):
        try:
            obj = self.bus.get_object(name, "/org/mpris/MediaPlayer2")
            getattr(dbus.Interface(obj, PLAYER), method)()
            return True
        except dbus.DBusException as e:
            log.info("%s %s failed: %s", name, method, e)
            return False

    def pause_all(self) -> int:
        n = 0
        for p in self._players():
            if self._status(p) == "Playing" and self._call(p, "Pause"):
                if p not in self._paused:
                    self._paused.append(p)
                n += 1
        log.info("paused %d player(s)", n)
        return n

    def resume_paused(self) -> int:
        n = 0
        # Something else started meanwhile: leave it.
        if any(self._status(p) == "Playing" for p in self._players()):
            self._paused.clear()
            return 0
        for p in self._paused:
            if self._status(p) == "Paused" and self._call(p, "Play"):
                n += 1
        self._paused.clear()
        log.info("resumed %d player(s)", n)
        return n

    def forget(self):
        self._paused.clear()


class EarPause:
    """Pauses media when a bud leaves the ear, resumes when it is back (within 15 s of both being out)."""
    RESUME_WINDOW_S = 15

    def __init__(self):
        self.mpris = Mpris()
        self._session = None
        self._applied = None
        self._pending = False
        self._timer = 0

    def attach(self, session):
        self._session = session
        self._applied = None
        self._forget()

    def detach(self, session):
        if self._session is session:
            self._session = None
            self._applied = None
            self._forget()

    def on_change(self, session, change):
        if session is not self._session:
            return
        st = session.state
        if change & Change.SETTINGS and st.flag(0x0A) is not True:
            self._forget()
        if not change & Change.EAR:
            return
        count = (st.primary_ear == EAR_IN) + (st.secondary_ear == EAR_IN)
        prev = self._applied
        self._applied = count
        if count > 0:
            self._stop_timer()
        if prev is None or count == prev:
            return
        if count < prev:
            if self._can_act(session):
                self._pending |= self.mpris.pause_all() > 0
            if count == 0 and self._pending:
                self._stop_timer()
                self._timer = GLib.timeout_add_seconds(self.RESUME_WINDOW_S, self._expired)
            return
        if not self._pending:
            return
        self._pending = False
        if self._can_act(session):
            self.mpris.resume_paused()
        else:
            self.mpris.forget()

    def _can_act(self, session):
        return session.state.flag(0x0A) is True and is_default_output(session.mac)

    def _expired(self):
        self._timer = 0
        self._forget()
        return False

    def _stop_timer(self):
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0

    def _forget(self):
        self._stop_timer()
        self._pending = False
        self.mpris.forget()


class ConversationDucker:
    """Conversation awareness on the host: lowers the AirPods sink volume while you speak (AAP 0x4B levels).

    Levels 1/2 = speaking (duck to start x duck%), 3..7 step back up, 8/9 restore; 2 s without a new level after a
    3..7 step also restores. A volume changed by the user ends the episode and is kept.
    """
    RECOVERY = [0, 0, 0, 1 / 6, 2 / 6, 3 / 6, 4 / 6, 5 / 6]

    def __init__(self, duck_percent_of):
        self._duck_percent_of = duck_percent_of
        self._session = None
        self._sink = None
        self._start = None
        self._set = None
        self._timer = 0

    def attach(self, session):
        self.restore()
        self._session = session

    def detach(self, session):
        if self._session is session:
            self.restore()
            self._session = None

    def on_change(self, session, change):
        if session is not self._session:
            return
        if change & Change.SETTINGS and session.state.flag(0x28) is False:
            self.restore()
        if not change & Change.CONVERSATION_LEVEL:
            return
        level = session.state.conversation_level
        if level is None or session.state.flag(0x28) is not True:
            return
        if level in (1, 2):
            self._stop_timer()
            if self._start is None:
                if not is_default_output(session.mac):
                    return
                self._sink = default_sink()
                self._start = sink_volume(self._sink) if self._sink else None
                if self._start is None:
                    return
            elif not self._still_ours():
                self._end()
                return
            self._apply(self._ducked())
        elif 3 <= level <= 7:
            if self._start is None:
                return
            if not self._still_ours():
                self._end()
                return
            low = self._ducked()
            self._apply(round(low + (self._start - low) * self.RECOVERY[level]))
            self._stop_timer()
            self._timer = GLib.timeout_add(2000, self._timeout)
        elif level >= 8:
            self.restore()

    def _ducked(self):
        pct = self._duck_percent_of(self._session.mac) if self._session else 40
        return round(self._start * pct / 100)

    def _still_ours(self):
        if self._set is None:
            return True
        v = sink_volume(self._sink)
        return v is None or abs(v - self._set) <= 1

    def _apply(self, pct):
        set_sink_volume(self._sink, pct)
        self._set = pct

    def _timeout(self):
        self._timer = 0
        self.restore()
        return False

    def _stop_timer(self):
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0

    def restore(self):
        self._stop_timer()
        if self._start is not None and self._sink and self._still_ours():
            set_sink_volume(self._sink, self._start)
        self._end()

    def _end(self):
        self._stop_timer()
        self._start = None
        self._set = None
