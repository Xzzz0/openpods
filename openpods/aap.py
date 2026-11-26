"""AAP (Apple Accessory Protocol) packets and the inbound parser.

Port of WPods' Core/Aap.cs (GPL-3.0, (C) fpndev). AAP runs over L2CAP PSM 0x1001.
"""
from __future__ import annotations

from . import models
from .state import (
    DeviceState, Change, Caps, Battery, BAT_CHARGING, BAT_DISCHARGING, BAT_DISCONNECTED, BAT_UNKNOWN,
    EAR_IN, EAR_OUT, EAR_CASE, EAR_DISCONNECTED, EAR_UNKNOWN,
)

PSM = 0x1001
UUID = "74ec2172-0bad-4d01-8f77-997b2be0722a"

# Control-setting ids (opcode 0x09)
MIC_SIDE = 0x01
EAR_DETECTION = 0x0A
LISTENING_MODE = 0x0D
PRESS_SPEED = 0x17
HOLD_DURATION = 0x18
STEM_MODES = 0x1A
ONE_BUD_ANC = 0x1B
TONE_VOLUME = 0x1F
PERSONALIZED_VOLUME = 0x26
CONVERSATION_AWARENESS = 0x28
HEARING_AID = 0x2C
ADAPTIVE_STRENGTH = 0x2E
HEART_RATE_STATE = 0x30
HEARING_ASSIST = 0x33
ALLOW_OFF = 0x34

HEADPHONE_COMPONENT = 0x01
RIGHT_COMPONENT = 0x02
LEFT_COMPONENT = 0x04

MEDIA_ASSIST_LENGTH = 140
MEDIA_ASSIST_CALLS = 10
MEDIA_ASSIST_MEDIA = 11

HEART_RATE_SERVICE = 0x54
HEART_RATE_LEGACY_SERVICE = 0x13

HEADER = bytes([0x04, 0x00, 0x04, 0x00])

