"""BlueZ over D-Bus: paired AirPods, their connection state, connect/disconnect, LE discovery for nearby adverts."""
from __future__ import annotations

import logging
import re
import time

import dbus

from . import aap

log = logging.getLogger("bluez")

BUS = "org.bluez"
DEVICE = "org.bluez.Device1"
ADAPTER = "org.bluez.Adapter1"
PROPS = "org.freedesktop.DBus.Properties"
OM = "org.freedesktop.DBus.ObjectManager"
APPLE = 0x004C


class Device:
    def __init__(self, path: str, props: dict):
        self.path = path
        self.mac = str(props.get("Address", ""))
        self.name = str(props.get("Alias") or props.get("Name") or "AirPods")
        self.connected = bool(props.get("Connected", False))
        self.services_resolved = bool(props.get("ServicesResolved", False))
        self.connected_at = 0.0  # monotonic time the link came up while we watched (0 = was already up)
        self.resolved_at = 0.0
        self.paired = bool(props.get("Paired", False))
        uuids = [str(u).lower() for u in props.get("UUIDs", [])]
        self.is_airpods = aap.UUID in uuids
        m = re.match(r"bluetooth:v004Cp([0-9A-Fa-f]{4})", str(props.get("Modalias", "")))
        self.product_id = int(m.group(1), 16) if m else 0

    def update(self, changed: dict):
        if "Connected" in changed:
            now_up = bool(changed["Connected"])
            if now_up and not self.connected:
                self.connected_at = time.monotonic()
            self.connected = now_up
            if not now_up:
                self.services_resolved = False
        if "ServicesResolved" in changed:
            res = bool(changed["ServicesResolved"])
            if res and not self.services_resolved:
                self.resolved_at = time.monotonic()
            self.services_resolved = res
        if "Alias" in changed:
            self.name = str(changed["Alias"])
        if "Paired" in changed:
            self.paired = bool(changed["Paired"])
        if "UUIDs" in changed:
            self.is_airpods = aap.UUID in [str(u).lower() for u in changed["UUIDs"]]


