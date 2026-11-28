# About Window Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** "Release Notes" in the applet opens a 7:9 Plasma glass window with a physical ASCII toy: OPENPODS letters, a case with two AirPods, the version digits – all grabbable/throwable, shaken by moving the window.

**Architecture:** Pure JS modules (`physics.js`, `ascii.js`, `.pragma library`) hold all logic and are unit-tested with node; `AboutWindow.qml` is a `PlasmaCore.Dialog` with a `Canvas` that steps the physics and draws glyphs, and moves itself (so it knows its own acceleration).

**Tech Stack:** QML (Plasma 6, Qt 6), plain JS, node for tests. No new dependency.

**Spec:** `docs/superpowers/specs/2026-11-28-about-window-design.md`

## Global Constraints
- Window aspect 7:9 (width:height), glass = `PlasmaCore.Dialog` `backgroundHints: StandardBackground`.
- Shade ramp exactly `.:;=+*xo%#&@` (from edwardjones7/ascii-art, MIT – credited in THIRD-PARTY-NOTICES).
- "?" dot top left opens `https://github.com/Xzzz0/openpods`.
- New applet texts: English in code + `plasmoid/translations/de.po` + `msgfmt`.

## Review Focus
- Fast throw → body tunnels through a wall and is lost: clamp velocity and clamp positions inside the walls every step (test: body at 5000 px/s stays inside).
- Bodies piling up jitter forever: velocity sleep threshold (test: resting stack energy decays to ~0).
- Removing AirPods with the lid closed must not work (test: `canTakeOut(case)` false when closed).
- Window opened twice: second click raises the existing window instead of creating a new one.
- Version string with letters (e.g. "0.1.0-rc1") still renders: unknown glyphs fall back to a box.

---

### Task 1: physics.js
**Files:** Create `plasmoid/org.openpods.applet/contents/ui/physics.js`; Test `tools/applet-tests/physics.test.mjs`
**Produces:** `World(w, h)` with `addBody({x,y,w,h,kind,mass,shape:"box"|"circle"}) -> body`, `step(dt, frameAx, frameAy)`, `bodyAt(x,y) -> body|null`, `grab(body,x,y)`, `drag(x,y)`, `release()` (throw with recent mouse velocity), body fields `x,y,a,vx,vy,va,w,h`.
- [ ] Tests: gravity falls & rests on floor; walls contain a 5000 px/s body; two boxes don't overlap after 2 s; resting energy < 1e-2 after 3 s; frame acceleration (window move right) pushes bodies left; grab/drag/release throws with drag velocity.
- [ ] Implement: semi-implicit Euler, OBB-vs-OBB via SAT with positional correction + impulse (restitution 0.35, friction 0.4), circles as boxes' inscribed test, walls with angle-aware corners, sleep below threshold.
- [ ] `node tools/applet-tests/physics.test.mjs` → all PASS; commit.

### Task 2: ascii.js
**Files:** Create `plasmoid/org.openpods.applet/contents/ui/ascii.js`; Test `tools/applet-tests/ascii.test.mjs`
**Produces:** `RAMP`, `glyphRows(ch) -> string[]` (5x7 block font for A–Z, 0–9, ".", "-", fallback box), `caseSprite(angle, lid) -> cells`, `podSprite(angle, side) -> cells`; cell = `{dx, dy, ch, shade}` relative to body centre in grid cells, shade 0..1.
- [ ] Tests: every char of "OPENPODS" and "0123456789.-" has 7 rows of width 5; unknown char → box; case sprite non-empty, wider than tall, lid open adds cells above; pod sprite has a stem (cells below bud); all `ch` in RAMP.
- [ ] Implement: 3D shapes sampled (rounded box for case + hinged lid, sphere+capsule for pod), rotated by angle about z and a fixed tilt, Lambert shading with light (-0.45,-0.75,0.9), z-buffer per cell, shade → RAMP index.
- [ ] node test PASS; commit.

### Task 3: AboutWindow.qml + applet hook
**Files:** Create `.../ui/AboutWindow.qml`; Modify `.../ui/main.qml` (one window instance, `showAbout()`), `.../ui/FullRepresentation.qml` (Release Notes → `applet.showAbout()`), `THIRD-PARTY-NOTICES.txt`, `plasmoid/translations/de.po` + `.mo`.
**Consumes:** Task 1 + 2 interfaces.
- [ ] Dialog: `type: Normal`, `location: Floating`, size 7:9 (e.g. 21×27 gridUnits), centred on screen at first open; `showAbout()` on an open window just raises it.
- [ ] Bodies: one per letter of OPENPODS (top centre row), case (centre, lid closed, pods inside as bodies with `inside: true` that follow the case until taken out), one per version char (bottom centre, smaller cell size).
- [ ] Input: press on body → grab; press on empty → move window (x/y += mouse delta) and feed window acceleration into `step`; double-click case → toggle lid; pods leave the case when lid open and (grabbed out or case upside down, |angle| > 120°).
- [ ] "?" dot top left (`Qt.openUrlExternally("https://github.com/Xzzz0/openpods")`), tooltip "Project page".
- [ ] Verify: render in isolated Plasma session (plasmawindowed) with stub, screenshots of start layout and after a scripted throw; qmllint clean; commit.
