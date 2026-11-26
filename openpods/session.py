"""One open AAP channel (L2CAP PSM 0x1001) to one AirPods. Port of WPods' Core/AapSession.cs (GPL-3.0).

Threads: a reader thread (blocking recv) and a worker thread (writes, init sequence, delays). Every state change and
callback runs on the GLib main thread (GLib.idle_add), so the rest of the app needs no locks.
"""
from __future__ import annotations

import logging
import queue
import socket
import threading
import time

from gi.repository import GLib

from . import aap, hires_mic, models
from .state import (DeviceState, Change, Caps, LISTENING_MODE_IDS, MIC_SIDE_IDS, PRESS_SPEED_IDS,
                    HOLD_DURATION_IDS)

log = logging.getLogger("aap")

HANDSHAKE_TIMEOUT = 10.0
KEYS_TIMEOUT = 3.0
INITIAL_REPORT_WINDOW = 1.0
INITIAL_REPORT_TIMEOUT = 60.0
HR_FIRST_READING_TIMEOUT = 12.0
HR_ATTEMPTS = 3
HR_PERIOD_US = 1_000_000


def _hex(b: bytes) -> str:
    return " ".join(f"{x:02X}" for x in b)


class Session:
    def __init__(self, mac: str, settings, product_id: int, on_change, on_end):
        self.mac = mac
        self._settings = settings
        self._on_change = on_change
        self._on_end = on_end
        number = settings.get(mac, "modelNumber") or models.model_number_of(product_id)
        baseline = (models.from_model_number(number) or models.UNKNOWN).caps if number else 0
        self.state = DeviceState(settings.get(mac, "caps", 0), baseline, settings.get(mac, "podSettings", {}))
        self.state.model_number = number
        st = self.state
        st.set_setting(aap.EAR_DETECTION, aap.flag(settings.ear_detection(mac)))
        st.set_setting(aap.MIC_SIDE, settings.mic_side(mac))
        st.set_setting(aap.ALLOW_OFF, aap.flag(settings.allow_off(mac)))
        self._saved_reported = st.reported
        self._sock: socket.socket | None = None
        self._jobs: queue.Queue = queue.Queue()
        self._closed = threading.Event()
        self._ended = False
        self._first_packet = threading.Event()
        self._first_setting = threading.Event()
        self._keys_reply = threading.Event()
        self._hr_reading = threading.Event()
        self._hr_generation = 0
        self._stream_seq = 0
        self._send_lock = threading.Lock()
        self._watching_modes = False
        self._resume_heart_rate = False
        self._last_inbound: dict[int, bytes] = {}
        self.end_reason = None
        # HD mic: callable(bytes) that receives 0x58 audio SDUs in the reader thread (set by HiResMic)
        self.audio_sink = None

    # ------------------------------------------------------------------ lifecycle
    def carry_over(self, previous: "Session"):
        self.state.carry_over(previous.state)
        self._resume_heart_rate = previous.state.heart_rate != "off"

    def start(self):
        """Connects in the worker thread; failure ends the session with reason 'connectFailed'."""
        threading.Thread(target=self._worker, name=f"aap-worker {self.mac}", daemon=True).start()

    def close(self):
        if self._closed.is_set():
            return
        log.info("close session %s", self.mac)
        self._closed.set()
        self._jobs.put(None)
        s = self._sock
        if s is not None:
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                s.close()
            except OSError:
                pass

    @property
    def closed(self):
        return self._closed.is_set()

    def _end(self, reason: str):
        """Main thread."""
        if self._ended:
            return
        self._ended = True
        self.end_reason = reason
        self.close()
        self._on_end(self, reason)

    def _post(self, fn, *args):
        def run():
            if not self._ended:
                fn(*args)
            return False
        GLib.idle_add(run)

    # ------------------------------------------------------------------ worker
    def _worker(self):
        try:
            s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_SEQPACKET, socket.BTPROTO_L2CAP)
            s.settimeout(8.0)
            s.connect((self.mac, aap.PSM))
            s.settimeout(None)
        except OSError as e:
            log.warning("L2CAP connect %s failed: %s", self.mac, e)
            GLib.idle_add(lambda: (self._end("connectFailed"), False)[1])
            return
        if self._closed.is_set():
            s.close()
            return
        self._sock = s
        log.info("L2CAP channel to %s open", self.mac)
        threading.Thread(target=self._reader, name=f"aap-reader {self.mac}", daemon=True).start()
        self._jobs.put(self._initialize)
        while True:
            job = self._jobs.get()
            if job is None or self._closed.is_set():
                return
            try:
                job()
            except _Closed:
                return
            except Exception:  # noqa: BLE001 - a failing job must not kill the worker
                log.exception("session job failed")

    def _queue(self, job):
        if not self._closed.is_set():
            self._jobs.put(job)

    def _sleep(self, seconds: float):
        if self._closed.wait(seconds):
            raise _Closed()

    def _wait(self, event: threading.Event, timeout: float) -> bool:
        end = time.monotonic() + timeout
        while not event.is_set():
            left = end - time.monotonic()
            if left <= 0:
                return False
            if self._closed.wait(min(left, 0.1)):
                raise _Closed()
        return True

    def write(self, packet: bytes, log_packet=True) -> bool:
        """Any thread. False when closed or the write failed."""
        s = self._sock
        if s is None or self._closed.is_set():
            return False
        if log_packet:
            log.debug("TX %s", _hex(packet))
        try:
            with self._send_lock:
                s.send(packet)
            return True
        except OSError as e:
            log.warning("write failed: %s", e)
            return False

    # ------------------------------------------------------------------ reader
    def _reader(self):
        s = self._sock
        reason = "failed"
        try:
            while not self._closed.is_set():
                data = s.recv(65536)
                if not data:
                    log.warning("read: end of stream")
                    break
                if hires_mic.is_audio(data):
                    sink = self.audio_sink
                    if sink is not None:
                        sink(bytes(data))
                    continue
                self._first_packet.set()
                if aap.is_setting(data):
                    self._first_setting.set()
                GLib.idle_add(self._on_packet_main, bytes(data))
        except OSError as e:
            if self._closed.is_set():
                reason = "closed"
            else:
                log.warning("read failed: %s", e)
                reason = "linkLost" if getattr(e, "errno", None) in (104, 107, 110, 112, 113) else "failed"
        if self._closed.is_set() and reason == "failed":
            reason = "closed"
        GLib.idle_add(lambda: (self._end(reason), False)[1])

    def _on_packet_main(self, p: bytes):
        if self._ended:
            return False
        op = aap.opcode(p)
        if op == 0x31:
            log.info("RX 0x31 keys reply, %d bytes", len(p))
        elif self._last_inbound.get(op) != p:
            self._last_inbound[op] = p
            log.debug("RX %s", _hex(p))
        keys = aap.parse_keys(p)
        if keys is not False:
            self._keys_reply.set()
            if keys:
                if self._settings.set_keys(self.mac, *keys):
                    log.info("proximity keys stored")
                    self._emit(Change.KEYS)
        change = aap.apply(p, self.state)
        if change:
            self._emit(change)
        if change & Change.HEART_RATE:
            self._hr_reading.set()
        if self.state.initial_report_done and self.state.reported != self._saved_reported:
            self._save_caps()
        if aap.is_setting(p) and p[6] == aap.EAR_DETECTION and p[7] in (1, 2):
            self._settings.set(self.mac, "earDetection", p[7] == 1)
        if aap.is_setting(p) and p[6] == aap.MIC_SIDE and p[7] <= 2:
            self._settings.set(self.mac, "micSide", p[7])
        if change & Change.IDENTITY and self.state.model_number:
            self._settings.set(self.mac, "modelNumber", self.state.model_number)
        return False

    def _emit(self, change: int):
        """Main thread."""
        self._save_pod_settings(change)
        try:
            self._on_change(self, change)
        except Exception:  # noqa: BLE001
            log.exception("change handler failed")

    def _save_pod_settings(self, change):
        if not self.state.initial_report_done:
            return
        if not change & (Change.LISTENING_MODE | Change.SETTINGS | Change.INITIAL_REPORT):
            return
        fallback = self._settings.get(self.mac, "podSettings", {})
        self._settings.set(self.mac, "podSettings", self.state.pod_settings(fallback))

    def _save_caps(self):
        self._saved_reported = self.state.reported
        self._settings.set(self.mac, "caps", self.state.reported)

    # ------------------------------------------------------------------ init (worker thread)
    def _set_status(self, status):
        def main():
            self.state.status = status
            self._emit(Change.CONNECTION)
        self._post(main)

    def _initialize(self):
        log.info("init %s: handshake", self.mac)
        if not self.write(aap.HANDSHAKE) or not self._wait(self._first_packet, HANDSHAKE_TIMEOUT):
            log.warning("init: no answer to the handshake within 10 s")
            self._set_status("noResponse")
            self._post(self._end, "noInitialReport")
            return
        self._sleep(0.1)
        if not self.write(aap.FEATURE_FLAGS) or not self.write(
                aap.request_notifications(self._settings.ear_detection(self.mac))):
            self._post(self._end, "noInitialReport")
            return
        self._set_status("ready")
        threading.Thread(target=self._finish_initial_report, daemon=True).start()
        if self._resume_heart_rate:
            self._post(self.set_heart_rate, True)
        self._sleep(INITIAL_REPORT_WINDOW)
        if self.state.caps & Caps.ALLOW_OFF:
            self._send_setting(aap.setting(aap.ALLOW_OFF, aap.flag(self._settings.allow_off(self.mac))))
        self._write_stem_modes_on_attach()
        self._send_setting(aap.setting(aap.EAR_DETECTION, aap.flag(self._settings.ear_detection(self.mac))))
        self._send_setting(aap.setting(aap.MIC_SIDE, self._settings.mic_side(self.mac)))
        for attempt in range(2):
            self._keys_reply.clear()
            if not self.write(aap.REQUEST_KEYS) or self._wait(self._keys_reply, KEYS_TIMEOUT):
                return
            log.warning("init: no keys reply within 3 s (attempt %d)", attempt + 1)

    def _finish_initial_report(self):
        try:
            if not self._wait(self._first_setting, INITIAL_REPORT_TIMEOUT):
                log.warning("init: no 0x09 setting within 60 s; closing the session")
                self._post(self._end, "noInitialReport")
                return
            self._sleep(INITIAL_REPORT_WINDOW)
        except _Closed:
            return

        def main():
            self.state.initial_report_done = True
            self._emit(Change.INITIAL_REPORT)
            self._save_caps()
        self._post(main)

    def _write_stem_modes_on_attach(self):
        caps = self.state.caps
        if not caps & Caps.LISTENING_MODE:
            return
        modes = self._settings.stem_modes(self.mac)
        if modes & aap.STEM_ADAPTIVE and not caps & Caps.ADAPTIVE:
            modes &= ~aap.STEM_ADAPTIVE
            if not aap.is_valid_stem_modes(modes):
                modes = aap.DEFAULT_STEM_MODES
        drop_off = modes & aap.STEM_OFF and caps & Caps.ALLOW_OFF and self.state.flag(aap.ALLOW_OFF) is False
        if drop_off:
            modes = _without_off(modes)
        if self._send_setting(aap.setting(aap.STEM_MODES, modes)) and drop_off:
            self._post(self._save_stem_modes, modes)

    def _save_stem_modes(self, modes):
        self._settings.set(self.mac, "stemModes", modes)
        self._emit(Change.STEM_MODES)

    def _send_setting(self, packet: bytes) -> bool:
        """Worker thread: writes a 0x09 setting, then applies it like the echo would (optimistic)."""
        if not self.write(packet):
            return False

        def main():
            ch = aap.apply_setting(packet, self.state)
            if ch:
                self._emit(ch)
        self._post(main)
        return True

    def _send_record(self, packet: bytes) -> bool:
        if not self.write(packet):
            return False

        def main():
            ch = aap.apply(packet, self.state)
            if ch:
                self._emit(ch)
        self._post(main)
        return True

    # ------------------------------------------------------------------ commands (main thread)
    def set_listening_mode(self, name: str):
        mode = LISTENING_MODE_IDS[name]
        id_ = self.state.push_listening_mode(mode)
        if not self._watching_modes:
            self._watching_modes = True
            GLib.timeout_add(250, self._watch_listening_modes)
        packet = aap.setting(aap.LISTENING_MODE, mode)

        def job():
            ok = self.write(packet)

            def main():
                if not ok:
                    if self.state.drop_listening_mode(id_):
                        self._emit(Change.LISTENING_MODE)
                elif self.state.is_newest_listening_mode(id_):
                    ch = aap.apply_setting(packet, self.state)
                    if ch:
                        self._emit(ch)
            self._post(main)
        self._queue(job)

    def _watch_listening_modes(self):
        if self._ended:
            self._watching_modes = False
            return False
        changed, wait = self.state.expire_listening_modes()
        if changed:
            self._emit(Change.LISTENING_MODE)
        if wait <= 0:
            self._watching_modes = False
            return False
        return True

    def _setting_job(self, packet, after=None):
        def job():
            if self._send_setting(packet) and after:
                self._post(after)
        self._queue(job)

    def set_ear_detection(self, on: bool):
        self._setting_job(aap.setting(aap.EAR_DETECTION, aap.flag(on)),
                          lambda: self._settings.set(self.mac, "earDetection", on))

    def set_conversation_awareness(self, on: bool):
        self._setting_job(aap.setting(aap.CONVERSATION_AWARENESS, aap.flag(on)))

    def set_personalized_volume(self, on: bool):
        self._setting_job(aap.setting(aap.PERSONALIZED_VOLUME, aap.flag(on)))

    def set_one_bud_anc(self, on: bool):
        self._setting_job(aap.setting(aap.ONE_BUD_ANC, aap.flag(on)))

    def set_allow_off(self, on: bool):
        if not self.state.caps & Caps.ALLOW_OFF:
            return

        def after():
            self._settings.set(self.mac, "allowOff", on)
            if not on:
                stored = self._settings.stem_modes(self.mac)
                if stored & aap.STEM_OFF:
                    modes = _without_off(stored)
                    self._setting_job(aap.setting(aap.STEM_MODES, modes), lambda: self._save_stem_modes(modes))
                if self.state.listening_mode == "off":
                    self.set_listening_mode("transparency")
        self._setting_job(aap.setting(aap.ALLOW_OFF, aap.flag(on)), after)

    def set_mic_side(self, side: str):
        v = MIC_SIDE_IDS[side]
        self._setting_job(aap.setting(aap.MIC_SIDE, v), lambda: self._settings.set(self.mac, "micSide", v))

    def set_press_speed(self, value: str):
        self._setting_job(aap.setting(aap.PRESS_SPEED, PRESS_SPEED_IDS[value]))

    def set_hold_duration(self, value: str):
        self._setting_job(aap.setting(aap.HOLD_DURATION, HOLD_DURATION_IDS[value]))

    def set_tone_volume(self, volume: int):
        self._setting_job(aap.tone_volume(max(0, min(100, int(volume)))))

    def set_stem_modes(self, modes: int) -> bool:
        if not aap.is_valid_stem_modes(modes):
            return False
        caps = self.state.caps
        if not caps & Caps.LISTENING_MODE or (modes & aap.STEM_ADAPTIVE and not caps & Caps.ADAPTIVE):
            return False
        self._setting_job(aap.setting(aap.STEM_MODES, modes), lambda: self._save_stem_modes(modes))
        return True

    def set_hearing_modes(self, hearing_aid=None, calls=None, media=None):
        """Hearing Aid (0x2C) and Media Assist (0x53) share Hearing Assist (0x33), on while any is on."""
        st = self.state
        if st.flag(aap.HEARING_AID) is not True:
            return
        record = st.media_assist_record
        if record is None and (calls is not None or media is not None):
            return
        aid = st.hearing_aid_enabled if hearing_aid is None else hearing_aid
        a_calls = (st.media_assist_on(aap.MEDIA_ASSIST_CALLS) is True) if calls is None else calls
        a_media = (st.media_assist_on(aap.MEDIA_ASSIST_MEDIA) is True) if media is None else media
        packets = []
        if st.hearing_aid_enabled_byte != aap.flag(aid):
            packets.append(aap.hearing_aid(aid))
        if record is not None and (record[aap.MEDIA_ASSIST_CALLS] != aap.flag(a_calls)
                                   or record[aap.MEDIA_ASSIST_MEDIA] != aap.flag(a_media)):
            packets.append(aap.media_assist(record, a_calls, a_media))
        assist = aid or a_calls or a_media
        current = st.flag(aap.HEARING_ASSIST)

        def send_modes():
            for pk in packets:
                ok = self._send_setting(pk) if aap.is_setting(pk) else self._send_record(pk)
                if not ok:
                    return False
            return True

        def job():
            if current == assist:
                send_modes()
                return
            ha = aap.setting(aap.HEARING_ASSIST, aap.flag(assist))
            if assist:
                if send_modes():
                    if packets:
                        self._sleep(0.3)
                    self._send_setting(ha)
            elif self._send_setting(ha):
                if packets:
                    self._sleep(0.3)
                send_modes()
        self._queue(job)

    def set_heart_rate(self, on: bool):
        if on and not self.state.caps & Caps.HEART_RATE:
            return
        self._hr_generation += 1
        gen = self._hr_generation
        if on:
            self._set_hr_status("starting", clear=False)

            def job():
                for _ in range(HR_ATTEMPTS):
                    if gen != self._hr_generation:
                        return
                    self._hr_reading.clear()
                    if not self._send_hr_start():
                        self._post(self._set_hr_status, "failed", False)
                        return
                    if self._wait(self._hr_reading, HR_FIRST_READING_TIMEOUT):
                        return
                if gen == self._hr_generation:
                    self._post(self._set_hr_status, "noReading", False)
            threading.Thread(target=lambda: _run_closed_safe(job), daemon=True).start()
        else:
            self._set_hr_status("off", clear=True)

            def job_off():
                self._stream_seq += 1
                self.write(aap.heart_rate_stream(self._stream_seq, aap.HEART_RATE_SERVICE, 0))
                self._stream_seq += 1
                self.write(aap.heart_rate_stream(self._stream_seq, aap.HEART_RATE_LEGACY_SERVICE, 0))
            self._queue(job_off)

    def _send_hr_start(self) -> bool:
        steps = [(aap.HR_CONNECT_0, 0.18), (aap.HR_CAPS_0, 0.22), (aap.HR_CONNECT_4, 0.18), (aap.HR_CAPS_4, 0.22),
                 (aap.HR_POWER_ON, 0.12)]
        for pk, delay in steps:
            if not self.write(pk):
                return False
            self._sleep(delay)
        self._stream_seq += 1
        if not self.write(aap.heart_rate_stream(self._stream_seq, aap.HEART_RATE_SERVICE, HR_PERIOD_US)):
            return False
        self._sleep(0.12)
        self._stream_seq += 1
        return self.write(aap.heart_rate_stream(self._stream_seq, aap.HEART_RATE_LEGACY_SERVICE, HR_PERIOD_US))

    def _set_hr_status(self, status, clear):
        st = self.state
        if st.heart_rate == status and not clear:
            return
        st.heart_rate = status
        if clear:
            st.heart_rate_bpm = None
        self._emit(Change.HEART_RATE)


class _Closed(Exception):
    pass


def _run_closed_safe(job):
    try:
        job()
    except _Closed:
        pass


def _without_off(modes: int) -> int:
    modes &= ~aap.STEM_OFF
    if not aap.is_valid_stem_modes(modes):
        modes |= aap.STEM_TRANSPARENCY if not modes & aap.STEM_TRANSPARENCY else aap.STEM_NC
    return modes
