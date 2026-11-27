# OpenPods

AirPods controls for Linux – a continuation of [WPods](https://github.com/FPNDev/wpods) (GPL-3.0, © fpndev).
The UI is the original WPods web UI (TypeScript); the backend was rewritten in Python: instead of a Windows service
plus a USB/IP trick, OpenPods speaks the AirPods protocol (AAP) directly over BlueZ (L2CAP PSM 0x1001).

## Features
- Battery for left/right/case (+ charging), ear detection (in ear / out / in case)
- Listening mode: off, transparency, adaptive, noise cancellation; ANC with one AirPod; allow "off"
- Conversation awareness (including lowering the volume on the PC, "lower media to"), personalized volume
- Controls: press speed, press-and-hold duration, modes cycled on hold, tone volume, microphone side
- Hearing aid / media assist (Pro 2/3), heart rate (Pro 3)
- Ear detection pauses/resumes media (MPRIS: Spotify, browsers, mpv …)
- iPhone-style nearby popup (open the case → battery + "Connect", shown on the primary monitor); needs one
  connection first (for the keys); **connects automatically** as soon as the AirPods go from the case into your ears
- **HD microphone**: Apple's AAC-ELD mic stream (64 kHz) over AAP instead of HFP – music stays in AAC quality;
  virtual source "AirPods Mic (HD)" (libfdk-aac)
- Keeps the AirPods on A2DP/AAC (no muffled HFP mono sound after a handoff), robust connecting with retries
- **KDE Plasma applet** in the system tray (like KDE Connect/Vaults): battery, listening-mode slider, switches;
  notification on low battery
- Material 3 Expressive UI, 45 languages, light/dark/auto

Not ported (Windows-specific): stereo mic trick, mic modes/AI noise suppression, mixer, low latency, HD voice,
global hotkeys (→ use `openpods ctl …` as a KDE shortcut instead), auto-update.

## Install / run
```sh
./install.sh          # sets up everything: packages, UI, openpods command, app menu, KDE applet, audio, autostart
openpods              # starts (or shows the running window)
openpods --hidden     # without a window (control it from the Plasma applet)
```
Requires: Python 3, python-gobject, webkit2gtk-4.1, python-dbus, python-cryptography, python-numpy, libfdk-aac
(HD mic), BlueZ, PipeWire (`pactl`, `wpctl`), Node.js to build the UI (`install.sh` builds it on the first run).
KDE Plasma 6 for the applet (`install.sh` installs it and adds it to the system tray).
`install.sh` is tested on Arch/Manjaro; the Debian/Ubuntu and Fedora package lists are a best guess.

Recommended for the HD mic: turn off WirePlumber's automatic HFP switch statically
(`~/.config/wireplumber/wireplumber.conf.d/51-openpods-no-hfp-autoswitch.conf` with
`wireplumber.settings = { bluetooth.autoswitch-to-headset-profile = false }`; `install.sh` does this). Do **not**
toggle it at runtime with `wpctl settings` – WirePlumber 0.5.18 crashes when you do.

## Updates
OpenPods checks GitHub for a new release (shortly after starting, then every 6 hours) and shows a notification, a
note in the app and an "Update" button in the applet. Updating fast-forwards this checkout to the release tag and
runs `install.sh` again; settings are kept.
```sh
openpods update --check   # is there a newer release?
openpods update           # install it (from a terminal: also installs new packages)
openpods --version
```
"Update automatically" (app → Linux settings → Updates) installs a new release at the next start of OpenPods.
Only releases are installed, never unreleased commits on `main`. Log: `~/.local/state/openpods/update.log`.

Publishing a release (maintainers): `tools/release.sh X.Y.Z [notes.md]` bumps `openpods/__init__.py` through a pull
request, tags `vX.Y.Z` and creates the GitHub release.

## Command line / keyboard shortcuts
```sh
openpods ctl noise.cycle            # cycle the listening modes (the ones chosen under "press and hold")
openpods ctl noise.nc | noise.transparency | noise.adaptive | noise.off
openpods ctl conversation.on|off
openpods ctl connect | disconnect | connection.toggle
openpods ctl toggle | show | status | quit
openpods ctl update.check
```
In KDE: System Settings → Shortcuts → New → Command.

## Files
- Settings: `~/.config/openpods/settings.json` · log: `~/.local/state/openpods/openpods.log` (`--debug` for packets)
- Code: `openpods/` (aap.py protocol, session.py L2CAP session, app.py control, bluez.py, nearby.py, media.py,
  hires_mic.py HD mic, ui.py, ctl.py control socket)
- UI source: `ui/` (WPods UI + `src/platform.ts` adaptations), built into `web/` (not in the repo)
- Plasma applet: `plasmoid/org.openpods.applet/`; its translations: `plasmoid/translations/*.po`, compiled into
  `contents/locale/<lang>/LC_MESSAGES/plasma_applet_org.openpods.applet.mo` (`msgfmt`)
- Headless UI preview: `tools/ui-preview/`

## Contributing
`main` only takes changes through pull requests.

## Licenses
OpenPods: GPL-3.0 (like WPods, see `LICENSE`, `THIRD-PARTY-NOTICES.txt`). Fonts in `assets/fonts/`:
Google Sans Flex (SIL OFL 1.1, `GoogleSansFlex-OFL.txt`), Material Symbols Rounded (Apache-2.0, Google).
Not affiliated with Apple; AirPods is a trademark of Apple Inc.
