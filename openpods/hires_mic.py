"""AirPods hi-res microphone: Apple's AAC-ELD uplink over AAP (opcode 0x58) instead of the Bluetooth HFP mic.

The AirPods stream their microphone as AAC-ELD (mono, 64 kHz, 480 samples = 7.5 ms per access unit) over the same
L2CAP channel (PSM 0x1001) OpenPods already holds. A2DP playback keeps running in full AAC quality meanwhile, so music
and mic work together. Protocol as reverse-engineered by LibrePods (PR #655) and airpods-linux.

Pipeline: AAP 0x58 SDU -> AU demux -> libfdk-aac (ctypes) -> limiter -> FIFO -> PipeWire module-pipe-source
"AirPods Mic (HD)". The stream only runs while an application records from that source.

Threads: Session reader thread calls feed(); a decode thread drains the queue; everything else on the GLib main thread.
"""
from __future__ import annotations

import ctypes
import fcntl
import logging
import os
import queue
import struct
import subprocess
import termios
import threading
import time

import numpy as np
from gi.repository import GLib

log = logging.getLogger("hires")

SOURCE_NAME = "openpods_airpods_hd_mic"
A2DP_SINK_UUID = "0000110b-0000-1000-8000-00805f9b34fb"
A2DP_RETRY_S = 10.0
RESET_MIN_INTERVAL_S = 60.0
START_GRACE_S = 2.5  # after the session is ready, give A2DP time before the first 0x58 START
SOURCE_DESC = "AirPods Mic (HD)"
RATE = 64000
FRAME = 480                      # samples per AAC-ELD access unit (7.5 ms)
ELD_ASC = bytes([0xF8, 0xE6, 0x30, 0x00])  # AOT 39 (ELD), mono, 480-sample frames

START_AUDIO = bytes([0x04, 0x00, 0x04, 0x00, 0x58, 0x00, 0x00, 0x00, 0x09, 0x00, 0x00, 0x01, 0x82, 0x00, 0x00,
                     0x00, 0x04, 0x96, 0x00])
STOP_AUDIO = bytes([0x04, 0x00, 0x04, 0x00, 0x58, 0x00, 0x00, 0x00, 0x02, 0x00, 0x03, 0x01])
TYPE58_HEADER = 22               # then N x [ts:u32 LE][len:u8][au]

MAX_LATENCY_BYTES = RATE * 2 * 60 // 1000   # keep at most ~60 ms queued in the FIFO
STALL_TIMEOUT = 2.5              # no audio for this long while recording -> restart the stream
CHECK_DEBOUNCE_MS = 150


def is_audio(p: bytes) -> bool:
    """0x58 audio SDU (subtype 0x0001)."""
    return len(p) >= 8 and p[0] == 0x04 and p[2] == 0x04 and p[4] == 0x58 and p[5] == 0x00 \
        and p[6] == 0x01 and p[7] == 0x00


def is_control(p: bytes) -> bool:
    return len(p) >= 6 and p[0] == 0x04 and p[2] == 0x04 and p[4] == 0x58 and p[5] == 0x00


def demux(sdu: bytes):
    off = TYPE58_HEADER
    n = len(sdu)
    while off + 5 <= n:
        size = sdu[off + 4]
        start = off + 5
        end = start + size
        if end > n:
            return
        yield sdu[start:end]
        off = end


# ---------------------------------------------------------------------------------------------- decoder
class _StreamInfo(ctypes.Structure):
    _fields_ = [("sampleRate", ctypes.c_int), ("frameSize", ctypes.c_int), ("numChannels", ctypes.c_int)]


