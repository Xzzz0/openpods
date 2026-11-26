# UI-Vorschau (OpenPods, Swift-Design)
- `./preview.sh /tmp/out home,controls,hearing,windows` – rendert Seiten unsichtbar (kwin_wayland --virtual), PNGs in /tmp/out.
- `./preview.sh /tmp/out popup` – Nearby-Popup. `PREVIEW_THEME=light` für hell.
- Braucht laufendes OpenPods (`openpods ctl debug.init` liefert Texte/Geräte); Zustand kommt aus `state.json`.
- `scheme.cpp`: rechnet Swifts Material-3-Farben (Seed #ff3d8a, SchemeContent) mit Swifts material-color-utilities:
  `g++ -std=c++20 -I ~/swiftify/third_party/material-color-utilities scheme.cpp ~/swiftify/build/libmaterial_color_utilities.a -o scheme && ./scheme d`
