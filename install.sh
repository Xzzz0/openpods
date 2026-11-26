#!/bin/bash
# OpenPods-Installer – richtet OpenPods komplett ein: Pakete, Oberfläche, Programm, KDE-Applet, Audio-Einstellung, Autostart.
#
#   ./install.sh              alles installieren / aktualisieren (fragt nur für Pakete nach dem sudo-Passwort)
#   ./install.sh --no-deps    ohne Paketinstallation
#   ./install.sh --no-start   am Ende OpenPods nicht starten
#
# Läuft mehrfach ohne Schaden (aktualisiert dann nur). Vorher gemachte Einstellungen in ~/.config/openpods bleiben.
set -euo pipefail

HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
DEPS=1
START=1
for a in "$@"; do
  case "$a" in
    --no-deps) DEPS=0 ;;
    --no-start) START=0 ;;
    -h|--help) sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unbekannte Option: $a" >&2; exit 2 ;;
  esac
done

bold() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
ok()   { printf '    \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '    \033[33m!\033[0m %s\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }

# command, app menu entry, icon, KDE applet (added to the system tray)
user_install() {
  mkdir -p "$HOME/.local/bin" "$HOME/.local/share/applications" "$HOME/.local/share/icons/hicolor/256x256/apps"
  ln -sf "$HERE/bin/openpods" "$HOME/.local/bin/openpods"
  cp "$HERE/assets/openpods.png" "$HOME/.local/share/icons/hicolor/256x256/apps/openpods.png"
  {
    echo "[Desktop Entry]"
    echo "Type=Application"
    echo "Name=OpenPods"
    echo "GenericName=AirPods-Steuerung"
    echo "Comment=AirPods: Akku, Hörmodus, Ohrerkennung, HD-Mikro (basiert auf WPods)"
    echo "Exec=$HOME/.local/bin/openpods"
    echo "Icon=openpods"
    echo "Categories=Utility;Settings;HardwareSettings;"
    echo "Keywords=AirPods;Bluetooth;ANC;Headphones;"
    echo "StartupWMClass=openpods"
  } > "$HOME/.local/share/applications/openpods.desktop"
  update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
  # KDE: OpenPods as a native applet in the system tray ("Status und Benachrichtigungen")
  if command -v kpackagetool6 >/dev/null 2>&1; then
    kpackagetool6 -t Plasma/Applet -u "$HERE/plasmoid/org.openpods.applet" >/dev/null 2>&1 \
      || kpackagetool6 -t Plasma/Applet -i "$HERE/plasmoid/org.openpods.applet"
    qdbus6 org.kde.plasmashell /PlasmaShell org.kde.PlasmaShell.evaluateScript '
      panels().forEach(function (p) { p.widgets("org.kde.plasma.systemtray").forEach(function (w) {
        w.currentConfigGroup = ["General"];
        ["extraItems", "knownItems"].forEach(function (k) { var i = w.readConfig(k);
          if (typeof i === "string") i = i.split(",");
          if (i.indexOf("org.openpods.applet") < 0) i.push("org.openpods.applet"); w.writeConfig(k, i); });
        w.reloadConfig(); }); });' >/dev/null 2>&1 || true
  fi
}

if [ "$(id -u)" -eq 0 ]; then
  echo "Bitte als normaler Benutzer starten (nicht mit sudo) – sudo wird nur für Pakete benutzt." >&2
  exit 1
fi

# ------------------------------------------------------------------------------------------------ 1. Pakete
if [ "$DEPS" -eq 1 ]; then
  bold "Pakete"
  if have pacman; then
    PKGS=(python python-gobject gtk3 webkit2gtk-4.1 python-dbus python-cryptography python-numpy libfdk-aac
          bluez bluez-utils libpulse pipewire-pulse wireplumber nodejs npm)
    if have plasmashell; then PKGS+=(kpackage qt6-tools libkscreen); fi
    MISSING=()
    for p in "${PKGS[@]}"; do pacman -Qq "$p" >/dev/null 2>&1 || MISSING+=("$p"); done
    if [ "${#MISSING[@]}" -gt 0 ]; then
      echo "    Fehlt: ${MISSING[*]}"
      sudo pacman -S --needed --noconfirm "${MISSING[@]}"
    fi
    ok "alle Pakete da"
  elif have apt-get; then
    warn "Debian/Ubuntu: Paketnamen nach bestem Wissen, nicht getestet"
    sudo apt-get install -y python3 python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1 python3-dbus python3-cryptography \
      python3-numpy libfdk-aac2 bluez pulseaudio-utils wireplumber nodejs npm
  elif have dnf; then
    warn "Fedora: Paketnamen nach bestem Wissen, nicht getestet (fdk-aac braucht evtl. RPM Fusion)"
    sudo dnf install -y python3 python3-gobject gtk3 webkit2gtk4.1 python3-dbus python3-cryptography python3-numpy \
      fdk-aac-free bluez pulseaudio-utils wireplumber nodejs npm
  else
    warn "Unbekannte Distribution – bitte selbst installieren: Python 3, PyGObject, GTK3, WebKit2GTK 4.1, python-dbus,"
    warn "python-cryptography, numpy, libfdk-aac, BlueZ, PipeWire (pactl/wpctl), Node.js + npm"
  fi
fi

# ------------------------------------------------------------------------------------------------ 2. Bluetooth
bold "Bluetooth"
if have systemctl && ! systemctl is-active --quiet bluetooth 2>/dev/null; then
  sudo systemctl enable --now bluetooth && ok "Bluetooth-Dienst gestartet" || warn "Bluetooth-Dienst ließ sich nicht starten"
else
  ok "Bluetooth-Dienst läuft"
fi
python3 - <<'PY' || warn "Python-Module fehlen noch (siehe oben)"
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("WebKit2", "4.1")
from gi.repository import Gtk, WebKit2  # noqa
import dbus, cryptography, numpy  # noqa
import ctypes; ctypes.CDLL("libfdk-aac.so.2")
print("    \033[32m✓\033[0m Python-Module und libfdk-aac gefunden")
PY

# ------------------------------------------------------------------------------------------------ 3. Oberfläche
bold "Oberfläche bauen"
if have npm; then
  (cd "$HERE/ui" && npm ci --no-audit --no-fund --loglevel=error && npm run build --silent) >/dev/null
  ok "UI gebaut (web/)"
elif [ -f "$HERE/web/index.html" ]; then
  warn "npm fehlt – nehme die vorhandene gebaute UI"
else
  echo "    npm fehlt und es gibt keine gebaute UI – bitte Node.js installieren." >&2
  exit 1
fi

# ------------------------------------------------------------------------------------------------ 4. Audio (HD-Mikro)
bold "Audio-Einstellung"
WP="$HOME/.config/wireplumber/wireplumber.conf.d/51-openpods-no-hfp-autoswitch.conf"
OLD_WP="$HOME/.config/wireplumber/wireplumber.conf.d/51-linpods-no-hfp-autoswitch.conf"
if [ -f "$OLD_WP" ] && [ ! -f "$WP" ]; then mv "$OLD_WP" "$WP"; fi  # same setting, new name: no reload needed
if [ ! -f "$WP" ]; then
  mkdir -p "$(dirname "$WP")"
  cat > "$WP" <<'CONF'
# OpenPods (AirPods HD mic): never switch the AirPods to the HFP headset profile automatically.
# The HD mic (AAC-ELD over AAP) replaces the HFP mic; HFP alongside it drops the link.
# Set here statically because toggling it at runtime (wpctl settings) crashes WirePlumber 0.5.18.
# Remove this file to get the stock behaviour back.
wireplumber.settings = {
  bluetooth.autoswitch-to-headset-profile = false
}
CONF
  # a clean restart reads the file; only runtime toggling of the setting is what crashes WirePlumber
  systemctl --user restart wireplumber 2>/dev/null && ok "WirePlumber: kein automatischer HFP-Wechsel (neu geladen)" \
    || warn "WirePlumber bitte neu starten oder neu anmelden"
else
  ok "WirePlumber-Einstellung schon vorhanden"
fi

# ------------------------------------------------------------------------------------------------ 5. Programm + Applet
bold "OpenPods installieren"
# Until 2026-11-26 the project was called LinPods: stop it and remove its entries (its settings are taken over by
# OpenPods on the first start; ~/.config/linpods itself stays as it is).
if [ -x "$HOME/.local/bin/linpods" ]; then "$HOME/.local/bin/linpods" ctl quit >/dev/null 2>&1 || true; fi
rm -f "$HOME/.local/bin/linpods" "$HOME/.local/share/applications/linpods.desktop" \
      "$HOME/.local/share/icons/hicolor/256x256/apps/linpods.png"
if [ -f "${XDG_CONFIG_HOME:-$HOME/.config}/autostart/linpods.desktop" ]; then
  rm -f "${XDG_CONFIG_HOME:-$HOME/.config}/autostart/linpods.desktop"
fi
if have kpackagetool6 && [ -d "$HOME/.local/share/plasma/plasmoids/org.linpods.applet" ]; then
  kpackagetool6 -t Plasma/Applet -r org.linpods.applet >/dev/null 2>&1 || true
fi
RUNNING=0
if [ -x "$HOME/.local/bin/openpods" ] && "$HOME/.local/bin/openpods" ctl status >/dev/null 2>&1; then
  RUNNING=1
  "$HOME/.local/bin/openpods" ctl quit >/dev/null 2>&1 || true
  for _ in $(seq 1 20); do "$HOME/.local/bin/openpods" ctl status >/dev/null 2>&1 || break; sleep 0.25; done
fi
APPLET_DIR="$HOME/.local/share/plasma/plasmoids/org.openpods.applet"
APPLET_WAS_THERE=0; [ -d "$APPLET_DIR" ] && APPLET_WAS_THERE=1
user_install >/dev/null 2>&1
ok "Befehl openpods, Startmenü-Eintrag, Icon"
if have plasmashell && have kpackagetool6; then
  if [ "$APPLET_WAS_THERE" -eq 1 ] && have systemctl; then
    # Plasma caches the old QML: restart the shell, then put the applet back into the system tray
    systemctl --user restart plasma-plasmashell 2>/dev/null && sleep 6 && user_install >/dev/null 2>&1 || true
  fi
  ok "KDE-Applet im Systemabschnitt (Pfeil im Tray → OpenPods)"
fi
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) warn "~/.local/bin ist nicht im PATH – Start mit ~/.local/bin/openpods" ;; esac

# ------------------------------------------------------------------------------------------------ 6. Autostart
bold "Autostart"
AUTO="${XDG_CONFIG_HOME:-$HOME/.config}/autostart/openpods.desktop"
if [ ! -f "$AUTO" ]; then
  mkdir -p "$(dirname "$AUTO")"
  printf '[Desktop Entry]\nType=Application\nName=OpenPods\nComment=AirPods controls\nExec=%s --hidden\nIcon=openpods\nX-GNOME-Autostart-enabled=true\n' \
    "$HOME/.local/bin/openpods" > "$AUTO"
fi
ok "startet mit der Anmeldung (abschaltbar im Applet: „Mit Linux starten“)"

# ------------------------------------------------------------------------------------------------ 7. Start
if [ "$START" -eq 1 ]; then
  bold "Start"
  if have systemd-run; then
    systemd-run --user --collect --unit="openpods-$(date +%s)" "$HOME/.local/bin/openpods" --hidden >/dev/null 2>&1
  else
    setsid -f "$HOME/.local/bin/openpods" --hidden >/dev/null 2>&1
  fi
  for _ in $(seq 1 40); do "$HOME/.local/bin/openpods" ctl status >/dev/null 2>&1 && break; sleep 0.25; done
  if "$HOME/.local/bin/openpods" ctl status >/dev/null 2>&1; then ok "OpenPods läuft"; else warn "OpenPods startet nicht – Log: ~/.local/state/openpods/openpods.log"; fi
fi

bold "Fertig"
if [ "$RUNNING" -eq 1 ]; then echo "    Aktualisiert."; else
  echo "    AirPods einmal in den Bluetooth-Einstellungen koppeln und verbinden – danach geht alles von selbst"
  echo "    (Case öffnen → Popup, einsetzen → verbindet automatisch)."
fi
