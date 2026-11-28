# About window ("Release Notes") – design

## Intent
Clicking "Release Notes" in the applet opens a small KDE-style translucent glass window that is a playful toy:
an interactive ASCII animation of an AirPods case with both AirPods inside, the name OPENPODS in ASCII letters
and the version number. Everything in it is physical and can be thrown around.

## Goals
- Window 7:9 (width:height), Plasma glass look (same blurred translucent background as tray popups, follows the theme).
- Start layout: OPENPODS in ASCII letters top centre, case (closed, AirPods inside) in the middle, version small at
  the bottom centre.
- Every letter, every digit/dot of the version, the case and both AirPods are separate rigid bodies:
  gravity, collisions with each other and the window walls, rotation.
- Grab and throw any body with the mouse.
- Moving the window shakes the content (window acceleration acts as inertia on every body).
- Case: double-click opens/closes the lid. With the lid open the AirPods can be pulled out with the mouse, and they
  fall out when the case is turned upside down.
- Small "?" dot top left opens the repository page (https://github.com/Xzzz0/openpods).
- ASCII look taken from edwardjones7/ascii-art (MIT): 3D shapes shaded with the ramp `.:;=+*xo%#&@`, coloured,
  monospace font, drawn on a character grid.

## Non-goals
- No release-notes text in the window. No sound. No physics library or new dependency.

## Approaches
1. **Plasma dialog in the applet (QML + Canvas), chosen.** Real KDE blur/translucency for free, no new process,
   physics + rendering in JS. Trade-off: JS performance → keep the character grid small (~70×90 cells).
2. Python/GTK window (like the nearby popup): no KWin blur on Wayland, would not look like KDE glass.
3. pygame port of the repo: extra dependency, own window without KDE look.

## How (builder's calls)
- `AboutWindow.qml` (Plasma dialog/window, glass background, 7:9) + `ascii.js` (shapes → shaded glyph sprites)
  + `physics.js` (bodies: position, velocity, angle, angular velocity; box/circle collision; walls; drag).
- Letters/digits: rendered from a small built-in ASCII block font, each glyph a body.
- Case and AirPods: 3D shapes (rounded box with lid, AirPod = bud sphere + stem capsule) rasterised per frame
  at their current angle, shaded with a light direction, z-buffer on the char grid.
- Window motion: sample window x/y each frame, second difference = acceleration, apply opposite to bodies.
- Credit the ascii-art repo (MIT) in THIRD-PARTY-NOTICES.