HANDSHAKE = bytes([0x00, 0x00, 0x04, 0x00, 0x01, 0x00, 0x02, 0x00] + [0x00] * 8)
FEATURE_FLAGS = bytes([0x04, 0x00, 0x04, 0x00, 0x4D, 0x00, 0xFF, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
REQUEST_KEYS = bytes([0x04, 0x00, 0x04, 0x00, 0x30, 0x00, 0x05, 0x00])

HR_CONNECT_0 = bytes([0x00, 0x00, 0x00, 0x00, 0x01, 0x00, 0x03, 0x00] + [0x00] * 8)
HR_CAPS_0 = bytes([0x04, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00])
HR_CONNECT_4 = bytes([0x00, 0x00, 0x04, 0x00, 0x01, 0x00, 0x03, 0x00] + [0x00] * 8)
HR_CAPS_4 = bytes([0x04, 0x00, 0x04, 0x00, 0x01, 0x00, 0x00])
HR_POWER_ON = bytes([0x04, 0x00, 0x04, 0x00, 0x09, 0x00, 0x30, 0x01, 0x00, 0x00, 0x00])

# Stem modes bitmask (0x1A)
STEM_OFF, STEM_NC, STEM_TRANSPARENCY, STEM_ADAPTIVE = 0x01, 0x02, 0x04, 0x08
DEFAULT_STEM_MODES = STEM_NC | STEM_TRANSPARENCY


def request_notifications(ear_detection: bool) -> bytes:
    return bytes([0x04, 0x00, 0x04, 0x00, 0x0F, 0x00, 0xFF, 0xFF, 0xFF if ear_detection else 0xFD, 0xFF])


def flag(on: bool) -> int:
    return 0x01 if on else 0x02


def setting(id_: int, value: int, extra: int = 0x00) -> bytes:
    return bytes([0x04, 0x00, 0x04, 0x00, 0x09, 0x00, id_, value & 0xFF, extra, 0x00, 0x00])


def tone_volume(volume: int) -> bytes:
    return setting(TONE_VOLUME, volume, 0x50)


def hearing_aid(on: bool) -> bytes:
    return setting(HEARING_AID, 0x01, flag(on))


def media_assist(record: bytes, calls: bool, media: bool) -> bytes:
    p = bytearray(record)
    p[MEDIA_ASSIST_CALLS] = flag(calls)
    p[MEDIA_ASSIST_MEDIA] = flag(media)
    return bytes(p)


def heart_rate_stream(seq: int, service: int, period_us: int) -> bytes:
    return bytes([
        0x04, 0x00, 0x04, 0x00, 0x17, 0x00, 0x00, 0x00, 0x10, 0x00, 0x11, 0x00,
        0x08, seq & 0x7F, 0x10, 0x02, 0x42, 0x0B, 0x08, service, 0x10, 0x02, 0x1A, 0x05, 0x01,
        period_us & 0xFF, (period_us >> 8) & 0xFF, (period_us >> 16) & 0xFF, (period_us >> 24) & 0xFF,
    ])


def is_valid_stem_modes(modes: int) -> bool:
    return (modes & ~0x0F) == 0 and bin(modes).count("1") >= 2


def is_setting(p: bytes) -> bool:
    return len(p) >= 8 and p[:4] == HEADER and p[4] == 0x09 and p[5] == 0x00


def opcode(p: bytes) -> int:
    if len(p) >= 6 and p[:4] == HEADER:
        return p[4] | (p[5] << 8)
    return -1


# ---------------------------------------------------------------- inbound

def apply(p: bytes, st: DeviceState) -> int:
    """Applies one inbound packet to `st`; returns the Change flags."""
    if len(p) < 6 or p[:4] != HEADER:
        return Change.NONE
    op = p[4] | (p[5] << 8)
    if op == 0x04:
        return _apply_battery(p, st) if len(p) >= 7 else Change.NONE
    if op == 0x06:
        return _apply_ear(p, st) if len(p) >= 8 else Change.NONE
    if op == 0x08:
        if len(p) >= 7 and p[6] in (0x01, 0x02):
            return st.set_primary_pod(LEFT_COMPONENT if p[6] == 0x01 else RIGHT_COMPONENT, from_bud_role=True)
        return Change.NONE
    if op == 0x09:
        if len(p) < 8:
            return Change.NONE
        if p[6] == LISTENING_MODE:
            ch = Change.LISTENING_MODE if st.report_listening_mode(p[7]) else Change.NONE
        else:
            ch = apply_setting(p, st)
        return ch | st.observe(_capability_of(p[6], p[7]))
    if op == 0x17:
        return _apply_heart_rate(p, st)
    if op == 0x1D:
        return _apply_device_info(p, st) if len(p) >= 12 else Change.NONE
    if op == 0x4B:
        if len(p) < 10 or st.conversation_level == p[9]:
            return Change.NONE
        st.conversation_level = p[9]
        return Change.CONVERSATION_LEVEL
    if op == 0x53:
        if _is_media_assist_record(p):
            ch = Change.SETTINGS if st.set_media_assist(p) else Change.NONE
            return ch | st.observe(Caps.MEDIA_ASSIST)
        return Change.NONE
    return Change.NONE


def parse_keys(p: bytes):
    """0x31 reply -> (irk, enc_key) or None; returns False when the packet is not a keys reply."""
    if len(p) < 7 or p[:4] != HEADER or (p[4] | (p[5] << 8)) != 0x31:
        return False
    irk = enc = None
    off = 7
    for _ in range(p[6]):
        if off + 4 > len(p):
            break
        typ = p[off] | (p[off + 1] << 8)
        ln = p[off + 2] | (p[off + 3] << 8)
        off += 4
        if ln > len(p) - off:
            break
        key = bytes(p[off:off + ln])
        off += ln
        if ln != 16:
            continue
        if typ == 0x0001:
            irk = key
        elif typ == 0x0004:
            enc = key
    return (irk, enc) if irk and enc else None


def _apply_battery(p: bytes, st: DeviceState) -> int:
    changed = False
    first_pod = 0
    for i in range(p[6]):
        off = 7 + i * 5
        if off + 4 >= len(p):
            break
        level = p[off + 2]
        status = p[off + 3]
        if level == 0xFF:
            b = Battery()
        elif status == 0x04:
            b = Battery(None, BAT_DISCONNECTED)
        elif status in (0x01, 0x05):
            b = Battery(min(level, 100), BAT_CHARGING)
        elif status == 0x02:
            b = Battery(min(level, 100), BAT_DISCHARGING)
        else:
            b = Battery(min(level, 100), BAT_UNKNOWN)
        changed |= st.set_battery(p[off], b)
        if first_pod == 0 and p[off] in (LEFT_COMPONENT, RIGHT_COMPONENT, HEADPHONE_COMPONENT):
            first_pod = p[off]
    ch = Change.BATTERY if changed else Change.NONE
    if first_pod:
        ch |= st.set_primary_pod(first_pod, from_bud_role=False)
    return ch


def _is_media_assist_record(p: bytes) -> bool:
    return (len(p) == MEDIA_ASSIST_LENGTH and p[6] == 0x84 and p[7] == 0x00 and p[8] == 0x02
            and p[9] <= 2 and p[MEDIA_ASSIST_CALLS] <= 2 and p[MEDIA_ASSIST_MEDIA] <= 2)


def _ear(v: int, prev):
    return {0x00: EAR_IN, 0x01: EAR_OUT, 0x02: EAR_CASE, 0x03: EAR_DISCONNECTED, 0x04: prev}.get(v, EAR_UNKNOWN)


def _apply_ear(p: bytes, st: DeviceState) -> int:
    primary = _ear(p[6], st.primary_ear)
    secondary = _ear(p[7], st.secondary_ear)
    if primary == st.primary_ear and secondary == st.secondary_ear:
        return Change.NONE
    st.primary_ear = primary
    st.secondary_ear = secondary
    return Change.EAR


def apply_setting(p: bytes, st: DeviceState) -> int:
    id_, value = p[6], p[7]
    if id_ == LISTENING_MODE:
        return Change.LISTENING_MODE if st.set_setting(id_, value) else Change.NONE
    if id_ == HEARING_AID:
        if len(p) < 9:
            return Change.NONE
        a = st.set_setting(id_, value)
        b = st.set_hearing_aid_enabled(p[8])
        return Change.SETTINGS if (a or b) else Change.NONE
    if id_ in (MIC_SIDE, EAR_DETECTION, PRESS_SPEED, HOLD_DURATION, ONE_BUD_ANC, TONE_VOLUME, PERSONALIZED_VOLUME,
               CONVERSATION_AWARENESS, HEARING_ASSIST, ALLOW_OFF, STEM_MODES):
        return Change.SETTINGS if st.set_setting(id_, value) else Change.NONE
    return Change.NONE


def _capability_of(id_: int, value: int) -> int:
    if id_ == LISTENING_MODE:
        return Caps.LISTENING_MODE | (Caps.ADAPTIVE if value == 4 else 0)
    return {
        ADAPTIVE_STRENGTH: Caps.ADAPTIVE,
        EAR_DETECTION: Caps.EAR_DETECTION,
        CONVERSATION_AWARENESS: Caps.CONVERSATION_AWARENESS,
        ONE_BUD_ANC: Caps.ONE_BUD_ANC,
        PERSONALIZED_VOLUME: Caps.PERSONALIZED_VOLUME,
        ALLOW_OFF: Caps.ALLOW_OFF,
        MIC_SIDE: Caps.MIC_SIDE,
        PRESS_SPEED: Caps.PRESS_SPEED,
        HOLD_DURATION: Caps.HOLD_DURATION,
        TONE_VOLUME: Caps.TONE_VOLUME,
        HEARING_AID: Caps.HEARING_AID,
        HEART_RATE_STATE: Caps.HEART_RATE,
    }.get(id_, 0)


def _apply_device_info(p: bytes, st: DeviceState) -> int:
    parts = bytes(p[11:]).split(b"\x00")
    name = parts[0].decode("utf-8", "replace").strip() if parts else ""
    number = parts[1].decode("utf-8", "replace").strip() if len(parts) > 1 else ""
    if name == st.name and number == st.model_number:
        return Change.NONE
    st.name = name
    st.model_number = number
    model = models.from_model_number(number) or models.UNKNOWN
    st.model_name = model.name
    return Change.IDENTITY | st.set_baseline(model.caps)


# ---- heart rate: 0x17 RTBuddy frame with a protobuf payload

def _read_varint(d: bytes, pos: int):
    value = 0
    shift = 0
    while pos < len(d) and shift < 64:
        c = d[pos]
        pos += 1
        value |= (c & 0x7F) << shift
        if not c & 0x80:
            return value, pos
        shift += 7
    return None, pos


def _read_field(d: bytes, pos: int):
    """-> (ok, pos, number, wire, scalar, bytes)"""
    if pos >= len(d):
        return False, pos, 0, 0, 0, b""
    key, pos = _read_varint(d, pos)
    if key is None:
        return False, pos, 0, 0, 0, b""
    number, wire = key >> 3, key & 7
    if number == 0 or number > 4096:
        return False, pos, 0, 0, 0, b""
    if wire == 0:
        v, pos = _read_varint(d, pos)
        return v is not None, pos, number, wire, v or 0, b""
    if wire == 2:
        ln, pos = _read_varint(d, pos)
        if ln is None or ln > len(d) - pos:
            return False, pos, 0, 0, 0, b""
        return True, pos + ln, number, wire, 0, d[pos:pos + ln]
    if wire in (1, 5):
        size = 8 if wire == 1 else 4
        if len(d) - pos < size:
            return False, pos, 0, 0, 0, b""
        return True, pos + size, number, wire, 0, d[pos:pos + size]
    return False, pos, 0, 0, 0, b""


def _fields(d: bytes):
    pos = 0
    while True:
        ok, pos, n, w, s, b = _read_field(d, pos)
        if not ok:
            return
        yield n, w, s, b


def _is_message(d: bytes) -> bool:
    if len(d) > 16 * 1024:
        return False
    pos = 0
    count = 0
    while pos < len(d):
        count += 1
        if count > 96:
            return False
        ok, pos, *_ = _read_field(d, pos)
        if not ok:
            return False
    return True


def _is_reading(d: bytes):
    bpm, conf = d[1], d[2]
    if bpm < 30 or bpm > 220 or conf < 0x80:
        return None
    a, b, c = d[15], d[16], d[17]
    ok = ((a == 0x10 and b == 0x00 and c in (0x00, 0x80)) or (a == 0x20 and b == 0x00 and c == 0x00)
          or (a == 0x20 and b == 0x80 and c == 0x00) or (a == 0x20 and b == 0x02 and c == 0x80)
          or (a == 0x20 and b == 0x82 and c == 0x80))
    return (bpm, conf) if ok else None


def _find_payload(d: bytes, depth: int):
    if len(d) == 18:
        r = _is_reading(d)
        if r:
            return r
    if depth >= 3 or not _is_message(d):
        return None
    for _, w, _, b in _fields(d):
        if w == 2:
            r = _find_payload(b, depth + 1)
            if r:
                return r
    return None


def _find_command(d: bytes, depth: int):
    if depth > 3 or not _is_message(d):
        return None
    for n, w, s, _ in _fields(d):
        if n == 1 and w == 0:
            if s in (19, 20, 84):
                for n2, w2, _, payload in _fields(d):
                    if n2 == 3 and w2 == 2:
                        r = _find_payload(payload, 0)
                        if r:
                            return r
            break
    for _, w, _, b in _fields(d):
        if w == 2:
            r = _find_command(b, depth + 1)
            if r:
                return r
    return None


def _apply_heart_rate(p: bytes, st: DeviceState) -> int:
    if len(p) < 12 or p[8] != 0x10 or p[9] != 0x00:
        return Change.NONE
    ln = p[10] | (p[11] << 8)
    if ln > len(p) - 12:
        return Change.NONE
    msg = bytes(p[12:12 + ln])
    if not _is_message(msg):
        return Change.NONE
    log_type = 0
    for n, w, s, _ in _fields(msg):
        if n == 2 and w == 0:
            log_type = s
            break
    if log_type not in (1, 3):
        return Change.NONE
    for _, w, _, b in _fields(msg):
        if w == 2:
            r = _find_command(b, 0)
            if r:
                st.heart_rate_bpm, st.heart_rate_confidence = r
                if st.heart_rate != "off":
                    st.heart_rate = "streaming"
                return Change.HEART_RATE | st.observe(Caps.HEART_RATE)
    return Change.NONE
