#!/bin/bash
# Renders OpenPods pages in a hidden KWin (never touches the real screen) with real labels from the running app and
# a fake connected AirPods state. Usage: preview.sh OUTDIR home,controls,hearing,windows   (or: preview.sh OUTDIR popup)
# Env: PREVIEW_THEME=light|dark, PREVIEW_JS='js expr' (printed as "JS: ...").
HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$1"
openpods ctl debug.init > "$1/.init.json" || exit 1
env -u DISPLAY WAYLAND_DISPLAY= kwin_wayland --virtual --width 1200 --height 1000 --no-lockscreen --socket lp-preview \
  --exit-with-session "env GDK_BACKEND=wayland WAYLAND_DISPLAY=lp-preview OPENPODS_NO_GPU=1 PREVIEW_JS=\"$PREVIEW_JS\" PREVIEW_THEME=$PREVIEW_THEME python3 '$HERE/preview.py' '$1' $2 '$1/.init.json'" 2>&1 \
  | grep -iE "JS|snapshot|error|Traceback" | head -20
