"""Device state of one attached AirPods session. Port of WPods' Core/DeviceState.cs (GPL-3.0)."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

log = logging.getLogger("state")


class Change:
    NONE = 0
    CONNECTION = 1 << 0
    IDENTITY = 1 << 1
    BATTERY = 1 << 2
    EAR = 1 << 3
    LISTENING_MODE = 1 << 4
    SETTINGS = 1 << 5
    CONVERSATION_LEVEL = 1 << 6
    HEART_RATE = 1 << 7
    KEYS = 1 << 8
    CAPS = 1 << 9
    INITIAL_REPORT = 1 << 10
    STEM_MODES = 1 << 11


class Caps:
    LISTENING_MODE = 1 << 0
    ADAPTIVE = 1 << 1
    EAR_DETECTION = 1 << 2
    CONVERSATION_AWARENESS = 1 << 3
    ONE_BUD_ANC = 1 << 4
    PERSONALIZED_VOLUME = 1 << 5
    ALLOW_OFF = 1 << 6
    MIC_SIDE = 1 << 7
    PRESS_SPEED = 1 << 8
    HOLD_DURATION = 1 << 9
    TONE_VOLUME = 1 << 10
    HEARING_AID = 1 << 11
    HEART_RATE = 1 << 12
    MEDIA_ASSIST = 1 << 13

    # Protocol names in enum order (WPods' MessageWriter.WriteCaps).
    NAMES = [
        (LISTENING_MODE, "listeningMode"), (ADAPTIVE, "adaptive"), (EAR_DETECTION, "earDetection"),
        (CONVERSATION_AWARENESS, "conversationAwareness"), (ONE_BUD_ANC, "oneBudAnc"),
        (PERSONALIZED_VOLUME, "personalizedVolume"), (ALLOW_OFF, "allowOff"), (MIC_SIDE, "micSide"),
        (PRESS_SPEED, "pressSpeed"), (HOLD_DURATION, "holdDuration"), (TONE_VOLUME, "toneVolume"),
        (HEARING_AID, "hearingAid"), (HEART_RATE, "heartRate"), (MEDIA_ASSIST, "mediaAssist"),
    ]


BAT_UNKNOWN, BAT_CHARGING, BAT_DISCHARGING, BAT_DISCONNECTED = range(4)
EAR_IN, EAR_OUT, EAR_CASE, EAR_DISCONNECTED, EAR_UNKNOWN = "inEar", "out", "inCase", "disconnected", None

LISTENING_MODES = {1: "off", 2: "noiseCancellation", 3: "transparency", 4: "adaptive"}
LISTENING_MODE_IDS = {v: k for k, v in LISTENING_MODES.items()}
MIC_SIDES = {0: "automatic", 1: "right", 2: "left"}
MIC_SIDE_IDS = {v: k for k, v in MIC_SIDES.items()}
PRESS_SPEEDS = {0: "default", 1: "slower", 2: "slowest"}
PRESS_SPEED_IDS = {v: k for k, v in PRESS_SPEEDS.items()}
HOLD_DURATIONS = {0: "default", 1: "shorter", 2: "shortest"}
HOLD_DURATION_IDS = {v: k for k, v in HOLD_DURATIONS.items()}
STEM_ORDER = [(0x01, "off"), (0x02, "noiseCancellation"), (0x04, "transparency"), (0x08, "adaptive")]

POD_SETTING_KEYS = ["listeningMode", "conversationAwareness", "personalizedVolume", "oneBudAnc", "pressSpeed",
                    "holdDuration", "toneVolume", "hearingAidEnrolled", "hearingAidEnabled", "mediaAssistCalls",
                    "mediaAssistMedia"]


@dataclass(frozen=True)
class Battery:
    pct: int | None = None
    status: int = BAT_UNKNOWN

    def to_json(self):
        if self.pct is None:
            return None
        return {"pct": self.pct, "charging": self.status == BAT_CHARGING}


NOT_REPORTED = 0xFF
LEFT, RIGHT, CASE, HEADPHONE = range(4)
LISTENING_MODE_QUIET_S = 3.0


class DeviceState:
    def __init__(self, remembered: int, baseline: int, remembered_settings: dict):
        self.status = "initializing"  # initializing | ready | noResponse
        self.reported = remembered
        self._baseline = baseline
        self.caps = remembered | baseline
        self.initial_report_done = False
        self.remembered_settings = dict(remembered_settings or {})
        self.name: str | None = None
        self.model_number: str | None = None
        self.model_name: str | None = None
        self._settings = [NOT_REPORTED] * 0x40
        self._batteries = [Battery()] * 4
        self._hearing_aid_enabled = NOT_REPORTED
        self._media_assist: bytes | None = None
        self._primary_pod = 0
        self._bud_role_seen = False
        self._sent_modes: list[tuple[int, int]] = []
        self._sent_mode_id = 0
        self._sent_modes_until = 0.0
        self._device_mode = 0
        self._battery_reported = False
        self._previous: DeviceState | None = None
        self.primary_ear = None
        self.secondary_ear = None
        self.conversation_level: int | None = None
        self.heart_rate = "off"
        self.heart_rate_bpm: int | None = None
        self.heart_rate_confidence = 0

    # ---- reads
    def battery(self, slot):
        return self._batteries[slot]

    @property
    def left_ear(self):
        from . import aap
        return {aap.LEFT_COMPONENT: self.primary_ear, aap.RIGHT_COMPONENT: self.secondary_ear}.get(self._primary_pod)

    @property
    def right_ear(self):
        from . import aap
        return {aap.LEFT_COMPONENT: self.secondary_ear, aap.RIGHT_COMPONENT: self.primary_ear}.get(self._primary_pod)

    def raw(self, id_):
        return self._settings[id_]

    def flag(self, id_):
        v = self._settings[id_]
        return None if v == NOT_REPORTED else v == 1

    @property
    def listening_mode(self):
        from . import aap
        return LISTENING_MODES.get(self._settings[aap.LISTENING_MODE])

    @property
    def mic_side(self):
        from . import aap
        return MIC_SIDES.get(self._settings[aap.MIC_SIDE])

    @property
    def tone_volume(self):
        from . import aap
        v = self._settings[aap.TONE_VOLUME]
        return None if v == NOT_REPORTED else min(v, 100)

    @property
    def hearing_aid_enabled(self):
        from . import aap
        return self._hearing_aid_enabled == 1 and self._settings[aap.HEARING_ASSIST] == 1

    @property
    def hearing_aid_enabled_byte(self):
        return self._hearing_aid_enabled

    @property
    def media_assist_record(self):
        return self._media_assist

    def media_assist_on(self, offset):
        from . import aap
        if self._media_assist is None:
            return None
        return self._media_assist[offset] == 1 and self._settings[aap.HEARING_ASSIST] == 1

    def pod_settings(self, fallback: dict | None = None) -> dict:
        """Pod-saved settings this session reported, the rest from `fallback`."""
        from . import aap
        fb = fallback or {}
        enrolled = self.flag(aap.HEARING_AID)
        own = {
            "listeningMode": self.listening_mode,
            "conversationAwareness": self.flag(aap.CONVERSATION_AWARENESS),
            "personalizedVolume": self.flag(aap.PERSONALIZED_VOLUME),
            "oneBudAnc": self.flag(aap.ONE_BUD_ANC),
            "pressSpeed": PRESS_SPEEDS.get(self._settings[aap.PRESS_SPEED]),
            "holdDuration": HOLD_DURATIONS.get(self._settings[aap.HOLD_DURATION]),
            "toneVolume": self.tone_volume,
            "hearingAidEnrolled": enrolled,
            "mediaAssistCalls": self.media_assist_on(aap.MEDIA_ASSIST_CALLS),
            "mediaAssistMedia": self.media_assist_on(aap.MEDIA_ASSIST_MEDIA),
        }
        out = {k: (v if v is not None else fb.get(k)) for k, v in own.items()}
        out["hearingAidEnabled"] = bool(fb.get("hearingAidEnabled", False)) if enrolled is None else self.hearing_aid_enabled
        return out

    @property
    def battery_source(self):
        if self._battery_reported or self._previous is None:
            return self
        return self._previous.battery_source

    @property
    def ear_source(self):
        if self.left_ear is not None or self.right_ear is not None or self._previous is None:
            return self
        return self._previous.ear_source

    def carry_over(self, previous: "DeviceState"):
        self._previous = previous

    # ---- writes
    def observe(self, caps: int) -> int:
        self.reported |= caps
        return self._update_caps()

    def set_baseline(self, baseline: int) -> int:
        self._baseline = baseline
        return self._update_caps()

    def _update_caps(self) -> int:
        caps = self.reported | self._baseline
        if caps == self.caps:
            return Change.NONE
        self.caps = caps
        return Change.CAPS

    def set_setting(self, id_, value) -> bool:
        if self._settings[id_] == value:
            return False
        self._settings[id_] = value
        return True

    def set_hearing_aid_enabled(self, value) -> bool:
        if self._hearing_aid_enabled == value:
            return False
        self._hearing_aid_enabled = value
        return True

    def set_media_assist(self, record: bytes) -> bool:
        if self._media_assist == bytes(record):
            return False
        self._media_assist = bytes(record)
        return True

    def set_primary_pod(self, component: int, from_bud_role: bool) -> int:
        if not from_bud_role and self._bud_role_seen:
            return Change.NONE
        self._bud_role_seen |= from_bud_role
        if component == self._primary_pod:
            return Change.NONE
        left, right = self.left_ear, self.right_ear
        self._primary_pod = component
        return Change.NONE if (left == self.left_ear and right == self.right_ear) else Change.EAR

    def set_battery(self, component: int, b: Battery) -> bool:
        slot = {0x01: HEADPHONE, 0x02: RIGHT, 0x04: LEFT, 0x08: CASE}.get(component)
        if slot is None:
            return False
        first = not self._battery_reported
        self._battery_reported = True
        if self._batteries[slot] == b and not first:
            return False
        self._batteries[slot] = b
        return True

    # ---- listening mode echo handling (no flicker while requests are in flight)
    def push_listening_mode(self, mode: int) -> int:
        self._sent_mode_id += 1
        self._sent_modes.append((self._sent_mode_id, mode))
        self._sent_modes_until = time.monotonic() + LISTENING_MODE_QUIET_S
        return self._sent_mode_id

    def is_newest_listening_mode(self, id_) -> bool:
        return bool(self._sent_modes) and self._sent_modes[-1][0] == id_

    def drop_listening_mode(self, id_) -> bool:
        from . import aap
        idx = next((i for i, e in enumerate(self._sent_modes) if e[0] == id_), -1)
        if idx < 0:
            return False
        del self._sent_modes[idx]
        shown = self._sent_modes[-1][1] if self._sent_modes else self._device_mode
        return shown != 0 and self.set_setting(aap.LISTENING_MODE, shown)

    def report_listening_mode(self, value) -> bool:
        from . import aap
        self._device_mode = value
        if self._sent_modes:
            idx = next((i for i, e in enumerate(self._sent_modes) if e[1] == value), -1)
            if idx >= 0:
                del self._sent_modes[:idx + 1]
            if self._sent_modes:
                self._sent_modes_until = time.monotonic() + LISTENING_MODE_QUIET_S
                return False
        return self.set_setting(aap.LISTENING_MODE, value)

    def expire_listening_modes(self):
        """-> (changed, wait_seconds)"""
        from . import aap
        if not self._sent_modes:
            return False, 0
        left = self._sent_modes_until - time.monotonic()
        if left > 0:
            return False, left
        self._sent_modes.clear()
        return (self._device_mode != 0 and self.set_setting(aap.LISTENING_MODE, self._device_mode)), 0
