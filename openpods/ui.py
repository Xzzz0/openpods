"""GTK windows hosting the WPods web UI in WebKitGTK, with a bridge that mimics WebView2's chrome.webview."""
from __future__ import annotations

import colorsys
import configparser
import json
import logging
import os

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import Gdk, Gtk, WebKit2  # noqa: E402

import dbus  # noqa: E402

log = logging.getLogger("ui")

BRIDGE = """
(() => {
  const listeners = [];
  window.chrome = window.chrome || {};
  window.chrome.webview = {
    postMessage: (m) => window.webkit.messageHandlers.openpods.postMessage(JSON.stringify(m)),
    addEventListener: (type, l) => { if (type === 'message') listeners.push(l); },
  };
  window.__lp = (m) => { for (const l of listeners) { try { l({ data: m }); } catch (e) { console.error(e); } } };
})();
"""


_CSS_DONE = False


def _install_css():
    global _CSS_DONE
    if _CSS_DONE:
        return
    _CSS_DONE = True
    css = Gtk.CssProvider()
    css.load_from_data(b"""
        .titlebar.lp-empty-titlebar, .lp-empty-titlebar { min-height: 0; padding: 0; margin: 0; border: 0;
            background: transparent; box-shadow: none; }
        decoration { border-radius: 10px; }
    """)
    Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), css,
                                             Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 10)


class WebWindow:
    def __init__(self, web_dir: str, page: str, on_message, width: int, height: int, title: str, icon: str | None,
                 popup=False):
        self._on_message = on_message
        self._popup = popup
        self._width = width
        self.ready = False
        self.shown = False
        self.win = Gtk.Window(title=title)
        # An empty client-side titlebar: no KWin/Mutter title bar on top of the page's own, but GTK still draws
        # the shadow and the resize edges.
        empty = Gtk.Box()
        empty.get_style_context().add_class("lp-empty-titlebar")
        self.win.set_titlebar(empty)
        _install_css()
        self.win.set_default_size(width, height)
        self.win.set_size_request(width, height if popup else 480)
        self.win.set_resizable(not popup)
        if icon and os.path.exists(icon):
            self.win.set_icon_from_file(icon)
        if popup:
            self.win.set_keep_above(True)
            self.win.set_skip_taskbar_hint(True)
            self.win.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        self.win.connect("delete-event", self._on_delete)
        ucm = WebKit2.UserContentManager()
        ucm.add_script(WebKit2.UserScript(BRIDGE, WebKit2.UserContentInjectedFrames.TOP_FRAME,
                                          WebKit2.UserScriptInjectionTime.START, None, None))
        ucm.register_script_message_handler("openpods")
        ucm.connect("script-message-received::openpods", self._on_script_message)
        self.view = WebKit2.WebView.new_with_user_content_manager(ucm)
        s = self.view.get_settings()
        s.set_allow_file_access_from_file_urls(True)
        s.set_allow_universal_access_from_file_urls(True)
        s.set_enable_developer_extras(bool(os.environ.get("OPENPODS_DEVTOOLS")))
        s.set_enable_back_forward_navigation_gestures(False)
        s.set_hardware_acceleration_policy(WebKit2.HardwareAccelerationPolicy.NEVER
                                           if os.environ.get("OPENPODS_NO_GPU") else
                                           WebKit2.HardwareAccelerationPolicy.ON_DEMAND)
        self.view.connect("context-menu", lambda *a: not os.environ.get("OPENPODS_DEVTOOLS"))
        self.view.connect("decide-policy", self._on_policy)
        self.win.add(self.view)
        self.view.load_uri("file://" + os.path.join(web_dir, page))
        self.on_hide_request = None

    def _on_policy(self, view, decision, kind):
        if kind == WebKit2.PolicyDecisionType.NAVIGATION_ACTION:
            uri = decision.get_navigation_action().get_request().get_uri()
            if not uri.startswith("file://"):
                decision.ignore()
                return True
        return False

    def _on_script_message(self, ucm, js_result):
        try:
            value = js_result.get_js_value() if hasattr(js_result, "get_js_value") else js_result
            msg = json.loads(value.to_string())
        except (ValueError, AttributeError) as e:
            log.warning("bad page message: %s", e)
            return
        if msg.get("type") == "ready":
            self.ready = True
        try:
            self._on_message(msg)
        except Exception:  # noqa: BLE001
            log.exception("page message %s failed", msg.get("type"))

    def _on_delete(self, *_):
        self.hide()
        return True

    def post(self, msg: dict):
        if not self.ready:
            return
        js = "window.__lp(" + json.dumps(msg, ensure_ascii=False) + ");"
        self.view.evaluate_javascript(js, -1, None, None, None, None, None)

    def show(self):
        self.win.show_all()
        self.win.present()
        self.shown = True

    def hide(self):
        self.win.hide()
        self.shown = False
        if self.on_hide_request:
            self.on_hide_request()

    def begin_drag(self):
        display = Gdk.Display.get_default()
        seat = display.get_default_seat()
        pointer = seat.get_pointer() if seat else None
        if pointer is None:
            return
        _, x, y = pointer.get_position()
        self.win.begin_move_drag(1, x, y, Gtk.get_current_event_time())

    def snapshot(self, path: str):
        """Saves only this window's page as PNG (debugging; never captures the rest of the screen)."""
        def done(view, res):
            try:
                view.get_snapshot_finish(res).write_to_png(path)
                log.info("snapshot saved: %s", path)
            except Exception as e:  # noqa: BLE001
                log.warning("snapshot failed: %s", e)
        self.view.get_snapshot(WebKit2.SnapshotRegion.FULL_DOCUMENT, WebKit2.SnapshotOptions.NONE, None, done)

    def minimize(self):
        self.win.iconify()

    def set_height(self, h: int):
        h = max(100, int(h))
        if self._popup:
            # A non-resizable window keeps its size request, so the popup grows through it. The request includes
            # GTK's client-side shadow margin, which the page does not get: add what the window has beyond the view.
            ex_w = max(0, self.win.get_allocated_width() - self.view.get_allocated_width())
            ex_h = max(0, self.win.get_allocated_height() - self.view.get_allocated_height())
            self.win.set_size_request(self._width + ex_w, h + ex_h)
            self.win.resize(self._width + ex_w, h + ex_h)
            return
        w, _ = self.win.get_size()
        self.win.resize(w, h)


