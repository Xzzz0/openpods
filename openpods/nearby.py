"""Apple Continuity Proximity Pairing adverts of known AirPods. Port of WPods' Nearby/Proximity.cs (GPL-3.0).

Advert (manufacturer payload after company id 0x004C, 27 bytes, type 0x07): [1] 0x19, [2] 0x01 paired, [3..4] model,
[5] status (bit 5 = left first), [6] pod nibbles, [7] charging flags | case nibble, [8] lid (bit 3 = closed),
[11..26] AES-128-ECB with the pair's ENC_KEY. The random address resolves with the pair's IRK.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from . import models
from .state import Battery, BAT_CHARGING, BAT_DISCHARGING

log = logging.getLogger("nearby")

LENGTH = 27


def _ecb(key: bytes):
    return Cipher(algorithms.AES(key), modes.ECB())


def is_valid(address: str, addr_type: str, data: bytes) -> bool:
    if addr_type != "random" or len(data) != LENGTH or data[0] != 0x07 or data[1] != LENGTH - 2 or data[2] != 0x01:
        return False
    top = int(address.split(":")[0], 16) >> 6
    return top == 0b01  # resolvable private address


def model_id(data: bytes) -> int:
    return data[3] | (data[4] << 8)


def lid_open(data: bytes) -> bool:
    return (data[8] & 0x08) == 0


# Status byte [5] (as reverse-engineered by LibrePods/OpenPods; not yet verified on this pair, logged on change):
# 0x02 / 0x08 = a pod is in an ear, 0x04 = both pods in the case, 0x10 = one pod in the case, 0x40 = this pod in case.
def pods_in_ear(data: bytes) -> bool:
    return (data[5] & 0x0A) != 0


def pods_in_case(data: bytes) -> bool:
    return (data[5] & 0x54) != 0


def resolves(irk: bytes, address: str) -> bool:
    """BT Core Vol 3 Part H 2.2.2: hash (low 24 bits) == ah(IRK, prand). AAP gives the IRK LSB first."""
    a = bytes.fromhex(address.replace(":", ""))  # MSB first
    block = bytes(13) + a[0:3]
    enc = _ecb(irk[::-1]).encryptor()
    out = enc.update(block) + enc.finalize()
    return out[13:16] == a[3:6]


def _from_nibble(n, charging):
    return Battery(n * 10, BAT_CHARGING if charging else BAT_DISCHARGING) if n <= 10 else Battery()


def _from_level(v, prev: Battery):
    if v == 0xFF:
        return Battery()
    level = v & 0x7F
    return Battery(level, BAT_CHARGING if v >= 0x80 else BAT_DISCHARGING) if level <= 100 else prev


def _agree(clear: Battery, dec: Battery):
    if clear.pct is None or dec.pct is None:
        return None
    return abs(dec.pct - clear.pct) <= 10


@dataclass
class PodBatteries:
    left: Battery = field(default_factory=Battery)
    right: Battery = field(default_factory=Battery)
    case: Battery = field(default_factory=Battery)
    headphone: Battery = field(default_factory=Battery)

    def to_json(self):
        return {"left": self.left.to_json(), "right": self.right.to_json(), "case": self.case.to_json(),
                "headphone": self.headphone.to_json()}


def read_batteries(data: bytes, enc_key: bytes, single: bool, prev: PodBatteries) -> PodBatteries | None:
    left_first = (data[5] & 0x20) != 0
    low, high, flags = data[6] & 0x0F, data[6] >> 4, data[7] >> 4
    d = _ecb(enc_key).decryptor()
    plain = d.update(bytes(data[11:27])) + d.finalize()
    if single:
        clear = _from_nibble(low, flags & 1)
        hp = prev.headphone
        for i in (1, 2, 3):
            if (plain[i] & 0x7F) <= 100:
                hp = _from_level(plain[i], prev.headphone)
                break
        return PodBatteries(headphone=hp) if _agree(clear, hp) is True else None
    c_left = _from_nibble(low if left_first else high, flags & (1 if left_first else 2))
    c_right = _from_nibble(high if left_first else low, flags & (2 if left_first else 1))
    c_case = _from_nibble(data[7] & 0x0F, flags & 4)
    left = _from_level(plain[1 if left_first else 2], prev.left)
    right = _from_level(plain[2 if left_first else 1], prev.right)
    case = _from_level(plain[3], prev.case)
    agree = [_agree(c_left, left), _agree(c_right, right), _agree(c_case, case)]
    if False in agree or True not in agree:
        return None
    return PodBatteries(left, right, case)


@dataclass
class Offer:
    mac: str
    name: str
    art: str
    batteries: PodBatteries
    state: str = "offer"  # offer | connecting | connected | failed
    last_seen: float = 0.0
    lid_open: bool = True
    in_ear: bool = False
    was_in_case: bool = False  # pods seen in the case / out of the ear while the lid is open: only then may "in ear" auto-connect
    status: tuple | None = None  # last logged (in_ear, in_case)

    def to_json(self):
        return {"id": self.mac, "name": self.name, "art": self.art, "batteries": self.batteries.to_json(),
                "state": self.state}


class Nearby:
    """Matches adverts to known pairs (by IRK). Calls on_offers() when the visible offers changed."""
    STALE_S = 12

    def __init__(self, settings, known_pairs, on_offers):
        self._settings = settings
        self._known_pairs = known_pairs  # () -> list[(mac, name)]
        self._on_offers = on_offers
        self._addr_cache: dict[str, str | None] = {}  # random address -> mac or None
        self.offers: dict[str, Offer] = {}
        self.seen: dict[str, tuple[float, PodBatteries]] = {}  # mac -> (time, batteries) of any advert
        self.dismissed: set[str] = set()

    def on_advert(self, address: str, addr_type: str, data: bytes, rssi):
        if not is_valid(address, addr_type, data):
            return
        mac = self._resolve(address)
        if mac is None:
            return
        keys = self._settings.keys(mac)
        model = models.from_product_id(model_id(data)) or models.UNKNOWN
        prev = self.seen.get(mac, (0, PodBatteries()))[1]
        b = read_batteries(data, keys[1], model.single_battery, prev)
        if b is None:
            return
        now = time.monotonic()
        self.seen[mac] = (now, b)
        is_open = lid_open(data)
        name = next((n for m, n in self._known_pairs() if m == mac), "AirPods")
        o = self.offers.get(mac)
        changed = False
        if not is_open:
            self.dismissed.discard(mac)
            if o and o.state not in ("connecting",):
                del self.offers[mac]
                changed = True
        elif mac not in self.dismissed:
            if o is None:
                self.offers[mac] = Offer(mac, name, model.art, b, last_seen=now)
                log.info("nearby offer %s (%s)", mac, name)
                changed = True
            else:
                if o.batteries != b:
                    o.batteries = b
                    changed = True
                o.last_seen = now
        o = self.offers.get(mac)
        if o is not None:
            # the two pods advertise in turn with different status bytes: log only when the meaning changes
            meaning = (pods_in_ear(data), pods_in_case(data))
            if meaning != o.status:
                log.info("nearby %s status 0x%02x (in ear %s, in case %s)", mac, data[5], *meaning)
                o.status = meaning
            # Live (AirPods Pro 2, 2026-11-26): lid opened with status 0x00 - no "in case" bit at all - then 0x23 once in
            # the ear. So "seen out of the ear while the lid is open" is the trigger condition; pods already worn with
            # the phone show "in ear" from the first advert and are never grabbed.
            if pods_in_case(data) or not pods_in_ear(data):
                o.was_in_case = True
            if pods_in_ear(data) != o.in_ear:
                o.in_ear = pods_in_ear(data)
                changed = True
        if changed:
            self._on_offers()

    def _resolve(self, address: str) -> str | None:
        if address in self._addr_cache:
            return self._addr_cache[address]
        mac = None
        for m, _ in self._known_pairs():
            keys = self._settings.keys(m)
            if keys and resolves(keys[0], address):
                mac = m
                break
        if len(self._addr_cache) > 512:
            self._addr_cache.clear()
        self._addr_cache[address] = mac
        return mac

    def expire(self) -> bool:
        now = time.monotonic()
        stale = [m for m, o in self.offers.items() if o.state != "connecting" and now - o.last_seen > self.STALE_S]
        for m in stale:
            del self.offers[m]
        for m in [m for m, (t, _) in self.seen.items() if now - t > 60]:
            del self.seen[m]
        return bool(stale)

    def dismiss(self, macs):
        for m in macs:
            self.dismissed.add(m)
            self.offers.pop(m, None)

    def drop(self, mac):
        if self.offers.pop(mac, None):
            self.dismissed.add(mac)
            return True
        return False
