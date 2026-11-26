"""Persistent settings: ~/.config/openpods/settings.json (atomic writes)."""
from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile

from . import aap

log = logging.getLogger("settings")

CONFIG_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "openpods")
PATH = os.path.join(CONFIG_DIR, "settings.json")
AUTOSTART = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "autostart",
                         "openpods.desktop")

DEFAULT_UI = {"theme": "auto", "useAccent": True, "language": "system", "firstRunDone": False,
              "windowHeight": 720, "popup": True, "selected": None}
DEFAULT_DUCK = 40


LEGACY_PATH = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "linpods",
                           "settings.json")


def _migrate_from_linpods():
    """The project was called LinPods until 2026-11-26: take over its settings (pairing keys, device settings) once.
    The old file stays where it is."""
    if os.path.exists(PATH) or not os.path.exists(LEGACY_PATH):
        return
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        shutil.copy2(LEGACY_PATH, PATH)
        log.info("settings taken over from %s", LEGACY_PATH)
    except OSError as e:
        log.warning("could not take over old LinPods settings: %s", e)


class Settings:
    def __init__(self):
        self.ui = dict(DEFAULT_UI)
        self.devices: dict[str, dict] = {}
        self._load()

    def _load(self):
        _migrate_from_linpods()
        try:
            with open(PATH, encoding="utf-8") as f:
                data = json.load(f)
            self.ui.update(data.get("ui") or {})
            self.devices = data.get("devices") or {}
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as e:
            log.warning("settings unreadable (%s), starting fresh; old file kept as .bad", e)
            try:
                os.replace(PATH, PATH + ".bad")
            except OSError:
                pass

    def save(self):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=CONFIG_DIR, prefix=".settings.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"ui": self.ui, "devices": self.devices}, f, indent=1, ensure_ascii=False)
            os.replace(tmp, PATH)
        except OSError as e:
            log.error("settings not saved: %s", e)
            try:
                os.unlink(tmp)
            except OSError:
                pass

    # ---- per device
    def dev(self, mac: str) -> dict:
        return self.devices.setdefault(mac, {})

    def get(self, mac: str, key: str, default=None):
        return self.devices.get(mac, {}).get(key, default)

    def set(self, mac: str, key: str, value, save=True) -> bool:
        d = self.dev(mac)
        if d.get(key) == value:
            return False
        d[key] = value
        if save:
            self.save()
        return True

    def ear_detection(self, mac):
        return self.get(mac, "earDetection", True)

    def allow_off(self, mac):
        return self.get(mac, "allowOff", False)

    def mic_side(self, mac):
        return self.get(mac, "micSide", 0)

    def stem_modes(self, mac):
        return self.get(mac, "stemModes", aap.DEFAULT_STEM_MODES)

    def duck_percent(self, mac):
        return self.get(mac, "duckPercent", DEFAULT_DUCK)

    def keys(self, mac):
        k = self.get(mac, "keys")
        if not k:
            return None
        try:
            return bytes.fromhex(k["irk"]), bytes.fromhex(k["enc"])
        except (KeyError, ValueError):
            return None

    def set_keys(self, mac, irk: bytes, enc: bytes) -> bool:
        return self.set(mac, "keys", {"irk": irk.hex(), "enc": enc.hex()})

    # ---- autostart
    @staticmethod
    def startup_enabled() -> bool:
        return os.path.exists(AUTOSTART)

    @staticmethod
    def set_startup(on: bool, exec_line: str):
        if on:
            os.makedirs(os.path.dirname(AUTOSTART), exist_ok=True)
            with open(AUTOSTART, "w", encoding="utf-8") as f:
                f.write("[Desktop Entry]\nType=Application\nName=OpenPods\nComment=AirPods controls\n"
                        f"Exec={exec_line} --hidden\nIcon=openpods\nX-GNOME-Autostart-enabled=true\n")
        else:
            try:
                os.unlink(AUTOSTART)
            except FileNotFoundError:
                pass