# ---------------------------------------------------------------- desktop theme

def _portal_read(key):
    try:
        bus = dbus.SessionBus()
        obj = bus.get_object("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop")
        settings = dbus.Interface(obj, "org.freedesktop.portal.Settings")
        try:
            v = settings.ReadOne("org.freedesktop.appearance", key)
        except dbus.DBusException:
            v = settings.Read("org.freedesktop.appearance", key)
        while isinstance(v, dbus.Struct) and len(v) == 1 and not isinstance(v[0], (int, float)):
            v = v[0]
        return v
    except dbus.DBusException:
        return None


def _kdeglobals():
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        cp.read(os.path.expanduser("~/.config/kdeglobals"), encoding="utf-8")
    except (configparser.Error, OSError):
        return None
    return cp


def desktop_dark() -> bool:
    v = _portal_read("color-scheme")
    try:
        if v is not None and int(v) in (1, 2):
            return int(v) == 1
    except (TypeError, ValueError):
        pass
    cp = _kdeglobals()
    if cp and cp.has_option("Colors:Window", "BackgroundNormal"):
        try:
            r, g, b = (int(x) for x in cp.get("Colors:Window", "BackgroundNormal").split(",")[:3])
            return (0.299 * r + 0.587 * g + 0.114 * b) < 128
        except ValueError:
            pass
    return False


def desktop_accent():
    """-> AccentRamp dict or None."""
    rgb = None
    v = _portal_read("accent-color")
    try:
        if v is not None and len(v) == 3:
            rgb = tuple(float(x) for x in v)
            if not all(0 <= c <= 1 for c in rgb):
                rgb = None
    except (TypeError, ValueError):
        rgb = None
    if rgb is None:
        cp = _kdeglobals()
        for sec, key in (("General", "AccentColor"), ("Colors:Selection", "BackgroundNormal")):
            if cp and cp.has_option(sec, key):
                try:
                    rgb = tuple(int(x) / 255 for x in cp.get(sec, key).split(",")[:3])
                    break
                except ValueError:
                    pass
    if rgb is None:
        return None
    h, l, s = colorsys.rgb_to_hls(*rgb)

    def shade(dl):
        r, g, b = colorsys.hls_to_rgb(h, max(0.0, min(1.0, l + dl)), s)
        return "#%02X%02X%02X" % (round(r * 255), round(g * 255), round(b * 255))
    return {"accent": shade(0), "dark1": shade(-0.08), "dark2": shade(-0.16), "dark3": shade(-0.24),
            "light1": shade(0.10), "light2": shade(0.20), "light3": shade(0.30)}
