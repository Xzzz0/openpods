"""AirPods model table. Port of WPods' Core/Models.cs (GPL-3.0)."""
from __future__ import annotations

from dataclasses import dataclass

from .state import Caps


@dataclass(frozen=True)
class Model:
    name: str
    art: str
    caps: int
    single_battery: bool


UNKNOWN = Model("AirPods", "airpods", 0, False)

_AP12 = Caps.EAR_DETECTION | Caps.MIC_SIDE
_CONTROLS = Caps.PRESS_SPEED | Caps.HOLD_DURATION | Caps.TONE_VOLUME
_AP3 = _AP12 | _CONTROLS
_AP4 = _AP3 | Caps.PERSONALIZED_VOLUME
_AP4ANC = _AP4 | Caps.LISTENING_MODE | Caps.ADAPTIVE | Caps.CONVERSATION_AWARENESS | Caps.ONE_BUD_ANC
_PRO1 = _AP3 | Caps.LISTENING_MODE | Caps.ONE_BUD_ANC
_PRO2 = _AP4ANC | Caps.ALLOW_OFF | Caps.HEARING_AID | Caps.MEDIA_ASSIST
_MAX1 = Caps.EAR_DETECTION | _CONTROLS | Caps.LISTENING_MODE
_MAX2 = _MAX1 | Caps.ADAPTIVE | Caps.CONVERSATION_AWARENESS | Caps.PERSONALIZED_VOLUME

_TABLE = [
    (Model("AirPods 1", "airpods", _AP12, False), [0x2002], ["A1523", "A1722"]),
    (Model("AirPods 2", "airpods", _AP12, False), [0x200F], ["A2032", "A2031"]),
    (Model("AirPods 3", "airpods", _AP3, False), [0x2013], ["A2565", "A2564"]),
    (Model("AirPods 4", "airpods4", _AP4, False), [0x2019], ["A3053", "A3050", "A3054"]),
    (Model("AirPods 4 (ANC)", "airpods4", _AP4ANC, False), [0x201B], ["A3056", "A3055", "A3057"]),
    (Model("AirPods 5", "airpods4", _AP4ANC, False), [0x2030, 0x2036],
     ["A3531", "A3532", "A3533", "A3439", "A3440", "A3441"]),
    (Model("AirPods Pro 1", "pro", _PRO1, False), [0x200E], ["A2084", "A2083"]),
    (Model("AirPods Pro 2", "pro", _PRO2, False), [0x2014, 0x2024],
     ["A2931", "A2699", "A2698", "A3047", "A3048", "A3049"]),
    (Model("AirPods Pro 3", "pro", _PRO2 | Caps.HEART_RATE, False), [0x2027], ["A3063", "A3064", "A3065"]),
    (Model("AirPods Max 1", "max", _MAX1, True), [0x200A, 0x201F], ["A2096", "A3184"]),
    (Model("AirPods Max 2", "max", _MAX2, True), [], ["A3454"]),
]

_BY_ID: dict[int, Model] = {}
_NUMBER_BY_ID: dict[int, str] = {}
_BY_NUMBER: dict[str, Model] = {}
for _m, _ids, _nums in _TABLE:
    for _i in _ids:
        _BY_ID[_i] = _m
        _NUMBER_BY_ID[_i] = _nums[0]
    for _n in _nums:
        _BY_NUMBER[_n.upper()] = _m


def from_product_id(pid: int) -> Model | None:
    return _BY_ID.get(pid)


def model_number_of(pid: int) -> str | None:
    return _NUMBER_BY_ID.get(pid)


def from_model_number(number: str | None) -> Model | None:
    return _BY_NUMBER.get(number.upper()) if number else None
