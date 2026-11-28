/*
 * "Release Notes": a small Plasma glass window with a physical ASCII toy – OPENPODS letters on top, the AirPods
 * case in the middle, the version at the bottom. Everything can be grabbed and thrown; dragging the window by its
 * empty background shakes the contents. Double-click the case to open/close the lid; with the lid open the AirPods
 * can be pulled out, and they fall out when the case is turned upside down.
 * Rendering after edwardjones7/ascii-art (MIT), see ascii.js; physics in physics.js.
 */
pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Window

import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents3
import org.kde.plasma.core as PlasmaCore

import "physics.js" as Phys
import "ascii.js" as Ascii

PlasmaCore.Dialog {
    id: win

    property string version: ""
    readonly property string repoUrl: "https://github.com/Xzzz0/openpods"

    type: PlasmaCore.Dialog.Normal
    location: PlasmaCore.Types.Floating
    backgroundHints: PlasmaCore.Dialog.StandardBackground
    hideOnWindowDeactivate: false
    flags: Qt.FramelessWindowHint

    // world state (plain JS objects, the Canvas draws them every frame)
    property var world: null
    property var caseBody: null
    property var pods: []          // {body, side, attached}
    property bool lidOpen: false
    property real lastX: 0
    property real lastY: 0
    property real lastVx: 0
    property real lastVy: 0
    property real frameAx: 0
    property real frameAy: 0

    function show() {
        if (visible) {
            raise()
            requestActivate()
            return
        }
        const scr = Qt.application.screens[0]
        x = scr.virtualX + (scr.width - stage.width) / 2
        y = scr.virtualY + (scr.height - stage.height) / 2
        visible = true
        requestActivate()
        reset()
    }

    /// start layout: name on top, case in the middle (closed, AirPods inside), version at the bottom; all asleep
    function reset() {
        const W = stage.width, H = stage.height
        const w = new Phys.World(W, H)
        const asleep = b => { b.still = 1e9; return b }

        const name = "OPENPODS", lw = 5 * big.cw, lh = 7 * big.ch, gap = big.cw
        const nameW = name.length * lw + (name.length - 1) * gap
        for (let i = 0; i < name.length; i++) {
            // snapped to the character grid, so the resting letters are crisp
            const left = Math.round((W - nameW) / 2 / big.cw) * big.cw, top = Math.round(Kirigami.Units.gridUnit * 1.6 / big.ch) * big.ch
            const b = asleep(w.addBody({ x: left + lw / 2 + i * (lw + gap), y: top + lh / 2,
                                         w: lw, h: lh, kind: "letter", data: name[i] }))
            b.font = big
        }

        const ver = version || "?", vw = 5 * small.cw, vh = 7 * small.ch, vgap = small.cw
        const verW = ver.length * vw + (ver.length - 1) * vgap
        for (let i = 0; i < ver.length; i++) {
            const left = Math.round((W - verW) / 2 / small.cw) * small.cw
            const top = Math.round((H - Kirigami.Units.gridUnit * 1.2 - vh) / small.ch) * small.ch
            const b = asleep(w.addBody({ x: left + vw / 2 + i * (vw + vgap), y: top + vh / 2,
                                         w: vw, h: vh, kind: "digit", data: ver[i] }))
            b.font = small
        }

        const cw = W * 0.42, chh = cw * 0.76
        const c = asleep(w.addBody({ x: W / 2, y: H / 2 + chh * 0.1, w: cw, h: chh, kind: "case", mass: 30 }))
        c.font = mid
        const pw = cw * 0.22, ph = pw * 2.1
        const ps = []
        for (const side of ["left", "right"]) {
            const p = w.addBody({ x: c.x, y: c.y, w: pw, h: ph, kind: "pod", data: side, mass: 3 })
            p.ghost = true   // inside the case: no collisions, follows the case
            p.font = mid
            ps.push({ body: p, side: side, attached: true })
        }
        world = w
        caseBody = c
        pods = ps
        lidOpen = false
        lastX = x; lastY = y; lastVx = 0; lastVy = 0
        frameAx = 0; frameAy = 0
        needsPaint = true
    }

    // where an attached pod sits: standing in its slot, head above the base's top edge
    function placeAttached(p) {
        const c = caseBody, b = p.body
        const lx = (p.side === "left" ? -1 : 1) * c.w * 0.2
        const ly = -c.h / 2 + c.h * 0.35 - b.h * 0.12
        const cs = Math.cos(c.a), sn = Math.sin(c.a)
        b.x = c.x + lx * cs - ly * sn
        b.y = c.y + lx * sn + ly * cs
        b.a = c.a
        b.vx = c.vx; b.vy = c.vy; b.va = 0
    }

    function detach(p) {
        p.attached = false
        p.body.ghost = false
        p.body.still = 0
        p.body.vx = caseBody.vx; p.body.vy = caseBody.vy
        // move it out of the case's box so the contact solver doesn't fire it across the window
        const c = caseBody
        const cs = Math.cos(c.a), sn = Math.sin(c.a)
        const ly = -c.h / 2 - p.body.h / 2 - 2
        const lx = (p.side === "left" ? -1 : 1) * c.w * 0.2
        p.body.x = c.x + lx * cs - ly * sn
        p.body.y = c.y + lx * sn + ly * cs
    }

    function tick(dt) {
        if (!world) return
        dt = Math.min(dt, 1 / 30)
        // the window's own acceleration (it only moves when the user drags it)
        const vx = (x - lastX) / dt, vy = (y - lastY) / dt
        const ax = Math.max(-25000, Math.min(25000, (vx - lastVx) / dt))
        const ay = Math.max(-25000, Math.min(25000, (vy - lastVy) / dt))
        frameAx = frameAx * 0.5 + ax * 0.5
        frameAy = frameAy * 0.5 + ay * 0.5
        lastX = x; lastY = y; lastVx = vx; lastVy = vy

        const steps = Math.max(1, Math.round(dt * 120))
        for (let i = 0; i < steps; i++) {
            world.step(dt / steps, frameAx, frameAy)
            for (const p of pods) if (p.attached) placeAttached(p)
        }
        // upside down with the lid open: the AirPods fall out
        if (lidOpen) {
            const a = Math.atan2(Math.sin(caseBody.a), Math.cos(caseBody.a))
            if (Math.abs(a) > 2.1) for (const p of pods) if (p.attached) detach(p)
        }
        // nothing moves (all asleep, nothing held, window still): keep the last frame
        const busy = world.held || Math.abs(frameAx) + Math.abs(frameAy) > 50
                     || world.bodies.some(b => !b.ghost && b.still <= 40)
        if (busy || needsPaint) {
            needsPaint = false
            canvas.requestPaint()
        }
    }
    property bool needsPaint: true
    onLidOpenChanged: needsPaint = true

    mainItem: Item {
        id: stage
        width: Kirigami.Units.gridUnit * 21
        height: Kirigami.Units.gridUnit * 27      // 7:9

        Keys.onEscapePressed: win.visible = false

        // three character grids: big (name), mid (case + AirPods), small (version)
        TextMetrics { id: bigM; font.family: "monospace"; font.pixelSize: Math.round(Kirigami.Units.gridUnit * 0.5); font.bold: true; text: "M" }
        TextMetrics { id: midM; font.family: "monospace"; font.pixelSize: Math.round(Kirigami.Units.gridUnit * 0.55); font.bold: true; text: "M" }
        TextMetrics { id: smallM; font.family: "monospace"; font.pixelSize: Math.round(Kirigami.Units.gridUnit * 0.36); font.bold: true; text: "M" }
        QtObject { id: big; readonly property real cw: bigM.advanceWidth; readonly property real ch: bigM.height; readonly property string css: `bold ${bigM.font.pixelSize}px monospace` }
        QtObject { id: mid; readonly property real cw: midM.advanceWidth; readonly property real ch: midM.height; readonly property string css: `bold ${midM.font.pixelSize}px monospace` }
        QtObject { id: small; readonly property real cw: smallM.advanceWidth; readonly property real ch: smallM.height; readonly property string css: `bold ${smallM.font.pixelSize}px monospace` }

        Canvas {
            id: canvas
            anchors.fill: parent
            renderStrategy: Canvas.Cooperative

            readonly property color ink: Kirigami.Theme.textColor
            readonly property color accent: Kirigami.Theme.highlightColor

            onPaint: {
                const ctx = getContext("2d")
                ctx.reset()
                if (!win.world) return
                ctx.textBaseline = "top"
                // the case first, attached AirPods on top of it, then everything else
                const order = win.world.bodies.slice().sort((a, b) => rank(a) - rank(b))
                for (const b of order) {
                    const p = b.kind === "pod" ? win.pods.find(q => q.body === b) : null
                    if (p && p.attached && !win.lidOpen) continue
                    let sampler
                    if (b.kind === "case") sampler = Ascii.caseSampler(b, win.lidOpen)
                    else if (b.kind === "pod") sampler = Ascii.podSampler(b, b.data)
                    else sampler = Ascii.glyphSampler(b, b.data)
                    const f = b.font
                    const color = b.kind === "letter" ? accent : ink
                    ctx.font = f.css
                    for (const c of Ascii.rasterize(b, f.cw, f.ch, sampler)) {
                        ctx.fillStyle = Qt.rgba(color.r, color.g, color.b,
                                                (b.kind === "digit" ? 0.55 : 0.35) + 0.65 * c.shade)
                        ctx.fillText(c.ch, c.col * f.cw, c.row * f.ch)
                    }
                }
            }
            function rank(b) { return b.kind === "case" ? 0 : b.kind === "pod" ? 1 : 2 }
        }

        FrameAnimation {
            running: win.visible
            onTriggered: win.tick(frameTime)
        }

        MouseArea {
            id: input
            anchors.fill: parent
            property bool movingWindow: false
            property real pressX: 0
            property real pressY: 0

            function podAt(mx, my) {
                // attached AirPods are only reachable while the lid is open
                for (const p of win.pods) {
                    if (!p.attached || !win.lidOpen) continue
                    const b = p.body
                    if (Math.abs(mx - b.x) < b.w * 0.7 && Math.abs(my - b.y) < b.h * 0.6) return p
                }
                return null
            }

            onPressed: mouse => {
                if (!win.world) return
                const p = podAt(mouse.x, mouse.y)
                if (p) {
                    win.detach(p)
                    p.body.x = mouse.x; p.body.y = mouse.y
                    win.world.grab(p.body, mouse.x, mouse.y)
                    return
                }
                const b = win.world.bodyAt(mouse.x, mouse.y, 3)
                if (b) {
                    win.world.grab(b, mouse.x, mouse.y)
                } else {
                    movingWindow = true
                    pressX = mouse.x
                    pressY = mouse.y
                }
            }
            onPositionChanged: mouse => {
                if (movingWindow) {
                    // move the window ourselves, so its acceleration is known exactly (Wayland hides it otherwise)
                    win.x += mouse.x - pressX
                    win.y += mouse.y - pressY
                } else if (win.world) {
                    win.world.drag(mouse.x, mouse.y)
                }
            }
            onReleased: {
                movingWindow = false
                if (win.world) win.world.release()
            }
            onDoubleClicked: mouse => {
                if (win.world && win.world.bodyAt(mouse.x, mouse.y, 3) === win.caseBody) {
                    win.world.release()
                    win.lidOpen = !win.lidOpen
                    win.caseBody.still = 0
                }
            }
        }

        // "?" – project page
        Rectangle {
            id: help
            x: Kirigami.Units.smallSpacing * 2
            y: Kirigami.Units.smallSpacing * 2
            width: Kirigami.Units.iconSizes.small + 2
            height: width
            radius: width / 2
            color: helpMouse.containsMouse ? Kirigami.Theme.highlightColor : Qt.rgba(Kirigami.Theme.textColor.r, Kirigami.Theme.textColor.g, Kirigami.Theme.textColor.b, 0.15)
            PlasmaComponents3.Label {
                anchors.centerIn: parent
                text: "?"
                font.bold: true
                font.pixelSize: parent.height * 0.7
                color: helpMouse.containsMouse ? Kirigami.Theme.highlightedTextColor : Kirigami.Theme.textColor
            }
            MouseArea {
                id: helpMouse
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: Qt.openUrlExternally(win.repoUrl)
            }
            PlasmaComponents3.ToolTip.text: i18n("Project page")
            PlasmaComponents3.ToolTip.visible: helpMouse.containsMouse
        }

        PlasmaComponents3.ToolButton {
            anchors.top: parent.top
            anchors.right: parent.right
            anchors.margins: Kirigami.Units.smallSpacing
            icon.name: "window-close"
            display: PlasmaComponents3.AbstractButton.IconOnly
            text: i18n("Close")
            onClicked: win.visible = false
        }
    }
}
