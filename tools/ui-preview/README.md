# UI preview (OpenPods)
- `./preview.sh /tmp/out home,controls,hearing,windows` – renders pages invisibly (kwin_wayland --virtual), PNGs in /tmp/out.
- `./preview.sh /tmp/out popup` – nearby popup. `PREVIEW_THEME=light` for the light theme.
- `PREVIEW_JS='JSON.stringify(window.__errs)'` prints the JavaScript errors collected on each page.
- Needs a running OpenPods (`openpods ctl debug.init` supplies texts/devices); the state comes from `state.json`.
- `scheme.cpp`: computes the Material 3 colors of the design (seed #ff3d8a, SchemeContent) with material-color-utilities,
  e.g. from the Swift music app: `g++ -std=c++20 -I ~/swiftify/third_party/material-color-utilities scheme.cpp ~/swiftify/build/libmaterial_color_utilities.a -o scheme && ./scheme d`
