/*
 * OpenPods in KDE's system tray ("Status and Notifications"), next to Vaults, KDE Connect & co.
 * Talks to the running OpenPods through its control socket: `openpods ctl applet` (state) and
 * `openpods ctl applet.do '<json>'` (actions), via Plasma's executable data engine.
 */
pragma ComponentBehavior: Bound

import QtQuick

import org.kde.kirigami as Kirigami
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.plasma5support as P5Support
import org.kde.plasma.plasmoid

PlasmoidItem {
    id: root

    readonly property string ctl: "\"$HOME/.local/bin/openpods\" ctl"
    property var st: null            // reply of `openpods ctl applet`, null = OpenPods not running
    property bool loaded: false
    property int serial: 0

    readonly property var device: {
        if (!st || !st.devices || st.devices.length === 0) return null
        const id = st.attached
        for (const d of st.devices) if (d.id === id) return d
        return st.devices[0]
    }
    readonly property bool connected: !!(st && st.ready)
    readonly property string batteryText: {
        if (!connected || !st.battery) return ""
        const b = st.battery
        const part = (label, x) => x && x.pct !== null && x.pct !== undefined ? `${label} ${x.pct} %${x.charging ? " ⚡" : ""}` : ""
        return [part(i18n("L"), b.left), part(i18n("R"), b.right), part(i18n("Case"), b.case),
                part("", b.headphone)].filter(s => s.length > 0).join(" · ")
    }

    Plasmoid.icon: "audio-headphones-symbolic"
    Plasmoid.title: "OpenPods"
    Plasmoid.status: connected ? PlasmaCore.Types.ActiveStatus : PlasmaCore.Types.PassiveStatus
    toolTipMainText: device ? device.name : "OpenPods"
    toolTipSubText: !st ? i18n("OpenPods is not running")
                  : connected ? batteryText
                  : device && device.conn === "connecting" ? i18n("Connecting…")
                  : i18n("Not connected")

    switchWidth: Kirigami.Units.gridUnit * 14
    switchHeight: Kirigami.Units.gridUnit * 12

    fullRepresentation: FullRepresentation {
        applet: root
    }

    P5Support.DataSource {
        id: exec
        engine: "executable"
        connectedSources: []
        onNewData: (source, out) => {
            disconnectSource(source)
            if (source.indexOf(" ctl applet #") < 0) {
                // an action: refresh right away
                poll.interval = 250
                poll.restart()
                return
            }
            root.loaded = true
            if (out["exit code"] !== 0 || !out.stdout) {
                root.st = null
                return
            }
            try {
                root.st = JSON.parse(out.stdout)
            } catch (e) {
                root.st = null
            }
        }
    }

    function refresh() {
        serial += 1
        exec.connectSource(`${ctl} applet #${serial}`)
    }

    /// sends one of OpenPods' applet actions; `msg` is plain JSON without single quotes
    function act(msg) {
        serial += 1
        const json = JSON.stringify(msg).replace(/'/g, "")
        exec.connectSource(`${ctl} applet.do '${json}' #${serial}`)
    }

    function startOpenPods() {
        serial += 1
        exec.connectSource(`setsid -f "$HOME/.local/bin/openpods" --hidden >/dev/null 2>&1 #${serial}`)
        poll.interval = 1500
        poll.restart()
    }

    Timer {
        id: poll
        interval: 500
        running: true
        repeat: true
        triggeredOnStart: true
        onTriggered: {
            root.refresh()
            interval = root.expanded ? 2000 : 8000
        }
    }

    onExpandedChanged: {
        if (root.expanded) {
            poll.interval = 50
            poll.restart()
        }
    }

    // "Release Notes": the ASCII toy window (one instance; a second click just raises it)
    AboutWindow {
        id: about
        visible: false
        version: root.st && root.st.update ? root.st.update.version : ""
    }
    function showAbout() { about.show() }

    /// asks the full representation to show one of its pages ("general", "airpods", …)
    signal pageRequested(string name)

    PlasmaCore.Action {
        id: configureAction
        text: i18n("Configure OpenPods…")
        icon.name: "configure"
        onTriggered: {
            root.expanded = true
            root.pageRequested("general")
        }
    }

    Component.onCompleted: {
        Plasmoid.setInternalAction("configure", configureAction)
    }
}