class EldDecoder:
    AAC_DEC_OK = 0
    CONCEAL = 1

    def __init__(self):
        lib = ctypes.CDLL("libfdk-aac.so.2")
        lib.aacDecoder_Open.restype = ctypes.c_void_p
        lib.aacDecoder_Open.argtypes = [ctypes.c_int, ctypes.c_uint]
        lib.aacDecoder_ConfigRaw.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
                                             ctypes.POINTER(ctypes.c_uint)]
        lib.aacDecoder_Fill.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
                                        ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint)]
        lib.aacDecoder_DecodeFrame.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_uint]
        lib.aacDecoder_GetStreamInfo.restype = ctypes.POINTER(_StreamInfo)
        lib.aacDecoder_GetStreamInfo.argtypes = [ctypes.c_void_p]
        lib.aacDecoder_Close.argtypes = [ctypes.c_void_p]
        self.lib = lib
        self.h = lib.aacDecoder_Open(0, 1)  # TT_MP4_RAW, one layer
        if not self.h:
            raise RuntimeError("aacDecoder_Open failed")
        asc = ctypes.create_string_buffer(ELD_ASC, len(ELD_ASC))
        ptr = ctypes.c_void_p(ctypes.addressof(asc))
        size = ctypes.c_uint(len(ELD_ASC))
        err = lib.aacDecoder_ConfigRaw(self.h, ctypes.byref(ptr), ctypes.byref(size))
        if err != self.AAC_DEC_OK:
            self.close()
            raise RuntimeError(f"aacDecoder_ConfigRaw failed: 0x{err:x}")
        self._pcm = (ctypes.c_int16 * 4096)()
        self._inbuf = ctypes.create_string_buffer(1024)

    def decode(self, au: bytes) -> bytes | None:
        """One access unit -> s16le mono PCM (None on error)."""
        if not au or len(au) > len(self._inbuf):
            return None
        ctypes.memmove(self._inbuf, au, len(au))
        ptr = ctypes.c_void_p(ctypes.addressof(self._inbuf))
        size = ctypes.c_uint(len(au))
        valid = ctypes.c_uint(len(au))
        if self.lib.aacDecoder_Fill(self.h, ctypes.byref(ptr), ctypes.byref(size), ctypes.byref(valid)):
            return None
        return self._frame(0)

    def conceal(self) -> bytes | None:
        return self._frame(self.CONCEAL)

    def _frame(self, flags) -> bytes | None:
        err = self.lib.aacDecoder_DecodeFrame(self.h, self._pcm, len(self._pcm), flags)
        if err != self.AAC_DEC_OK:
            return None
        info = self.lib.aacDecoder_GetStreamInfo(self.h).contents
        n = info.frameSize * max(1, info.numChannels)
        if n <= 0 or n > len(self._pcm):
            return None
        pcm = bytes(memoryview(self._pcm).cast("B")[:n * 2])
        if info.numChannels > 1:  # never seen, but keep the source mono: first channel
            pcm = np.frombuffer(pcm, "<i2")[::info.numChannels].tobytes()
        return pcm

    def close(self):
        if self.h:
            self.lib.aacDecoder_Close(self.h)
            self.h = None


# ---------------------------------------------------------------------------------------------- limiter
class Limiter:
    """Fixed gain + per-block peak limiter (smoothed) so the HD mic sits at a normal level and never clips."""

    def __init__(self, gain_db=6.0, ceiling=0.89):
        self.gain = 10 ** (gain_db / 20)
        self.ceiling = ceiling
        self.env = 1.0
        self.peak = 0.0

    def process(self, pcm: bytes) -> bytes:
        x = np.frombuffer(pcm, "<i2").astype(np.float32) * (self.gain / 32768.0)
        a = float(np.abs(x).max()) if x.size else 0.0
        target = min(1.0, self.ceiling / a) if a > 0 else 1.0
        # instant attack, ~150 ms release; ramp across the block to avoid zipper noise
        if target < self.env:
            self.env = target
            ramp = np.float32(target)
        else:
            new = self.env + (target - self.env) * 0.05
            ramp = np.linspace(self.env, new, x.size, dtype=np.float32) if x.size else np.float32(new)
            self.env = new
        y = np.clip(x * ramp, -1.0, 1.0)
        self.peak = float(np.abs(y).max()) if y.size else 0.0
        return (y * 32767.0).astype("<i2").tobytes()


# ---------------------------------------------------------------------------------------------- pipewire glue
# pactl/wpctl output is localized (e.g. "Aktives Profil", "Quellen-Eingabe"); the parsers expect English.
C_ENV = {**os.environ, "LC_ALL": "C"}


def _pactl(*args, timeout=4) -> str | None:
    try:
        r = subprocess.run(["pactl", *args], capture_output=True, text=True, timeout=timeout, env=C_ENV)
        return r.stdout if r.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _fifo_path() -> str:
    return os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "openpods-hd-mic.fifo")


def _unload_stale():
    out = _pactl("list", "short", "modules") or ""
    for line in out.splitlines():
        if "module-pipe-source" in line and SOURCE_NAME in line:
            _pactl("unload-module", line.split("\t", 1)[0])


