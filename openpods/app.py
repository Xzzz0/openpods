"""OpenPods controller: BlueZ devices -> AAP sessions -> web UI, tray, nearby popup, control socket."""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

import dbus  # noqa: E402

from . import aap, models  # noqa: E402
from .bluez import BlueZ  # noqa: E402
from .ctl import ControlServer  # noqa: E402
from .hires_mic import HiResMic  # noqa: E402
from .media import ConversationDucker, EarPause  # noqa: E402
from .nearby import Nearby  # noqa: E402
from .session import Session  # noqa: E402
from .settings import Settings  # noqa: E402
from .state import (Caps, Change, STEM_ORDER, HEADPHONE, LEFT, RIGHT, CASE, BAT_CHARGING,  # noqa: E402
                    LISTENING_MODES)
from .ui import WebWindow, desktop_accent, desktop_dark  # noqa: E402

log = logging.getLogger("app")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")
LOCALES = os.path.join(ROOT, "locales")
ASSETS = os.path.join(ROOT, "assets")
ICON = os.path.join(ASSETS, "openpods.png")
VERSION = "0.4.4-linux1"
SUPPORT_URL = "https://github.com/FPNDev/wpods#support-wpods"
MAX_ATTACH_ATTEMPTS = 8
POPUP_W = 380
POPUP_TITLE = "OpenPods – AirPods in der Nähe"
# Handoff (phone -> PC): when the link comes up, the AirPods still negotiate A2DP/HFP for a moment. Opening AAP and
# starting the HD mic in that window made them refuse A2DP (-> mono HFP "slime" sound) or drop the link.
SETTLE_AFTER_RESOLVED_S = 1.0  # wait this long after BlueZ reports ServicesResolved
SETTLE_MAX_S = 6.0             # ... but never longer than this after the link came up
CONNECT_RETRIES = 2            # extra Device.Connect attempts on transient BlueZ errors
CONNECT_RETRY_DELAYS = (2, 4)
A2DP_CHECK_AFTER_READY_S = 3
LOW_BATTERY = 10
STEM_BIT = {name: bit for bit, name in STEM_ORDER}


def _transient(err) -> bool:
    e = str(err or "").lower()
    return any(k in e for k in ("br-connection", "in progress", "busy", "timed out", "timeout", "host is down",
                                "page-timeout", "profile-unavailable", "inprogress", "abort"))


def _system_language() -> str:
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        v = os.environ.get(var)
        if v and v not in ("C", "POSIX"):
            return v.split(":")[0].split(".")[0].replace("_", "-")
    return "en-US"


class Locales:
    def __init__(self, directory):
        self.files = {}
        for name in sorted(os.listdir(directory), key=str.lower):
            if name.endswith(".json"):
                try:
                    with open(os.path.join(directory, name), encoding="utf-8") as f:
                        self.files[name[:-5]] = json.load(f)
                except (OSError, ValueError) as e:
                    log.warning("locale %s skipped: %s", name, e)

    def pick(self, wanted: str) -> str:
        if wanted in self.files:
            return wanted
        lang = wanted.split("-")[0].lower()
        for code in self.files:
            if code.split("-")[0].lower() == lang:
                return code
        return "en-US" if "en-US" in self.files else next(iter(self.files))

    def resolve(self, choice: str):
        code = self.pick(_system_language() if choice in ("system", "") else choice)
        labels = dict(self.files["en-US"]["labels"]) if "en-US" in self.files else {}
        labels.update(self.files[code]["labels"])
        # Linux port: same texts, with the platform and app name swapped.
        labels = {k: v.replace("WPods", "OpenPods").replace("Windows", "Linux") for k, v in labels.items()}
        rtl = code.split("-")[0].lower() in ("ar", "he", "fa", "ur")
        return code, labels, rtl


