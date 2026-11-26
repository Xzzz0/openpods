"""OpenPods UI preview: renders pages with real labels + a fake connected state, saves PNGs. Run inside a headless kwin."""
import json, os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk
from openpods import ui as uimod
from openpods.ui import WebWindow
# collect page errors so a preview run doubles as a smoke test (read them with PREVIEW_JS='JSON.stringify(window.__errs)')
uimod.BRIDGE = """
window.__errs = [];
window.addEventListener('error', (e) => window.__errs.push(String(e.message) + ' @' + e.filename + ':' + e.lineno));
window.addEventListener('unhandledrejection', (e) => window.__errs.push('promise: ' + String(e.reason)));
(() => { const ce = console.error.bind(console);
  console.error = (...a) => { window.__errs.push('console: ' + a.map(String).join(' ')); ce(...a); }; })();
""" + uimod.BRIDGE
from openpods import app as appmod

out = sys.argv[1]; pages = sys.argv[2].split(",")
here = os.path.dirname(os.path.abspath(__file__))
init = json.load(open(sys.argv[3]))
state = json.load(open(os.path.join(here, "state.json")))
mac = init["devices"][0]["id"]
init["devices"][0]["conn"] = "connected"
init["attached"] = mac; init["selected"] = mac; init["state"] = state; init["firstRun"] = False
init["visible"] = True
if os.environ.get("PREVIEW_THEME"):
    init["theme"] = os.environ["PREVIEW_THEME"]
POPUP = pages == ["popup"]
if POPUP:
    st = lambda p, c=False: {"pct": p, "charging": c}
    offer = {"id": mac, "name": init["devices"][0]["name"], "art": "pro", "state": "offer",
             "batteries": {"left": st(80), "right": st(75), "case": st(50, True), "headphone": None}}
    init = {"type": "init", "labels": init["labels"], "lang": init["lang"], "rtl": init["rtl"], "theme": init["theme"],
            "useAccent": False, "accent": None, "visible": True, "offers": [offer]}
win = None

def on_msg(m):
    if m.get("type") == "ready":
        win.post(init)
        GLib.timeout_add(1200, step, 0)

def step(i):
    if POPUP:
        if i:
            Gtk.main_quit(); return False
        GLib.timeout_add(900, lambda: (win.snapshot(os.path.join(out, "popup.png")), GLib.timeout_add(700, step, 1))[0] and False)
        return False
    if i >= len(pages):
        Gtk.main_quit(); return False
    p = pages[i]
    win.view.evaluate_javascript(f"window.__lpGo({json.dumps(p)})", -1, None, None, None, None, None)
    def snap():
        js = os.environ.get("PREVIEW_JS")
        if js:
            def got(view, res):
                try:
                    print("JS:", view.evaluate_javascript_finish(res).to_string(), flush=True)
                except Exception as e:
                    print("JS error", e, flush=True)
            win.view.evaluate_javascript(js, -1, None, None, None, got)
        win.snapshot(os.path.join(out, f"{p}.png"))
        GLib.timeout_add(700, step, i + 1)
        return False
    GLib.timeout_add(900, snap)
    return False

win = WebWindow(appmod.WEB, "popup.html" if POPUP else "index.html", on_msg, 340 if POPUP else 420, 300 if POPUP else 820, "OpenPods Preview", None, popup=POPUP)
win.show()
GLib.timeout_add_seconds(40, Gtk.main_quit)
Gtk.main()
