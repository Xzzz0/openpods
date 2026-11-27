pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents3
import org.kde.plasma.extras as PlasmaExtras

PlasmaExtras.Representation {
    id: full

    required property var applet
    readonly property var st: applet.st
    readonly property var device: applet.device
    readonly property bool connected: applet.connected
    readonly property var prefs: st ? st.prefs : ({})

    collapseMarginsHint: true
    Layout.minimumWidth: Kirigami.Units.gridUnit * 18
    Layout.preferredWidth: Kirigami.Units.gridUnit * 20
    Layout.preferredHeight: Kirigami.Units.gridUnit * 24

    // no own header: the system tray already shows the title plus "Open OpenPods" / "Set up" (main.qml actions)

    // --- OpenPods not running
    PlasmaExtras.PlaceholderMessage {
        anchors.centerIn: parent
        width: parent.width - Kirigami.Units.gridUnit * 4
        visible: full.applet.loaded && !full.st
        iconName: "audio-headphones"
        text: i18n("OpenPods is not running")
        helpfulAction: QQC2.Action {
            text: i18n("Start OpenPods")
            icon.name: "media-playback-start"
            onTriggered: full.applet.startOpenPods()
        }
    }

    PlasmaComponents3.ScrollView {
        id: scroll
        anchors.fill: parent
        visible: !!full.st
        contentWidth: availableWidth
        QQC2.ScrollBar.horizontal.policy: QQC2.ScrollBar.AlwaysOff

        ColumnLayout {
            width: scroll.availableWidth
            spacing: Kirigami.Units.smallSpacing

            // ---------------------------------------------------------- update (GitHub release, openpods/updater.py)
            Kirigami.InlineMessage {
                id: updateNote
                readonly property var info: full.st && full.st.update ? full.st.update : ({})
                Layout.fillWidth: true
                Layout.margins: Kirigami.Units.smallSpacing
                visible: !!info.available
                type: Kirigami.MessageType.Positive
                icon.name: "update-none"
                text: info.installing ? i18n("Installing OpenPods %1…", info.available)
                                      : i18n("OpenPods %1 is available", info.available)
                actions: [
                    Kirigami.Action {
                        text: i18n("Update")
                        icon.name: "download"
                        enabled: !updateNote.info.installing
                        onTriggered: full.applet.act({ type: "update" })
                    }
                ]
            }

            // ---------------------------------------------------------- device
            RowLayout {
                Layout.fillWidth: true
                Layout.margins: Kirigami.Units.smallSpacing
                spacing: Kirigami.Units.largeSpacing

                Kirigami.Icon {
                    source: "audio-headphones"
                    Layout.preferredWidth: Kirigami.Units.iconSizes.large
                    Layout.preferredHeight: Kirigami.Units.iconSizes.large
                    opacity: full.connected ? 1 : 0.5
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 0
                    PlasmaExtras.Heading {
                        Layout.fillWidth: true
                        level: 3
                        text: full.device ? full.device.name : i18n("No AirPods paired")
                        elide: Text.ElideRight
                    }
                    PlasmaComponents3.Label {
                        Layout.fillWidth: true
                        opacity: 0.7
                        elide: Text.ElideRight
                        text: {
                            if (!full.device) return ""
                            switch (full.device.conn) {
                            case "connected": return i18n("Connected") + (full.device.model ? " · " + full.device.model : "")
                            case "connecting":
                            case "reconnecting": return i18n("Connecting…")
                            case "elsewhere": return i18n("Connected to another device")
                            case "attachFailed": return i18n("Controls unavailable – connect again")
                            default: return i18n("Not connected")
                            }
                        }
                    }
                }
                PlasmaComponents3.Button {
                    visible: !!full.device
                    icon.name: full.connected ? "network-disconnect" : "network-connect"
                    text: full.connected ? i18n("Disconnect") : i18n("Connect")
                    enabled: !!full.device && full.device.conn !== "connecting" && full.device.conn !== "reconnecting"
                    onClicked: full.applet.act({ type: full.connected ? "disconnect" : "connect",
                                                 id: full.device.id })
                }
            }

            // ---------------------------------------------------------- batteries
            RowLayout {
                Layout.alignment: Qt.AlignHCenter
                Layout.topMargin: Kirigami.Units.smallSpacing
                visible: !!full.st && !!full.st.battery
                spacing: Kirigami.Units.gridUnit

                Repeater {
                    model: [
                        { key: "left", label: i18n("Left") },
                        { key: "right", label: i18n("Right") },
                        { key: "case", label: i18n("Case") },
                        { key: "headphone", label: i18n("Battery") },
                    ]
                    delegate: ColumnLayout {
                        id: cell
                        required property var modelData
                        readonly property var bat: full.st && full.st.battery ? full.st.battery[modelData.key] : null
                        readonly property bool known: !!bat && bat.pct !== null && bat.pct !== undefined
                        visible: known
                        Layout.preferredWidth: Kirigami.Units.gridUnit * 4
                        spacing: Kirigami.Units.smallSpacing / 2

                        Kirigami.Icon {
                            Layout.alignment: Qt.AlignHCenter
                            Layout.preferredWidth: Kirigami.Units.iconSizes.medium
                            Layout.preferredHeight: Kirigami.Units.iconSizes.medium
                            source: {
                                if (!cell.known) return "battery-missing-symbolic"
                                const step = Math.min(100, Math.round(cell.bat.pct / 10) * 10)
                                const n = String(step).padStart(3, "0")
                                return `battery-${n}${cell.bat.charging ? "-charging" : ""}-symbolic`
                            }
                        }
                        PlasmaComponents3.Label {
                            Layout.alignment: Qt.AlignHCenter
                            text: cell.known ? `${cell.bat.pct} %` : ""
                            font.weight: Font.DemiBold
                            color: cell.known && cell.bat.pct <= 10 ? Kirigami.Theme.negativeTextColor : Kirigami.Theme.textColor
                        }
                        PlasmaComponents3.Label {
                            Layout.alignment: Qt.AlignHCenter
                            text: cell.modelData.label
                            opacity: 0.7
                            font: Kirigami.Theme.smallFont
                        }
                    }
                }
            }

            PlasmaComponents3.Label {
                Layout.alignment: Qt.AlignHCenter
                visible: !!full.st && !!full.st.battery && full.st.batterySource !== "live"
                opacity: 0.6
                font: Kirigami.Theme.smallFont
                text: !full.st ? "" : full.st.batterySource === "nearby" ? i18n("From the case nearby")
                    : i18n("Last seen %1 min ago", Math.max(1, Math.round((full.st.batteryAge || 0) / 60)))
            }

            // ---------------------------------------------------------- noise control (slider, like KDE's power profiles)
            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: Kirigami.Units.largeSpacing
                Layout.leftMargin: Kirigami.Units.smallSpacing
                Layout.rightMargin: Kirigami.Units.smallSpacing
                visible: modeSlider.count > 1
                Kirigami.Heading {
                    Layout.fillWidth: true
                    level: 5
                    opacity: 0.7
                    text: i18n("Noise Control")
                }
                PlasmaComponents3.Label {
                    font.weight: Font.DemiBold
                    text: modeSlider.current >= 0 ? modeSlider.modes[modeSlider.current].label : ""
                }
            }
            ColumnLayout {
                id: modeSlider
                readonly property var modes: full.st && full.st.modes ? full.st.modes : []
                readonly property int count: modes.length
                readonly property int current: {
                    for (let k = 0; k < modes.length; ++k) if (modes[k].id === full.st.listeningMode) return k
                    return -1
                }
                Layout.fillWidth: true
                Layout.leftMargin: Kirigami.Units.largeSpacing
                Layout.rightMargin: Kirigami.Units.largeSpacing
                visible: count > 1
                spacing: 0

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Kirigami.Units.smallSpacing
                    Kirigami.Icon {
                        source: "audio-volume-muted-symbolic"
                        Layout.preferredWidth: Kirigami.Units.iconSizes.small
                        Layout.preferredHeight: Kirigami.Units.iconSizes.small
                        opacity: slider.enabled ? 1 : 0.5
                    }
                    PlasmaComponents3.Slider {
                        id: slider
                        Layout.fillWidth: true
                        from: 0
                        to: Math.max(1, modeSlider.count - 1)
                        stepSize: 1
                        snapMode: QQC2.Slider.SnapAlways
                        enabled: full.connected
                        // follow the AirPods unless the user is dragging
                        Binding on value {
                            when: !slider.pressed
                            value: Math.max(0, modeSlider.current)
                            restoreMode: Binding.RestoreNone
                        }
                        onMoved: {
                            const m = modeSlider.modes[Math.round(value)]
                            if (m && m.id !== full.st.listeningMode) {
                                full.applet.act({ type: "setListeningMode", mode: m.id })
                            }
                        }
                    }
                    Kirigami.Icon {
                        source: "audio-volume-high-symbolic"
                        Layout.preferredWidth: Kirigami.Units.iconSizes.small
                        Layout.preferredHeight: Kirigami.Units.iconSizes.small
                        opacity: slider.enabled ? 1 : 0.5
                    }
                }
                // tick labels, spread like the slider's stops
                Item {
                    id: ticks
                    Layout.fillWidth: true
                    Layout.leftMargin: Kirigami.Units.iconSizes.small + Kirigami.Units.smallSpacing
                    Layout.rightMargin: Kirigami.Units.iconSizes.small + Kirigami.Units.smallSpacing
                    implicitHeight: Kirigami.Units.gridUnit * 2.2
                    Repeater {
                        model: modeSlider.modes
                        delegate: PlasmaComponents3.Label {
                            required property var modelData
                            required property int index
                            readonly property real stop: modeSlider.count > 1 ? index / (modeSlider.count - 1) : 0
                            readonly property real gap: modeSlider.count > 1 ? ticks.width / (modeSlider.count - 1) : ticks.width
                            readonly property bool edge: index === 0 || index === modeSlider.count - 1
                            width: edge ? gap * 0.58 : gap * 0.8
                            x: stop * ticks.width - (index === 0 ? 0 : index === modeSlider.count - 1 ? width : width / 2)
                            horizontalAlignment: index === 0 ? Text.AlignLeft
                                               : index === modeSlider.count - 1 ? Text.AlignRight : Text.AlignHCenter
                            wrapMode: Text.Wrap
                            maximumLineCount: 2
                            font.pointSize: Kirigami.Theme.smallFont.pointSize
                            text: ({ noiseCancellation: "ANC", adaptive: i18n("Adaptive"),
                                     transparency: i18n("Transparency"), off: i18n("Off") })[modelData.id] || modelData.label
                            opacity: index === modeSlider.current ? 1 : 0.6
                            font.weight: index === modeSlider.current ? Font.DemiBold : Font.Normal
                        }
                    }
                }
                PlasmaComponents3.Label {
                    Layout.fillWidth: true
                    visible: !full.connected
                    horizontalAlignment: Text.AlignHCenter
                    opacity: 0.6
                    font: Kirigami.Theme.smallFont
                    text: i18n("Connect the AirPods to change the mode")
                }
            }

            // ---------------------------------------------------------- AirPods features
            Kirigami.Heading {
                Layout.fillWidth: true
                Layout.topMargin: Kirigami.Units.largeSpacing
                Layout.leftMargin: Kirigami.Units.smallSpacing
                visible: full.connected
                level: 5
                opacity: 0.7
                text: i18n("AirPods")
            }
            SwitchRow {
                visible: full.connected && full.st.conversation !== null && full.st.conversation !== undefined
                text: i18n("Conversation Awareness")
                subtitle: i18n("Lowers media when you speak")
                isOn: !!(full.st && full.st.conversation)
                onFlip: value => full.applet.act({ type: "setToggle", name: "conversationAwareness", value })
            }
            SwitchRow {
                visible: full.connected && full.st.earDetection !== null && full.st.earDetection !== undefined
                text: i18n("Automatic Ear Detection")
                subtitle: i18n("Pauses when you take out an AirPod")
                isOn: !!(full.st && full.st.earDetection)
                onFlip: value => full.applet.act({ type: "setToggle", name: "earDetection", value })
            }
            SwitchRow {
                text: i18n("HD Microphone")
                subtitle: full.st && full.st.mic && full.st.mic.streaming
                          ? i18n("Active · %1", full.st.mic.recorders.join(", "))
                          : i18n("High-quality AirPods mic, music stays AAC")
                isOn: !!full.prefs.hdMic
                onFlip: value => full.applet.act({ type: "setPref", key: "hdMic", value })
            }

            // ---------------------------------------------------------- OpenPods
            Kirigami.Heading {
                Layout.fillWidth: true
                Layout.topMargin: Kirigami.Units.largeSpacing
                Layout.leftMargin: Kirigami.Units.smallSpacing
                level: 5
                opacity: 0.7
                text: i18n("General")
            }
            SwitchRow {
                text: i18n("Window when AirPods are nearby")
                subtitle: i18n("When the case is opened")
                isOn: !!full.prefs.popup
                onFlip: value => full.applet.act({ type: "setPref", key: "popup", value })
            }
            SwitchRow {
                text: i18n("Connect automatically")
                subtitle: i18n("As soon as the AirPods go from the case into your ears")
                isOn: !!full.prefs.autoConnect
                onFlip: value => full.applet.act({ type: "setPref", key: "autoConnect", value })
            }
            SwitchRow {
                text: i18n("Start with Linux")
                isOn: !!full.prefs.startup
                onFlip: value => full.applet.act({ type: "setPref", key: "startup", value })
            }
            Item { Layout.preferredHeight: Kirigami.Units.smallSpacing }
        }
    }

    component SwitchRow: PlasmaComponents3.ItemDelegate {
        id: row
        property string subtitle
        property bool isOn
        signal flip(bool value)

        Layout.fillWidth: true
        onClicked: row.flip(!row.isOn)

        contentItem: RowLayout {
            spacing: Kirigami.Units.largeSpacing
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 0
                PlasmaComponents3.Label {
                    Layout.fillWidth: true
                    text: row.text
                    elide: Text.ElideRight
                }
                PlasmaComponents3.Label {
                    Layout.fillWidth: true
                    visible: row.subtitle.length > 0
                    text: row.subtitle
                    opacity: 0.7
                    font: Kirigami.Theme.smallFont
                    elide: Text.ElideRight
                }
            }
            PlasmaComponents3.Switch {
                id: sw
                checked: row.isOn
                // toggling by hand breaks the binding: follow OpenPods again once the reply had time to arrive,
                // so a refused change (or one made elsewhere) never leaves the switch showing the wrong state
                onToggled: {
                    row.flip(checked)
                    resync.restart()
                }
                Timer {
                    id: resync
                    interval: 2500
                    onTriggered: sw.checked = Qt.binding(() => row.isOn)
                }
            }
        }
    }
}