class App:
    def __init__(self, start_hidden=False):
        self.settings = Settings()
        self.locales = Locales(LOCALES)
        self._resolve_locale()
        self.session: Session | None = None
        self.connecting: set[str] = set()
        self.user_disconnected: set[str] = set()
        self.attach_failed: set[str] = set()
        self.attempts: dict[str, int] = {}
        self._retry_timers: dict[str, int] = {}
        self._connect_timeouts: dict[str, int] = {}
        self._settle_timers: dict[str, int] = {}
        self._last_battery: dict[str, tuple[float, dict]] = {}
        self._last_sent: dict[str, str] = {}
        self._flush_pending = False
        self._low_notified: set[str] = set()
        self._notify_id = 0
        self.dark = desktop_dark()
        self.accent = desktop_accent()
        Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme", self.dark)
        self.ear_pause = EarPause()
        self.ducker = ConversationDucker(self.settings.duck_percent)
        self.hd_mic = HiResMic(self.settings, on_reset=self._reset_session)
        self.main = WebWindow(WEB, "index.html", self._on_main_message, 400,
                              int(self.settings.ui.get("windowHeight", 720)), "OpenPods", ICON)
        self.main.on_hide_request = lambda: self._post_main({"type": "visibility", "visible": False})
        self.popup: WebWindow | None = None
        self.nearby = Nearby(self.settings, self._known_pairs, self._on_offers)
        self.bluez = BlueZ(self._on_devices, self.nearby.on_advert, self._on_adapter)
        self._build_tray()
        self._on_devices()
        self.ctl = ControlServer(self.command)
        GLib.timeout_add_seconds(3, self._tick)
        if not start_hidden or not self.settings.ui.get("firstRunDone"):
            self.show_main()

    # ------------------------------------------------------------------ helpers
    def _resolve_locale(self):
        self.lang, self.labels, self.rtl = self.locales.resolve(self.settings.ui.get("language", "system"))

    def text(self, key, **kw):
        s = self.labels.get(key, key)
        for k, v in kw.items():
            s = s.replace("{" + k + "}", str(v))
        return s

    def _known_pairs(self):
        return [(d.mac, d.name) for d in self.bluez.devices.values()] if hasattr(self, "bluez") else []

    def _devices(self):
        return sorted(self.bluez.devices.values(), key=lambda d: d.mac)

    def _model_of(self, mac, product_id=0):
        number = self.settings.get(mac, "modelNumber") or models.model_number_of(product_id)
        return models.from_model_number(number) or models.from_product_id(product_id) or models.UNKNOWN

    # ------------------------------------------------------------------ BlueZ events
    def _on_adapter(self, powered):
        log.info("adapter powered=%s", powered)
        if hasattr(self, "bluez"):
            self._schedule_flush()
            self._update_scan()

    def _on_devices(self):
        if not hasattr(self, "bluez"):
            return
        for d in self._devices():
            if d.connected:
                self.user_disconnected.discard(d.mac)
                if self.session is None and d.mac not in self._retry_timers and d.mac not in self.attach_failed:
                    self._attach_when_settled(d)
            else:
                self._cancel_settle(d.mac)
                self.attach_failed.discard(d.mac)
                self.attempts.pop(d.mac, None)
                self._cancel_retry(d.mac)
                if self.session and self.session.mac == d.mac:
                    log.info("%s disconnected (BlueZ); closing session", d.mac)
                    self._drop_session(self.session, "linkLost")
        if self.session and not self.bluez.by_mac(self.session.mac):
            self._drop_session(self.session, "closed")
        self._schedule_flush()
        self._update_scan()

    # ------------------------------------------------------------------ sessions
    def _attach(self, mac, previous: Session | None = None):
        d = self.bluez.by_mac(mac)
        if d is None or not d.connected or self.session is not None:
            return
        self.attempts[mac] = self.attempts.get(mac, 0) + 1
        log.info("attach %s (attempt %d)", mac, self.attempts[mac])
        s = Session(mac, self.settings, d.product_id, self._on_session_change, self._on_session_end)
        if previous is not None:
            s.carry_over(previous)
        self.session = s
        self.ear_pause.attach(s)
        self.ducker.attach(s)
        self.hd_mic.attach(s)
        s.start()
        self._schedule_flush()
        self._update_scan()

    def _settle_left(self, d) -> float:
        """Seconds until a freshly connected link is calm enough for AAP (0 = go)."""
        if not d.connected_at:
            return 0.0
        now = time.monotonic()
        left = SETTLE_MAX_S - (now - d.connected_at)
        if d.services_resolved and d.resolved_at >= d.connected_at:
            left = min(left, SETTLE_AFTER_RESOLVED_S - (now - d.resolved_at))
        return max(0.0, left)

    def _attach_when_settled(self, d):
        if d.mac in self._settle_timers:
            # ServicesResolved may have arrived: re-evaluate below by replacing the timer
            GLib.source_remove(self._settle_timers.pop(d.mac))
        wait = self._settle_left(d)
        if wait <= 0:
            self._attach(d.mac)
            return
        mac = d.mac

        def go():
            self._settle_timers.pop(mac, None)
            dd = self.bluez.by_mac(mac)
            if dd and dd.connected and self.session is None and mac not in self._retry_timers:
                self._attach(mac)
            return False
        log.info("link %s up, letting audio profiles settle (%.1f s)", mac, wait)
        self._settle_timers[mac] = GLib.timeout_add(int(wait * 1000) + 50, go)

    def _cancel_settle(self, mac):
        t = self._settle_timers.pop(mac, None)
        if t:
            GLib.source_remove(t)

    def _reset_session(self, s: Session):
        """Close the AAP channel and open a fresh one (Bluetooth link stays up)."""
        if self.session is not s:
            return
        mac = s.mac
        self._drop_session(s, "reset")

        def again():
            if self.session is None:
                self._attach(mac, s if s.state.status == "ready" else None)
            return False
        GLib.timeout_add(1500, again)

    def _drop_session(self, s: Session, reason):
        s.close()
        if self.session is s:
            self._detach(s)

    def _detach(self, s: Session):
        self.session = None
        self.ear_pause.detach(s)
        self.ducker.detach(s)
        self.hd_mic.detach(s)
        self._schedule_flush()
        self._update_scan()

    def _on_session_end(self, s: Session, reason):
        log.info("session %s ended: %s", s.mac, reason)
        if self.session is not s:
            return
        self._detach(s)
        d = self.bluez.by_mac(s.mac)
        if reason == "closed" or d is None or not d.connected or s.mac in self.user_disconnected:
            return
        if self.attempts.get(s.mac, 0) >= MAX_ATTACH_ATTEMPTS:
            log.warning("attach %s: giving up after %d attempts", s.mac, self.attempts[s.mac])
            self.attach_failed.add(s.mac)
            self.connecting.discard(s.mac)
            self._schedule_flush()
            return
        delay = 1500 if s.state.status == "ready" else 2500
        prev = s if s.state.status == "ready" else None

        def retry():
            self._retry_timers.pop(s.mac, None)
            if self.session is None:
                self._attach(s.mac, prev)
            return False
        self._cancel_retry(s.mac)
        self._retry_timers[s.mac] = GLib.timeout_add(delay, retry)
        self._schedule_flush()

    def _cancel_retry(self, mac):
        t = self._retry_timers.pop(mac, None)
        if t:
            GLib.source_remove(t)

    def _on_session_change(self, s: Session, change):
        if s is not self.session:
            return
        if change & Change.CONNECTION and s.state.status == "ready":
            self.attempts[s.mac] = 0
            self.hd_mic.on_ready(s)

            def a2dp_check(sess=s):
                if self.session is sess:
                    self.hd_mic.ensure_music_profile(sess)
                return False
            GLib.timeout_add_seconds(A2DP_CHECK_AFTER_READY_S, a2dp_check)
            if s.mac in self.connecting:
                self.connecting.discard(s.mac)
            o = self.nearby.offers.get(s.mac)
            if o and o.state == "connecting":
                o.state = "connected"
                self._send_offers()
                GLib.timeout_add_seconds(3, self._close_connected_offer, s.mac)
        if change & Change.IDENTITY:
            self._schedule_flush()
        self.ear_pause.on_change(s, change)
        self.ducker.on_change(s, change)
        if change & Change.BATTERY:
            self._check_low_battery(s)
        self._schedule_flush()

    def _close_connected_offer(self, mac):
        o = self.nearby.offers.get(mac)
        if o and o.state == "connected":
            self.nearby.drop(mac)
            self._send_offers()
        return False

    # ------------------------------------------------------------------ JSON for the page
    def _conn(self, d) -> str:
        if self.session and self.session.mac == d.mac and self.session.state.status != "initializing":
            return "connected" if self.session.state.status == "ready" else "reconnecting"
        o = self.nearby.offers.get(d.mac)
        if d.mac in self.connecting or (o and o.state == "connecting"):
            return "connecting"
        if d.mac in self.user_disconnected:
            return "notConnected"
        if d.mac in self.attach_failed:
            return "attachFailed"
        if d.connected:
            return "reconnecting" if self.attempts.get(d.mac, 0) > 1 else "connecting"
        return "elsewhere" if d.mac in self.nearby.seen else "notConnected"

    def _caps_list(self, caps, model):
        out = [name for bit, name in Caps.NAMES if caps & bit]
        if model.single_battery:
            out.append("singleBattery")
        out.append("noStereoMic")
        return out

    def _host_json(self, mac):
        return {"disableHandsFree": False, "lowLatency": False, "lowLatencyMic": False, "micMode": "standard",
                "duckPercent": self.settings.duck_percent(mac), "hdVoice": False}

    def _setting_fields(self, pod, ear_detection, allow_off, mic_side):
        return {
            "earDetection": ear_detection,
            "conversationAwareness": pod.get("conversationAwareness"),
            "personalizedVolume": pod.get("personalizedVolume"),
            "oneBudAnc": pod.get("oneBudAnc"),
            "allowOff": allow_off,
            "micSide": mic_side,
            "pressSpeed": pod.get("pressSpeed"),
            "holdDuration": pod.get("holdDuration"),
            "toneVolume": pod.get("toneVolume"),
            "hearingAidEnrolled": pod.get("hearingAidEnrolled"),
            "hearingAidEnabled": bool(pod.get("hearingAidEnabled", False)),
            "mediaAssistCalls": pod.get("mediaAssistCalls"),
            "mediaAssistMedia": pod.get("mediaAssistMedia"),
        }

    def _device_json(self, d):
        mac = d.mac
        model = self._model_of(mac, d.product_id)
        caps = self.settings.get(mac, "caps", 0) | model.caps
        if self.session and self.session.mac == mac:
            caps |= self.session.state.caps
        conn = self._conn(d)
        seen = self.nearby.seen.get(mac)
        stem = self.settings.stem_modes(mac)
        saved = dict(self._setting_fields(self.settings.get(mac, "podSettings", {}), self.settings.ear_detection(mac),
                                          self.settings.allow_off(mac),
                                          {0: "automatic", 1: "right", 2: "left"}.get(self.settings.mic_side(mac))))
        saved["listeningMode"] = self.settings.get(mac, "podSettings", {}).get("listeningMode")
        return {
            "id": mac, "name": d.name, "model": model.name, "art": model.art,
            "caps": self._caps_list(caps, model), "conn": conn,
            "hasKeys": self.settings.keys(mac) is not None,
            "batteries": seen[1].to_json() if conn == "elsewhere" and seen else None,
            "host": self._host_json(mac),
            "stemModes": [name for bit, name in STEM_ORDER if stem & bit],
            "saved": saved,
        }

    def _checking(self, st):
        return not st.initial_report_done and st.status != "noResponse"

    def _shown(self, st):
        return st.pod_settings(st.remembered_settings if self._checking(st) else {})

    def _state_parts(self, s: Session):
        st = s.state
        b = st.battery_source
        e = st.ear_source
        pod = self._shown(st)
        model = models.from_model_number(st.model_number) or self._model_of(s.mac)
        return {
            "battery": {"left": b.battery(LEFT).to_json(), "right": b.battery(RIGHT).to_json(),
                        "case": b.battery(CASE).to_json(), "headphone": b.battery(HEADPHONE).to_json()},
            "ear": {"left": e.left_ear, "right": e.right_ear},
            "listeningMode": pod.get("listeningMode"),
            "settings": self._setting_fields(pod, st.flag(aap.EAR_DETECTION), st.flag(aap.ALLOW_OFF), st.mic_side),
            "heartRate": {"heartRate": st.heart_rate, "heartRateBpm": st.heart_rate_bpm},
            "caps": self._caps_list(st.caps, model),
            "checking": {"checking": self._checking(st), "ready": st.status == "ready"},
        }

    def _state_json(self):
        s = self.session
        if s is None:
            return None
        p = self._state_parts(s)
        out = {"battery": p["battery"], "ear": p["ear"], "listeningMode": p["listeningMode"]}
        out.update(p["settings"])
        out.update(p["heartRate"])
        out["caps"] = p["caps"]
        out.update(p["checking"])
        return out

    def _devices_msg(self):
        return {"type": "devices", "devices": [self._device_json(d) for d in self._devices()],
                "attached": self.session.mac if self.session else None}

    def _prefs(self):
        return {"theme": self.settings.ui.get("theme", "auto"), "useAccent": bool(self.settings.ui.get("useAccent")),
                "accent": self.accent}

    def _languages(self):
        return [{"code": c, "originalName": f.get("originalName", c), "engName": f.get("engName", c)}
                for c, f in self.locales.files.items()]

    def _main_init(self):
        sys_code = self.locales.pick(_system_language())
        devs = self._devices_msg()
        selected = self.settings.ui.get("selected")
        if selected not in [d["id"] for d in devs["devices"]]:
            selected = None
        msg = {"type": "init", "labels": self.labels, "lang": self.lang, "rtl": self.rtl,
               "languages": self._languages(),
               "language": "" if self.settings.ui.get("language", "system") == "system" else self.settings.ui["language"],
               "windowsLanguageName": self.locales.files[sys_code].get("originalName", sys_code),
               **self._prefs(), "visible": self.main.shown,
               "startup": Settings.startup_enabled(), "firstRun": not self.settings.ui.get("firstRunDone"),
               "adapterUnsupported": False, "restartPending": False,
               "update": {"version": VERSION, "available": None, "status": "idle", "checked": True, "auto": False,
                          "dismissed": None},
               "devices": devs["devices"], "attached": devs["attached"], "selected": selected,
               "state": self._state_json(), "mic": "unsupported",
               "micCatalog": {"standard": [], "voiceIsolation": [], "wideSpectrum": [], "enhancement": []},
               "micConfig": {"modes": [], "models": {"standard": "", "voiceIsolation": "", "wideSpectrum": ""},
                             "enhancement": None},
               "mixer": {"devices": [], "enabled": False, "hideDisconnected": False, "hideDisabled": False},
               "hotkeys": {"sounds": False, "items": []}}
        return msg

    # ------------------------------------------------------------------ sending
    def _post_main(self, msg):
        self.main.post(msg)

    def _send(self, key, msg, force=False):
        js = json.dumps(msg, sort_keys=True)
        if not force and self._last_sent.get(key) == js:
            return
        self._last_sent[key] = js
        self._post_main(msg)

    def _schedule_flush(self):
        if not self._flush_pending:
            self._flush_pending = True
            GLib.idle_add(self._flush)

    def _flush(self):
        self._flush_pending = False
        self._update_tray()
        if not self.main.ready or not self.main.shown:
            return False
        self._send("devices", self._devices_msg())
        s = self.session
        attached_key = s.mac if s else None
        if self._last_sent.get("_attached") != str(attached_key) + str(id(s)):
            self._last_sent["_attached"] = str(attached_key) + str(id(s))
            for k in ("battery", "ear", "listeningMode", "settings", "heartRate", "caps", "checking"):
                self._last_sent.pop(k, None)
            self._send("state", {"type": "state", "state": self._state_json()}, force=True)
            if s:
                for k, v in self._state_parts(s).items():
                    self._last_sent[k] = json.dumps(self._part_msg(k, v), sort_keys=True)
            return False
        if s:
            for k, v in self._state_parts(s).items():
                self._send(k, self._part_msg(k, v))
        return False

    @staticmethod
    def _part_msg(k, v):
        if k in ("battery", "ear", "listeningMode", "caps"):
            return {"type": k, k: v}
        if k == "settings":
            return {"type": "settings", "settings": v}
        return {"type": k, **v}

    def _toast(self, toast, device=None, code=None):
        msg = {"type": "toast", "toast": toast, "device": device}
        if code:
            msg["code"] = code
        self._post_main(msg)

    # ------------------------------------------------------------------ main page messages
    def _on_main_message(self, m):
        t = m.get("type")
        s = self.session
        log.debug("page: %s", m)
        if t == "ready":
            self._last_sent.clear()
            self._post_main(self._main_init())
            self._last_sent["devices"] = json.dumps(self._devices_msg(), sort_keys=True)
            self._last_sent["_attached"] = str(s.mac if s else None) + str(id(s))
            if s:
                for k, v in self._state_parts(s).items():
                    self._last_sent[k] = json.dumps(self._part_msg(k, v), sort_keys=True)
        elif t == "connect":
            self.connect(m.get("id"))
        elif t == "cancel":
            mac = m.get("id")
            self.connecting.discard(mac)
            self.bluez.disconnect(mac)
            self._schedule_flush()
        elif t == "disconnect":
            self.disconnect(m.get("id"))
        elif t == "reconnect":
            mac = m.get("id")
            self.attach_failed.discard(mac)
            self.attempts[mac] = 0
            if s and s.mac == mac:
                self._drop_session(s, "closed")
            d = self.bluez.by_mac(mac)
            if d and d.connected:
                self._attach(mac)
            else:
                self.connect(mac)
        elif t == "setListeningMode" and s and m.get("mode") in LISTENING_MODES.values():
            s.set_listening_mode(m["mode"])
        elif t == "setToggle" and s and isinstance(m.get("value"), bool):
            fn = {"earDetection": s.set_ear_detection, "conversationAwareness": s.set_conversation_awareness,
                  "personalizedVolume": s.set_personalized_volume, "oneBudAnc": s.set_one_bud_anc,
                  "allowOff": s.set_allow_off}.get(m.get("name"))
            if fn:
                fn(m["value"])
        elif t == "setHeartRate" and s:
            s.set_heart_rate(bool(m.get("value")))
        elif t == "setHearingAid" and s:
            s.set_hearing_modes(hearing_aid=bool(m.get("value")))
        elif t == "setMediaAssist" and s and m.get("name") in ("calls", "media"):
            s.set_hearing_modes(**{m["name"]: bool(m.get("value"))})
        elif t == "setMicSide" and s and m.get("side") in ("automatic", "left", "right"):
            s.set_mic_side(m["side"])
        elif t == "setPressSpeed" and s and m.get("value") in ("default", "slower", "slowest"):
            s.set_press_speed(m["value"])
        elif t == "setHoldDuration" and s and m.get("value") in ("default", "shorter", "shortest"):
            s.set_hold_duration(m["value"])
        elif t == "setToneVolume" and s and isinstance(m.get("value"), (int, float)):
            s.set_tone_volume(int(m["value"]))
        elif t == "setHostSetting" and m.get("id"):
            if m.get("name") == "duckPercent" and isinstance(m.get("value"), (int, float)):
                self.settings.set(m["id"], "duckPercent", max(10, min(90, int(m["value"]))))
            self._post_main({"type": "hostSettings", "id": m["id"], "host": self._host_json(m["id"]),
                             "handsFreeApplying": False})
        elif t == "setStemModes" and m.get("id"):
            mask = 0
            for name in m.get("modes") or []:
                mask |= STEM_BIT.get(name, 0x80)
            if s and s.mac == m["id"]:
                if not s.set_stem_modes(mask):
                    self._send("devices", self._devices_msg(), force=True)
            elif aap.is_valid_stem_modes(mask):
                self.settings.set(m["id"], "stemModes", mask)
                self._schedule_flush()
        elif t == "setTheme" and m.get("theme") in ("light", "dark", "auto"):
            self.settings.ui["theme"] = m["theme"]
            self.settings.save()
            self._send_prefs_to_popup()
        elif t == "setAccent":
            self.settings.ui["useAccent"] = bool(m.get("value"))
            self.settings.save()
            self._send_prefs_to_popup()
        elif t == "setStartup":
            Settings.set_startup(bool(m.get("value")), self._exec_line())
        elif t == "setLanguage" and isinstance(m.get("code"), str):
            self.settings.ui["language"] = m["code"] or "system"
            self.settings.save()
            self._resolve_locale()
            labels = {"type": "labels", "labels": self.labels, "lang": self.lang, "rtl": self.rtl}
            self._post_main(labels)
            if self.popup:
                self.popup.post(labels)
            self._build_tray_menu()
        elif t == "openLegal":
            path = os.path.join(ROOT, "LICENSE" if m.get("name") == "license" else "THIRD-PARTY-NOTICES.txt")
            self._open(path)
        elif t in ("openBluetoothSettings", "openAddDevice"):
            self._open_bluetooth_settings()
        elif t == "retryBluetooth":
            self.bluez.refresh()
        elif t == "openSupport":
            self._open(SUPPORT_URL)
        elif t == "getStarted":
            self.settings.ui["firstRunDone"] = True
            self.settings.save()
            self.main.set_height(self.settings.ui.get("windowHeight", 720))
        elif t == "fitHeight" and not self.settings.ui.get("firstRunDone"):
            h = m.get("height")
            if isinstance(h, (int, float)) and h > 0:
                self.main.set_height(min(960, max(480, int(h))))
        elif t == "minimize":
            self.main.minimize()
        elif t == "close":
            self.hide_main()
        elif t == "beginDrag":
            self.main.begin_drag()

    # ------------------------------------------------------------------ actions
    def connect(self, mac):
        if not mac or mac in self.connecting:
            return
        if not self.bluez.powered:
            self._toast("bluetoothOff", mac)
            return
        self.connecting.add(mac)
        self.user_disconnected.discard(mac)
        self.attach_failed.discard(mac)
        self.attempts[mac] = 0
        log.info("connect %s requested", mac)
        tries = [0]

        def done(ok, err):
            d = self.bluez.by_mac(mac)
            if not ok and d is not None and d.connected:
                # BlueZ reports an error for one profile (e.g. br-connection-unknown) but the link is up.
                log.info("connect %s: BlueZ said '%s' but the link is up", mac, err)
                ok = True
            if not ok and mac in self.connecting and tries[0] < CONNECT_RETRIES and _transient(err):
                delay = CONNECT_RETRY_DELAYS[min(tries[0], len(CONNECT_RETRY_DELAYS) - 1)]
                tries[0] += 1
                log.info("connect %s: %s -> retry %d in %d s", mac, err, tries[0], delay)

                def again():
                    cur = self.bluez.by_mac(mac)
                    if mac in self.connecting and cur is not None and not cur.connected:
                        self.bluez.connect(mac, done)
                    return False
                GLib.timeout_add_seconds(delay, again)
                return
            if not ok:
                log.warning("connect %s failed: %s", mac, err)
                if mac in self.connecting:
                    self.connecting.discard(mac)
                    self._toast("connectFailed", mac)
                o = self.nearby.offers.get(mac)
                if o and o.state == "connecting":
                    o.state = "failed"
                    self._send_offers()
            elif d is not None and d.connected and self.session is None and mac not in self._retry_timers:
                # link was already up (e.g. AAP gave up earlier): no property change will come, attach now
                self._attach_when_settled(d)
            self._schedule_flush()

        def timeout():
            self._connect_timeouts.pop(mac, None)
            if mac in self.connecting:
                self.connecting.discard(mac)
                if not (self.session and self.session.mac == mac):
                    self._toast("connectFailed", mac)
                self._schedule_flush()
            return False
        self.bluez.connect(mac, done)
        old = self._connect_timeouts.pop(mac, None)
        if old:
            GLib.source_remove(old)
        self._connect_timeouts[mac] = GLib.timeout_add_seconds(45, timeout)
        self._schedule_flush()

    def disconnect(self, mac):
        if not mac:
            return
        log.info("disconnect %s requested", mac)
        self.user_disconnected.add(mac)
        self.connecting.discard(mac)
        self._cancel_retry(mac)
        if self.session and self.session.mac == mac:
            self._drop_session(self.session, "closed")

        def done(ok, err):
            if not ok:
                log.warning("disconnect %s failed: %s", mac, err)
                self._toast("disconnectFailed", mac)
            self._schedule_flush()
        self.bluez.disconnect(mac, done)
        self._schedule_flush()

    def _open(self, target):
        try:
            subprocess.Popen(["xdg-open", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as e:
            log.warning("xdg-open failed: %s", e)

    def _open_bluetooth_settings(self):
        for cmd in (["systemsettings", "kcm_bluetooth"], ["kcmshell6", "kcm_bluetooth"], ["blueman-manager"],
                    ["gnome-control-center", "bluetooth"]):
            try:
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
            except OSError:
                continue

    def _exec_line(self):
        launcher = os.path.expanduser("~/.local/bin/openpods")
        if os.path.exists(launcher):
            return launcher
        return f"{sys.executable} -m openpods"

    def show_main(self):
        was = self.main.shown
        self.main.show()
        if not was and self.main.ready:
            self._last_sent.clear()
            self._post_main({"type": "visibility", "visible": True})
            self._post_main(self._devices_msg())
            self._post_main({"type": "state", "state": self._state_json()})
            self._post_main({"type": "accent", "accent": self.accent})
        self._schedule_flush()

    def hide_main(self):
        w, h = self.main.win.get_size()
        if self.settings.ui.get("firstRunDone") and 480 <= h <= 960 and h != self.settings.ui.get("windowHeight"):
            self.settings.ui["windowHeight"] = h
            self.settings.save()
        self.main.hide()

    def toggle_main(self):
        if self.main.shown:
            self.hide_main()
        else:
            self.show_main()

    def quit(self):
        log.info("quit")
        self.ducker.restore()
        self.hd_mic.shutdown()
        if self.session:
            self.session.close()
        self.bluez.set_discovery(False)
        self.ctl.close()
        Gtk.main_quit()

    # ------------------------------------------------------------------ nearby + popup
    def _wants_scan(self):
        return (self.settings.ui.get("popup", True) and self.bluez.powered and self.session is None
                and any(self.settings.keys(d.mac) for d in self._devices()))

    def _update_scan(self):
        if hasattr(self, "bluez"):
            self.bluez.set_discovery(self._wants_scan())

    def _tick(self):
        # a periodic GLib source dies for good if its callback raises: keep going whatever happens
        try:
            if self.nearby.expire():
                self._send_offers()
                self._schedule_flush()
            self._update_scan()
        except Exception:  # noqa: BLE001
            log.exception("tick failed")
        return True

    def _visible_offers(self):
        attached = self.session.mac if self.session and self.session.state.status == "ready" else None
        return [o for o in self.nearby.offers.values() if o.mac != attached or o.state == "connected"]

    def _on_offers(self):
        self._auto_connect_in_ear()
        self._send_offers()
        self._schedule_flush()

    def _auto_connect_in_ear(self):
        """Case opened near the PC, pods taken out and put in: connect without a click, like an iPhone does.
        Only for an offer that saw the pods in the case first, so AirPods worn with the phone are never grabbed."""
        if not self.settings.ui.get("autoConnectInEar", True) or self.session is not None:
            return
        for o in self.nearby.offers.values():
            if o.state == "offer" and o.in_ear and o.was_in_case and o.mac not in self.connecting:
                log.info("nearby %s: in ear after leaving the case -> connecting automatically", o.mac)
                o.state = "connecting"
                self.connect(o.mac)
                break

    def _send_offers(self):
        offers = self._visible_offers()
        if not offers:
            if self.popup and self.popup.shown:
                self.popup.hide()
            return
        if not self.settings.ui.get("popup", True):
            return
        if self.popup is None:
            self._place_popup_on_primary()
            self.popup = WebWindow(WEB, "popup.html", self._on_popup_message, POPUP_W, 470, POPUP_TITLE, ICON,
                                   popup=True)
        self.popup.post({"type": "offers", "offers": [o.to_json() for o in offers]})
        if not self.popup.shown:
            self.popup.show()

    def _place_popup_on_primary(self):
        """Wayland lets KWin place windows, and it picks the screen under the mouse. A KWin window rule (matched on
        the popup's title) forces it onto the primary monitor (kscreen priority 1), centred horizontally."""
        try:
            outs = json.loads(subprocess.run(["kscreen-doctor", "-j"], capture_output=True, text=True,
                                             timeout=3).stdout)["outputs"]
            outs = [o for o in outs if o.get("enabled") and o.get("connected", True)]
            prim = min(outs, key=lambda o: o.get("priority") or 99)
            scale = prim.get("scale") or 1
            size = prim.get("size") or {}
            w = int(size.get("width", 1920) / scale)
            h = int(size.get("height", 1080) / scale)
            x = prim["pos"]["x"] + (w - POPUP_W) // 2
            y = prim["pos"]["y"] + int(h * 0.26)
        except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError) as e:
            log.info("primary monitor unknown: %s", e)
            return
        pos = f"{x},{y}"
        if getattr(self, "_popup_rule_pos", None) == pos:
            return
        rc = "kwinrulesrc"
        grp = "openpods-popup"
        try:
            for key, val in (("Description", "OpenPods: Popup auf dem primären Monitor"), ("title", POPUP_TITLE),
                             ("titlematch", "1"), ("wmclass", "openpods"), ("wmclassmatch", "1"),
                             ("position", pos), ("positionrule", "2")):
                subprocess.run(["kwriteconfig6", "--file", rc, "--group", grp, "--key", key, val], timeout=3)
            rules = subprocess.run(["kreadconfig6", "--file", rc, "--group", "General", "--key", "rules"],
                                   capture_output=True, text=True, timeout=3).stdout.strip()
            names = [r for r in rules.split(",") if r]
            if grp not in names:
                names.append(grp)
                subprocess.run(["kwriteconfig6", "--file", rc, "--group", "General", "--key", "rules",
                                ",".join(names)], timeout=3)
                subprocess.run(["kwriteconfig6", "--file", rc, "--group", "General", "--key", "count",
                                str(len(names))], timeout=3)
            subprocess.run(["qdbus6", "org.kde.KWin", "/KWin", "reconfigure"], capture_output=True, timeout=3)
            self._popup_rule_pos = pos
            log.info("popup placed on primary monitor %s at %s", prim.get("name"), pos)
        except (OSError, subprocess.SubprocessError) as e:
            log.info("kwin rule failed: %s", e)

    def _on_popup_message(self, m):
        t = m.get("type")
        if t == "ready":
            self.popup.post({"type": "init", "labels": self.labels, "lang": self.lang, "rtl": self.rtl,
                             **self._prefs(), "visible": True,
                             "offers": [o.to_json() for o in self._visible_offers()]})
        elif t == "popupConnect":
            o = self.nearby.offers.get(m.get("id"))
            if o:
                o.state = "connecting"
                self._send_offers()
                self.connect(o.mac)
        elif t == "popupCancel":
            for o in self.nearby.offers.values():
                if o.state in ("connecting", "failed"):
                    o.state = "offer"
                    o.was_in_case = False  # cancelled: no auto-connect until the pods were back in the case
                    self.connecting.discard(o.mac)
            self._send_offers()
        elif t == "popupDismiss":
            self.nearby.dismiss(m.get("ids") or [])
            self._send_offers()
        elif t == "popupSize" and isinstance(m.get("height"), (int, float)):
            log.info("popup content height %s", m.get("height"))
            self.popup.set_height(int(m["height"]))

    def _send_prefs_to_popup(self):
        if self.popup:
            self.popup.post({"type": "prefs", "theme": self.settings.ui.get("theme", "auto"),
                             "useAccent": bool(self.settings.ui.get("useAccent"))})

    # ------------------------------------------------------------------ Plasma applet
    def _applet_json(self):
        """Everything the KDE system tray applet shows, in one small reply (it polls `openpods ctl applet`)."""
        s = self.session
        ready = s is not None and s.state.status == "ready"
        devs = []
        for d in self._devices():
            devs.append({"id": d.mac, "name": d.name, "model": self._model_of(d.mac, d.product_id).name,
                         "conn": self._conn(d)})
        out = {"devices": devs, "attached": s.mac if s else None, "ready": ready,
               "prefs": {"startup": Settings.startup_enabled(), "popup": bool(self.settings.ui.get("popup", True)),
                         "autoConnect": bool(self.settings.ui.get("autoConnectInEar", True)),
                         "hdMic": self.hd_mic.enabled, "theme": self.settings.ui.get("theme", "auto")},
               "mic": {"streaming": self.hd_mic.streaming, "recorders": self.hd_mic.recorders}}
        order = ("noiseCancellation", "adaptive", "transparency", "off")  # the slider runs quiet -> open
        if ready:
            p = self._state_parts(s)
            st = s.state
            modes = []
            for mode in order:
                if mode == "adaptive" and not st.caps & Caps.ADAPTIVE:
                    continue
                if mode == "off" and st.caps & Caps.ALLOW_OFF and st.flag(aap.ALLOW_OFF) is False:
                    continue
                modes.append({"id": mode, "label": self.text(f"nc.{mode}")})
            pod = self._shown(st)
            self._last_battery[s.mac] = (time.time(), p["battery"])
            prev = self.settings.get(s.mac, "lastBattery") or {}
            if prev.get("battery") != p["battery"]:  # persisted so the applet still shows it after a restart
                self.settings.set(s.mac, "lastBattery", {"battery": p["battery"], "t": int(time.time())})
            out.update({"battery": p["battery"], "batterySource": "live", "ear": p["ear"],
                        "listeningMode": p["listeningMode"],
                        "modes": modes if st.caps & Caps.LISTENING_MODE else [],
                        "conversation": pod.get("conversationAwareness"),
                        "earDetection": st.flag(aap.EAR_DETECTION)})
        else:
            # not connected: modes from what OpenPods remembers about the pair, battery from the case's
            # nearby advert (lid open) or the last value seen while connected
            dev = next((d for d in self._devices_msg()["devices"]), None)
            if dev:
                caps = dev.get("caps") or []
                saved = dev.get("saved") or {}
                modes = [{"id": m, "label": self.text(f"nc.{m}")} for m in order
                         if (m != "adaptive" or "adaptive" in caps) and (m != "off" or saved.get("allowOff"))]
                out.update({"modes": modes if "listeningMode" in caps else [],
                            "listeningMode": saved.get("listeningMode")})
                seen = self.nearby.seen.get(dev["id"])
                last = self._last_battery.get(dev["id"])
                if last is None and self.settings.get(dev["id"], "lastBattery"):
                    saved_b = self.settings.get(dev["id"], "lastBattery")
                    last = (saved_b.get("t", time.time()), saved_b.get("battery"))
                if seen:
                    out.update({"battery": seen[1].to_json(), "batterySource": "nearby"})
                elif last:
                    out.update({"battery": last[1], "batterySource": "last",
                                "batteryAge": int(time.time() - last[0])})
        return out

    def _applet_do(self, m):
        t = m.get("type")
        s = self.session
        if t == "setPref":
            key, val = m.get("key"), bool(m.get("value"))
            if key == "startup":
                Settings.set_startup(val, self._exec_line())
            elif key == "popup":
                self.settings.ui["popup"] = val
                self.settings.save()
                self._update_scan()
            elif key == "autoConnect":
                self.settings.ui["autoConnectInEar"] = val
                self.settings.save()
            elif key == "hdMic":
                self.hd_mic.set_enabled(val)
            else:
                return {"error": "unknown pref"}
        elif t == "setListeningMode" and s and m.get("mode") in LISTENING_MODES.values():
            s.set_listening_mode(m["mode"])
        elif t == "setToggle" and s and m.get("name") in ("conversationAwareness", "earDetection"):
            (s.set_conversation_awareness if m["name"] == "conversationAwareness" else s.set_ear_detection)(
                bool(m.get("value")))
        elif t == "connect":
            self.connect(m.get("id") or (self._devices()[0].mac if self._devices() else None))
        elif t == "disconnect":
            self.disconnect(m.get("id") or (s.mac if s else None))
        elif t == "open":
            self.show_main()
            if m.get("page") and self.main.ready:
                self.main.view.evaluate_javascript(f"window.__lpGo && window.__lpGo({json.dumps(m['page'])})", -1,
                                                   None, None, None, None, None)
        elif t == "quit":
            GLib.idle_add(self.quit)
        elif t in ("setListeningMode", "setToggle") and not s:
            return {"error": "not connected"}
        else:
            return {"error": "unknown"}
        self._schedule_flush()
        return {"ok": True}

    # ------------------------------------------------------------------ tray
    # The old AppIndicator tray icon is gone: OpenPods lives in KDE's system tray as a native Plasma applet
    # (plasmoid/, "Status und Benachrichtigungen"), which talks to this process via `openpods ctl applet`.
    def _build_tray(self):
        pass

    def _update_tray(self):
        pass

    def _build_tray_menu(self):
        pass

    # ------------------------------------------------------------------ notifications
    def notify(self, title, body, replace=True):
        try:
            bus = dbus.SessionBus()
            n = dbus.Interface(bus.get_object("org.freedesktop.Notifications", "/org/freedesktop/Notifications"),
                               "org.freedesktop.Notifications")
            self._notify_id = int(n.Notify("OpenPods", dbus.UInt32(self._notify_id if replace else 0),
                                           ICON, title, body, [], {"urgency": dbus.Byte(0)}, 2500))
        except dbus.DBusException as e:
            log.info("notification failed: %s", e)

    def _check_low_battery(self, s: Session):
        st = s.state
        d = self.bluez.by_mac(s.mac)
        for slot, key in ((LEFT, "battery.left"), (RIGHT, "battery.right"), (HEADPHONE, "battery.max")):
            b = st.battery(slot)
            tag = f"{s.mac}:{slot}"
            if b.pct is None or b.status == BAT_CHARGING or b.pct > LOW_BATTERY:
                if b.pct is not None and b.pct > LOW_BATTERY + 5:
                    self._low_notified.discard(tag)
                continue
            if tag not in self._low_notified:
                self._low_notified.add(tag)
                self.notify("OpenPods", self.text("battery.low", name=d.name if d else "AirPods",
                                                  part=self.text(key), pct=b.pct), replace=False)

    # ------------------------------------------------------------------ control commands (CLI / hotkeys)
    def command(self, cmd: str, arg: str | None = None):
        s = self.session
        ready = s is not None and s.state.status == "ready"
        if cmd == "show":
            self.show_main()
        elif cmd == "toggle":
            self.toggle_main()
        elif cmd == "quit":
            GLib.idle_add(self.quit)
        elif cmd == "snapshot" and arg:
            win = self.popup if (arg.endswith("popup.png") and self.popup) else self.main
            win.snapshot(arg)
        elif cmd == "page" and arg and self.main.ready:
            # Debug: navigate the page like a click would (e.g. "windows", "controls").
            self.main.view.evaluate_javascript(f"window.__lpGo && window.__lpGo({json.dumps(arg)})", -1,
                                               None, None, None, None, None)
        elif cmd == "debug.popup":
            # Shows the nearby popup with a demo offer for the first known pair (UI check without the case nearby).
            from .nearby import Offer, PodBatteries
            from .state import Battery, BAT_DISCHARGING
            d = self._devices()[0] if self._devices() else None
            if d:
                import time as _t
                b = PodBatteries(Battery(80, BAT_DISCHARGING), Battery(75, BAT_DISCHARGING), Battery(50, BAT_CHARGING))
                self.nearby.offers[d.mac] = Offer(d.mac, d.name, self._model_of(d.mac, d.product_id).art, b,
                                                  last_seen=_t.monotonic())
                self._send_offers()
        elif cmd == "debug.init":
            # Debug: the page's init message (labels, devices, state) for UI previews outside the running window.
            return self._main_init()
        elif cmd == "applet":
            return self._applet_json()
        elif cmd == "applet.do" and arg:
            # The Plasma applet (plasmoid/) drives OpenPods with the same messages as the page.
            try:
                m = json.loads(arg)
            except ValueError:
                return {"error": "bad json"}
            if not isinstance(m, dict):
                return {"error": "bad json"}
            return self._applet_do(m)
        elif cmd == "applet.do":
            return {"error": "missing argument"}
        elif cmd == "mic.status":
            return self.hd_mic.status()
        elif cmd in ("mic.on", "mic.off"):
            self.hd_mic.set_enabled(cmd == "mic.on")
            return self.hd_mic.status()
        elif cmd == "status":
            return {"attached": s.mac if s else None, "state": self._state_json(),
                    "devices": self._devices_msg()["devices"]}
        elif cmd.startswith("noise."):
            if not ready:
                return {"error": "not connected"}
            mode = cmd.split(".", 1)[1]
            alias = {"nc": "noiseCancellation", "anc": "noiseCancellation", "t": "transparency"}
            mode = alias.get(mode, mode)
            if mode == "cycle":
                stem = self.settings.stem_modes(s.mac)
                cycle = [n for bit, n in STEM_ORDER if stem & bit] or ["noiseCancellation", "transparency"]
                cur = self._shown(s.state).get("listeningMode")
                mode = cycle[(cycle.index(cur) + 1) % len(cycle)] if cur in cycle else cycle[0]
            if mode not in LISTENING_MODES.values():
                return {"error": f"unknown mode {mode}"}
            s.set_listening_mode(mode)
            self.notify(self.text("nc.title"), self.text(f"nc.{mode}"))
            return {"ok": mode}
        elif cmd in ("conversation.on", "conversation.off"):
            if not ready:
                return {"error": "not connected"}
            s.set_conversation_awareness(cmd.endswith("on"))
            self.notify(self.text("features.conversation") if "features.conversation" in self.labels else "OpenPods",
                        "an" if cmd.endswith("on") else "aus")
        elif cmd == "connection.on" or cmd == "connect":
            mac = arg or (self._devices()[0].mac if self._devices() else None)
            self.connect(mac)
        elif cmd == "connection.off" or cmd == "disconnect":
            mac = arg or (s.mac if s else None)
            self.disconnect(mac)
        elif cmd == "connection.toggle":
            if s:
                self.disconnect(s.mac)
            elif self._devices():
                self.connect(self._devices()[0].mac)
        else:
            return {"error": f"unknown command {cmd}"}
        return {"ok": True}
