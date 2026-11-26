# OpenPods

AirPods-Steuerung für Linux – ein Weiterentwicklung von [WPods](https://github.com/FPNDev/wpods) (GPL-3.0, © fpndev).
Die Oberfläche ist die originale WPods-Web-UI (TypeScript), das Backend wurde in Python neu geschrieben:
statt Windows-Dienst + USB-IP-Trick spricht OpenPods das AirPods-Protokoll (AAP) direkt über BlueZ (L2CAP PSM 0x1001).

## Funktionen
- Akku links/rechts/Case (+ Laden), Ohrerkennung (In Ear / Raus / Im Case)
- Hörmodus: Aus, Transparenz, Adaptiv, Geräuschunterdrückung; ANC mit einem AirPod; „Aus“ erlauben
- Gesprächserkennung (inkl. Lautstärke absenken auf dem PC, „Medien absenken auf“), Personalisierte Lautstärke
- Steuerung: Drückgeschwindigkeit, Drück-und-halten-Dauer, Modi-Zyklus beim Halten, Ton-Lautstärke, Mikrofonseite
- Hörhilfe / Medienunterstützung (Pro 2/3), Herzfrequenz (Pro 3)
- Ohrerkennung pausiert/fortsetzt Medien (MPRIS: Spotify, Browser, mpv …)
- Nearby-Popup wie am iPhone (Case öffnen → Akku + „Verbinden“, öffnet auf dem primären Monitor), braucht einmal eine
  Verbindung (Schlüssel); **verbindet automatisch**, sobald die AirPods aus dem Case ins Ohr kommen
- **HD-Mikrofon**: Apples AAC-ELD-Mikrostream (64 kHz) über AAP statt HFP – Musik bleibt dabei in AAC-Qualität;
  virtuelle Quelle „AirPods Mikro (HD)“ (libfdk-aac)
- Hält die AirPods auf A2DP/AAC (kein „schleimiger“ HFP-Mono-Ton nach Handoff), robustes Verbinden mit Wiederholung
- **KDE-Plasma-Applet** im Systemabschnitt (wie KDE Connect/Tresore): Akku, Hörmodus-Schieberegler, Schalter;
  Benachrichtigung bei schwachem Akku
- Oberfläche im Material-3-Expressive-Stil, 45 Sprachen, Hell/Dunkel/Auto

Nicht portiert (Windows-spezifisch): Stereo-Mikro-Trick, Mikro-Modi/KI-Rauschunterdrückung, Mixer, Low-Latency,
HD-Voice, globale Hotkeys (→ stattdessen `openpods ctl …` als KDE-Kurzbefehl), Auto-Update.

## Installieren / Starten
```sh
./install.sh          # richtet alles ein: Pakete, UI, Befehl openpods, Startmenü, KDE-Applet, Audio, Autostart
openpods               # startet (oder zeigt das laufende Fenster)
openpods --hidden      # ohne Fenster (Steuerung über das Plasma-Applet)
```
Benötigt: Python 3, python-gobject, webkit2gtk-4.1, python-dbus, python-cryptography, python-numpy, libfdk-aac
(HD-Mikro), BlueZ, PipeWire (`pactl`, `wpctl`), Node.js zum Bauen der UI (`install.sh` baut sie beim ersten Mal).
KDE Plasma 6 für das Applet (`install.sh` installiert es und trägt es in den Systemabschnitt ein).

Empfohlen fürs HD-Mikro: WirePlumbers automatischen HFP-Wechsel statisch abschalten
(`~/.config/wireplumber/wireplumber.conf.d/51-openpods-no-hfp-autoswitch.conf` mit
`wireplumber.settings = { bluetooth.autoswitch-to-headset-profile = false }`). **Nicht** zur Laufzeit per
`wpctl settings` umschalten – WirePlumber 0.5.18 stürzt dabei ab.

## Steuern per Kommandozeile / Tastenkürzel
```sh
openpods ctl noise.cycle            # Hörmodus durchschalten (Modi aus „Drücken und halten“)
openpods ctl noise.nc | noise.transparency | noise.adaptive | noise.off
openpods ctl conversation.on|off
openpods ctl connect | disconnect | connection.toggle
openpods ctl toggle | show | status | quit
```
In KDE: Systemeinstellungen → Kurzbefehle → Neu → Befehl.

## Dateien
- Einstellungen: `~/.config/openpods/settings.json` · Log: `~/.local/state/openpods/openpods.log` (`--debug` für Pakete)
- Code: `openpods/` (aap.py Protokoll, session.py L2CAP-Sitzung, app.py Steuerung, bluez.py, nearby.py, media.py,
  hires_mic.py HD-Mikro, ui.py, ctl.py Steuer-Socket)
- UI-Quelle: `ui/` (WPods-UI + `src/platform.ts`-Anpassungen), gebaut nach `web/` (nicht im Repo)
- Plasma-Applet: `plasmoid/org.openpods.applet/`
- UI-Vorschau ohne Bildschirm: `tools/ui-preview/`

## Lizenzen
OpenPods: GPL-3.0 (wie WPods, siehe `LICENSE`, `THIRD-PARTY-NOTICES.txt`). Schriften in `assets/fonts/`:
Google Sans Flex (SIL OFL 1.1, `GoogleSansFlex-OFL.txt`), Material Symbols Rounded (Apache-2.0, Google).
Nicht mit Apple verbunden; AirPods ist eine Marke der Apple Inc.