def _source_index() -> int | None:
    out = _pactl("list", "short", "sources") or ""
    for line in out.splitlines():
        cols = line.split("\t")
        if len(cols) > 1 and cols[1] == SOURCE_NAME:
            return int(cols[0])
    return None


def _recorders(source_idx: int) -> list[str]:
    """Clients recording from our source (pactl short format: idx, source, client, driver, spec)."""
    out = _pactl("list", "short", "source-outputs") or ""
    clients = []
    for line in out.splitlines():
        cols = line.split("\t")
        if len(cols) > 2 and cols[1] == str(source_idx):
            clients.append(cols[2])
    if not clients:
        return []
    names = {}
    for line in (_pactl("list", "short", "clients") or "").splitlines():
        cols = line.split("\t")
        if len(cols) > 2:
            names[cols[0]] = cols[2]
    return [names.get(c, c) for c in clients]


# ---------------------------------------------------------------------------------------------- controller
class HiResMic:
    """Owns the virtual source while a session is attached; streams while something records from it."""

    def __init__(self, settings, on_status=None, on_reset=None):
        self.settings = settings
        self.on_status = on_status
        self.on_reset = on_reset  # rebuild the AAP session (fresh handshake)
        self.session = None
        self.module: int | None = None
        self.source_idx: int | None = None
        self.fifo_fd: int | None = None
        self.prev_default: str | None = None
        self.streaming = False
        self.recorders: list[str] = []
        self.level = 0.0
        self.frames = 0
        self.errors = 0
        self.dropped = 0
        self._q: queue.Queue = queue.Queue(maxsize=256)
        self._decode_thread: threading.Thread | None = None
        self._last_sdu = 0.0
        self._subscribe: subprocess.Popen | None = None
        self._check_timer = 0
        self._watchdog = 0
        self._retry_timer = 0
        self._stalls = 0
        self._autoswitch_prev: bool | None = None
        self._a2dp_busy = False
        self._a2dp_last = 0.0
        self._hfp_dirty = False  # card was in HFP during this session -> AAP mic needs a fresh session
        self._ready_at = 0.0
        self._grace_timer = 0
        self._last_reset = 0.0

    @property
    def enabled(self) -> bool:
        return bool(self.settings.ui.get("hiresMic", True))

    # -------------------------------------------------- session lifecycle (main thread)
    def attach(self, session):
        self.session = session
        self._hfp_dirty = False
        self._stalls = 0

    def on_ready(self, session):
        """Session finished its handshake: bring up the virtual mic."""
        if session is not self.session:
            return
        self._ready_at = time.monotonic()
        if not self.enabled or self.module is not None:
            return
        self._open_source()

    def ensure_music_profile(self, session):
        """Called a few seconds after a (re)connect: if the AirPods came up without A2DP or stuck in HFP, fix it
        whether or not the HD mic is on. Only when the HD mic is off and an app uses the old BT mic, HFP is wanted."""
        if session is not self.session:
            return
        prof = self._card_profile()
        if prof is None:
            return
        if prof.startswith("a2dp"):
            return
        if self.module is None and self._bt_mic_in_use():
            return
        self._ensure_a2dp(prof or "off")

    def _bt_mic_in_use(self) -> bool:
        mac = self.session.mac if self.session else ""
        out = _pactl("list", "short", "source-outputs") or ""
        srcs = _pactl("list", "short", "sources") or ""
        ids = {ln.split("\t")[0] for ln in srcs.splitlines() if f"bluez_input.{mac}" in ln}
        return any(ln.split("\t")[1] in ids for ln in out.splitlines() if "\t" in ln)

    def detach(self, session):
        if session is not self.session:
            return
        self._stop_stream(send=False)
        self._close_source()
        self.session = None

    def set_enabled(self, on: bool):
        self.settings.ui["hiresMic"] = bool(on)
        self.settings.save()
        if on and self.session is not None and self.session.state.status == "ready":
            self._open_source()
        elif not on:
            self._stop_stream(send=True)
            self._close_source()
        self._notify()

    def status(self) -> dict:
        return {"enabled": self.enabled, "source": SOURCE_NAME if self.module is not None else None,
                "streaming": self.streaming, "recorders": self.recorders, "level": round(self.level, 3),
                "frames": self.frames, "errors": self.errors, "dropped": self.dropped, "stalls": self._stalls,
                "hfpBlocked": bool(self._autoswitch_prev)}

    # -------------------------------------------------- virtual source
    def _open_source(self):
        _unload_stale()
        path = _fifo_path()
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        props = (f'device.description="{SOURCE_DESC}" device.icon_name=audio-input-microphone '
                 'node.driver=false priority.driver=0 priority.session=3000')
        out = _pactl("load-module", "module-pipe-source", f"source_name={SOURCE_NAME}", f"file={path}",
                     "format=s16le", f"rate={RATE}", "channels=1", "channel_map=mono",
                     f"source_properties={props}")
        if not out or not out.strip().isdigit():
            log.warning("could not load module-pipe-source")
            return
        self.module = int(out.strip())
        # O_RDWR: never blocks on open and the pipe never sees "no writer".
        try:
            self.fifo_fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
        except OSError as e:
            log.warning("open fifo failed: %s", e)
            self._close_source()
            return
        self.source_idx = _source_index()
        log.info("HD mic ready: source %s (#%s)", SOURCE_NAME, self.source_idx)
        if self.settings.ui.get("hiresMicDefault", True):
            cur = (_pactl("get-default-source") or "").strip()
            if cur and cur != SOURCE_NAME:
                self.prev_default = cur
            _pactl("set-default-source", SOURCE_NAME)
        self._block_hfp()
        self._subscribe_events()
        self._schedule_check()
        self._notify()

    # -------------------------------------------------- keep the AirPods out of HFP while the HD mic exists
    def _card(self) -> str | None:
        return f"bluez_card.{self.session.mac.replace(':', '_')}" if self.session else None

    def _card_profile(self) -> str | None:
        card = self._card()
        out = _pactl("list", "cards") or ""
        hit = False
        for line in out.splitlines():
            if line.strip().startswith("Name: "):
                hit = line.strip() == f"Name: {card}"
            elif hit and line.strip().startswith("Active Profile:"):
                return line.split(":", 1)[1].strip()
        return None

    def _block_hfp(self):
        """With the HD mic there is no reason for HFP; an app opening the old BT mic would force the AirPods into
        HFP while the AAP mic stream runs, and that combination drops the link. WirePlumber's headset autoswitch is
        therefore off permanently via ~/.config/wireplumber/wireplumber.conf.d/51-openpods-no-hfp-autoswitch.conf.
        NEVER toggle it at runtime: WirePlumber 0.5.18 segfaults on that (autoswitch-bluetooth-profile.lua:508,
        capture_stream_links nil), every Bluetooth device vanishes and the AirPods come back in HFP -> loop."""
        try:
            out = subprocess.run(["wpctl", "settings", "bluetooth.autoswitch-to-headset-profile"],
                                 capture_output=True, text=True, timeout=3, env=C_ENV).stdout
            self._autoswitch_prev = "false" in out.lower()  # reported as hfpBlocked
            if not self._autoswitch_prev:
                log.warning("WirePlumber headset autoswitch is on (config drop-in missing?) - not touching it at "
                            "runtime, that crashes WirePlumber")
        except (OSError, subprocess.TimeoutExpired) as e:
            log.warning("wpctl failed: %s", e)
        prof = self._card_profile() or ""
        if prof.startswith("headset"):
            self._ensure_a2dp(prof)

    def _a2dp_available(self) -> bool:
        card = self._card()
        out = _pactl("list", "cards") or ""
        hit = False
        for line in out.splitlines():
            t = line.strip()
            if t.startswith("Name: "):
                hit = t == f"Name: {card}"
            elif hit and t.startswith("a2dp-sink") and "available: yes" in t:
                return True
        return False

    def _ensure_a2dp(self, prof: str):
        """Card sits in HFP (mono 16 kHz mSBC, sounds smeary). Happens when a reconnect only brought up HFP because
        the AirPods refused the A2DP connect: then WirePlumber has nothing better than headset-head-unit. Reconnect
        the A2DP sink profile via BlueZ if needed and switch the card back. Runs off the main thread, rate limited."""
        now = time.monotonic()
        if self._a2dp_busy or now - self._a2dp_last < A2DP_RETRY_S:
            return
        self._a2dp_busy = True
        self._a2dp_last = now
        mac = self.session.mac if self.session else None
        card = self._card()
        if not mac or not card:
            self._a2dp_busy = False
            return
        log.warning("card in %s -> restoring A2DP/AAC", prof)

        def work():
            try:
                if not self._a2dp_available():
                    path = "/org/bluez/hci0/dev_" + mac.replace(":", "_")
                    r = subprocess.run(["busctl", "call", "--timeout=15", "org.bluez", path, "org.bluez.Device1",
                                        "ConnectProfile", "s", A2DP_SINK_UUID],
                                       capture_output=True, text=True, timeout=20)
                    log.info("BlueZ ConnectProfile A2DP: %s", "ok" if r.returncode == 0 else r.stderr.strip())
                    for _ in range(20):
                        if self._a2dp_available():
                            break
                        time.sleep(0.25)
                ok = _pactl("set-card-profile", card, "a2dp-sink") is not None
                log.info("card -> a2dp-sink: %s", "ok" if ok else "failed")
            except (OSError, subprocess.TimeoutExpired) as e:
                log.warning("A2DP restore failed: %s", e)
            finally:
                self._a2dp_busy = False
                GLib.idle_add(lambda: (self._schedule_check(), False)[1])
        threading.Thread(target=work, name="a2dp-restore", daemon=True).start()

    def _restore_hfp(self):
        # nothing to restore: the autoswitch setting is static config now (see _block_hfp)
        self._autoswitch_prev = None

    def _close_source(self):
        if self._subscribe is not None:
            try:
                self._subscribe.terminate()
            except OSError:
                pass
            self._subscribe = None
        if self._check_timer:
            GLib.source_remove(self._check_timer)
            self._check_timer = 0
        if self._retry_timer:
            GLib.source_remove(self._retry_timer)
            self._retry_timer = 0
        self._stalls = 0
        self._restore_hfp()
        if self.fifo_fd is not None:
            os.close(self.fifo_fd)
            self.fifo_fd = None
        if self.module is not None:
            if self.prev_default and (_pactl("get-default-source") or "").strip() == SOURCE_NAME:
                _pactl("set-default-source", self.prev_default)
            _pactl("unload-module", str(self.module))
            self.module = None
            log.info("HD mic removed")
        self.prev_default = None
        self.source_idx = None
        self.recorders = []
        try:
            os.unlink(_fifo_path())
        except OSError:
            pass
        self._notify()

    def _subscribe_events(self):
        try:
            p = subprocess.Popen(["pactl", "subscribe"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=C_ENV,
                                 text=True, bufsize=1)
        except OSError as e:
            log.warning("pactl subscribe failed: %s", e)
            return
        self._subscribe = p

        def on_line(src, cond):
            if cond & (GLib.IO_HUP | GLib.IO_ERR):
                return False
            line = p.stdout.readline()
            if not line:
                return False
            if "source-output" in line or "'remove' on source" in line or "on card" in line:
                self._schedule_check()
            return True
        GLib.io_add_watch(p.stdout, GLib.PRIORITY_DEFAULT, GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, on_line)

    def _schedule_check(self):
        if self._check_timer:
            return

        def run():
            self._check_timer = 0
            self._check()
            return False
        self._check_timer = GLib.timeout_add(CHECK_DEBOUNCE_MS, run)

    def _check(self):
        if self.module is None or self.session is None:
            return
        if self.source_idx is None:
            self.source_idx = _source_index()
            if self.source_idx is None:
                return
        recs = _recorders(self.source_idx)
        if recs != self.recorders:
            self.recorders = recs
            self._notify()
        prof = self._card_profile() or ""
        if prof.startswith("headset"):
            self._hfp_dirty = True
            self._ensure_a2dp(prof)
        if recs:
            if prof.startswith("headset"):
                # Someone forced HFP manually: the AAP mic stream must not run alongside SCO.
                if self.streaming:
                    log.warning("card switched to %s -> pausing HD mic", prof)
                    self._stop_stream(send=True)
                return
        if recs and not self.streaming and not self._retry_timer:
            wait = START_GRACE_S - (time.monotonic() - self._ready_at)
            if wait > 0 or not prof.startswith("a2dp"):
                # fresh handoff: let A2DP settle first; STARTing during negotiation made the AirPods drop the link
                if not self._grace_timer:
                    def again():
                        self._grace_timer = 0
                        self._check()
                        return False
                    self._grace_timer = GLib.timeout_add(int(max(wait, 1.0) * 1000), again)
                return
            if self._hfp_dirty and self._request_reset("card was in HFP"):
                return
            log.info("recording from HD mic by %s -> start", ", ".join(recs))
            self._start_stream()
        elif not recs and self.streaming:
            log.info("nobody records from HD mic -> stop")
            self._stop_stream(send=True)

    # -------------------------------------------------- stream
    def _start_stream(self):
        s = self.session
        if s is None or s.closed:
            return
        try:
            dec = EldDecoder()
        except (OSError, RuntimeError) as e:
            log.warning("AAC-ELD decoder unavailable: %s", e)
            return
        self._q = queue.Queue(maxsize=256)
        self._last_sdu = time.monotonic()
        self.frames = self.errors = self.dropped = 0
        self.streaming = True
        self._decode_thread = threading.Thread(target=self._decode_loop, args=(dec, self._q), daemon=True,
                                               name="hd-mic-decode")
        self._decode_thread.start()
        s.audio_sink = self.feed
        if not s.write(START_AUDIO):
            log.warning("0x58 START failed")
            self._stop_stream(send=False)
            return
        log.info("0x58 START sent")
        if not self._watchdog:
            self._watchdog = GLib.timeout_add(1000, self._watch)
        self._notify()

    def _stop_stream(self, send: bool):
        if not self.streaming:
            return
        self.streaming = False
        s = self.session
        if s is not None:
            s.audio_sink = None
            if send and not s.closed:
                s.write(STOP_AUDIO)
                log.info("0x58 STOP sent")
        self._q.put(None)
        self._decode_thread = None
        if self._watchdog:
            GLib.source_remove(self._watchdog)
            self._watchdog = 0
        self.level = 0.0
        log.info("HD mic stream stopped (%d frames, %d errors, %d dropped)", self.frames, self.errors, self.dropped)
        self._notify()

    def _watch(self):
        if not self.streaming:
            self._watchdog = 0
            return False
        if self.frames > 400:  # 3 s of good audio: the stream is healthy again
            self._stalls = 0
        if time.monotonic() - self._last_sdu > STALL_TIMEOUT:
            self._stalls += 1
            delay = min(30, 3 * 2 ** (self._stalls - 1))
            log.warning("HD mic: no audio for %.1f s, retry in %d s (stall #%d)", STALL_TIMEOUT, delay, self._stalls)
            self._watchdog = 0
            dead = self.frames == 0
            self._stop_stream(send=True)
            # The AirPods ignore START after an HFP episode, and repeated START/STOP then makes them drop the link.
            if dead and self._stalls >= 2 and self._request_reset("no audio after START"):
                return False

            def retry():
                self._retry_timer = 0
                self._check()
                return False
            self._retry_timer = GLib.timeout_add_seconds(delay, retry)
            return False
        self._notify()
        return True

    def _request_reset(self, why: str) -> bool:
        now = time.monotonic()
        if self.on_reset is None or self.session is None or now - self._last_reset < RESET_MIN_INTERVAL_S:
            return False
        self._last_reset = now
        log.warning("HD mic: %s -> rebuilding the AAP session", why)
        self.on_reset(self.session)
        return True

    def feed(self, sdu: bytes):
        """Session reader thread."""
        self._last_sdu = time.monotonic()
        try:
            self._q.put_nowait(sdu)
        except queue.Full:
            self.dropped += 1

    def _decode_loop(self, dec: EldDecoder, q: queue.Queue):
        lim = Limiter()
        buf = bytearray(4)
        try:
            while True:
                sdu = q.get()
                if sdu is None:
                    break
                pcm = bytearray()
                for au in demux(sdu):
                    frame = dec.decode(au)
                    if frame is None:
                        self.errors += 1
                        frame = dec.conceal() or bytes(FRAME * 2)
                    else:
                        self.frames += 1
                    pcm += frame
                if not pcm:
                    continue
                out = lim.process(bytes(pcm))
                self.level = max(lim.peak, self.level * 0.85)
                fd = self.fifo_fd
                if fd is None:
                    continue
                try:
                    fcntl.ioctl(fd, termios.FIONREAD, buf)
                    queued = struct.unpack("i", buf)[0]
                    if queued + len(out) > MAX_LATENCY_BYTES:
                        # PipeWire reads slower than the AirPods send (clock drift): drop to keep latency low.
                        self.dropped += 1
                        continue
                    os.write(fd, out)
                except BlockingIOError:
                    self.dropped += 1
                except OSError as e:
                    log.warning("fifo write failed: %s", e)
                    break
        finally:
            dec.close()

    def _notify(self):
        if self.on_status:
            try:
                self.on_status(self.status())
            except Exception:  # noqa: BLE001
                log.exception("status callback failed")

    def shutdown(self):
        self._stop_stream(send=True)
        self._close_source()