class BlueZ:
    """Callbacks: on_devices() when the AirPods list or a connection changed; on_advert(addr, addr_type, data, rssi)
    for Apple manufacturer data of LE devices; on_adapter(powered)."""

    def __init__(self, on_devices, on_advert, on_adapter):
        self.bus = dbus.SystemBus()
        self._on_devices = on_devices
        self._on_advert = on_advert
        self._on_adapter = on_adapter
        self.devices: dict[str, Device] = {}  # by path, AirPods only
        self.adapter_path: str | None = None
        self.powered = False
        self._le: dict[str, tuple[str, str]] = {}  # path -> (address, type) of LE devices
        self._discovering = False
        self.bus.add_signal_receiver(self._props_changed, dbus_interface=PROPS, signal_name="PropertiesChanged",
                                     bus_name=BUS, path_keyword="path")
        self.bus.add_signal_receiver(self._added, dbus_interface=OM, signal_name="InterfacesAdded", bus_name=BUS)
        self.bus.add_signal_receiver(self._removed, dbus_interface=OM, signal_name="InterfacesRemoved", bus_name=BUS)
        self.refresh()

    def refresh(self):
        try:
            om = dbus.Interface(self.bus.get_object(BUS, "/"), OM)
            objects = om.GetManagedObjects()
        except dbus.DBusException as e:
            log.warning("BlueZ not reachable: %s", e)
            self.powered = False
            self._on_adapter(False)
            return
        self.devices.clear()
        for path, ifaces in objects.items():
            if ADAPTER in ifaces and self.adapter_path is None:
                self.adapter_path = str(path)
                self.powered = bool(ifaces[ADAPTER].get("Powered", False))
            if DEVICE in ifaces:
                self._track(str(path), ifaces[DEVICE])
        self._on_adapter(self.powered)
        self._on_devices()

    def _track(self, path, props):
        d = Device(path, props)
        if d.is_airpods and d.paired:
            self.devices[path] = d
        if str(props.get("AddressType", "public")) == "random":
            self._le[path] = (d.mac, "random")
            md = props.get("ManufacturerData")
            if md:
                self._advert(path, md, props.get("RSSI"))

    def _added(self, path, ifaces):
        if DEVICE in ifaces:
            before = len(self.devices)
            self._track(str(path), ifaces[DEVICE])
            if len(self.devices) != before:
                self._on_devices()
        if ADAPTER in ifaces and self.adapter_path is None:
            self.refresh()

    def _removed(self, path, ifaces):
        path = str(path)
        self._le.pop(path, None)
        if DEVICE in ifaces and self.devices.pop(path, None):
            self._on_devices()
        if ADAPTER in ifaces and path == self.adapter_path:
            self.adapter_path = None
            self.powered = False
            self._on_adapter(False)

    def _props_changed(self, iface, changed, invalidated, path=None):
        path = str(path)
        if iface == ADAPTER and path == self.adapter_path:
            if "Powered" in changed:
                self.powered = bool(changed["Powered"])
                self._on_adapter(self.powered)
            if "Discovering" in changed:
                self._discovering = bool(changed["Discovering"])
            return
        if iface != DEVICE:
            return
        if path in self.devices:
            d = self.devices[path]
            d.update(changed)
            if not d.paired:
                del self.devices[path]
            if {"Connected", "Alias", "Paired", "ServicesResolved"} & set(changed.keys()):
                self._on_devices()
        elif "Paired" in changed or "UUIDs" in changed:
            try:
                props = dbus.Interface(self.bus.get_object(BUS, path), PROPS).GetAll(DEVICE)
            except dbus.DBusException:
                return
            self._track(path, props)
            if path in self.devices:
                self._on_devices()
        if "ManufacturerData" in changed and path in self._le:
            self._advert(path, changed["ManufacturerData"], changed.get("RSSI"))

    def _advert(self, path, md, rssi):
        data = md.get(dbus.UInt16(APPLE)) if hasattr(md, "get") else None
        if data is None:
            for k, v in md.items():
                if int(k) == APPLE:
                    data = v
        if data is None:
            return
        addr, typ = self._le[path]
        self._on_advert(addr, typ, bytes(bytearray(data)), int(rssi) if rssi is not None else None)

    # ---- actions
    def by_mac(self, mac: str) -> Device | None:
        return next((d for d in self.devices.values() if d.mac.upper() == mac.upper()), None)

    def connect(self, mac: str, on_done):
        d = self.by_mac(mac)
        if not d:
            on_done(False, "unknown device")
            return
        dev = dbus.Interface(self.bus.get_object(BUS, d.path), DEVICE)
        dev.Connect(reply_handler=lambda: on_done(True, None),
                    error_handler=lambda e: on_done(False, str(e)), timeout=40)

    def disconnect(self, mac: str, on_done=None):
        d = self.by_mac(mac)
        if not d:
            return
        dev = dbus.Interface(self.bus.get_object(BUS, d.path), DEVICE)
        dev.Disconnect(reply_handler=lambda: on_done and on_done(True, None),
                       error_handler=lambda e: on_done and on_done(False, str(e)), timeout=20)

    def set_discovery(self, on: bool):
        if not self.adapter_path or not self.powered:
            return
        ad = dbus.Interface(self.bus.get_object(BUS, self.adapter_path), ADAPTER)
        try:
            if on and not self._discovering:
                ad.SetDiscoveryFilter(dbus.Dictionary({"Transport": "le", "DuplicateData": dbus.Boolean(True)},
                                                      signature="sv"))
                ad.StartDiscovery()
                self._discovering = True
                log.info("LE scan started")
            elif not on and self._discovering:
                ad.StopDiscovery()
                self._discovering = False
                log.info("LE scan stopped")
        except dbus.DBusException as e:
            msg = str(e)
            if "InProgress" in msg or "Already" in msg:
                self._discovering = on
            elif "NotReady" not in msg and "Failed" not in msg:
                log.warning("discovery %s: %s", "start" if on else "stop", msg)
            else:
                log.info("discovery %s: %s", "start" if on else "stop", msg)
