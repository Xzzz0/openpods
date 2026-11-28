/*
 * The whole OpenPods UI, inside KDE's system tray: an overview page plus sub pages (StackView, like the
 * Bluetooth and Networks applets). Every change goes to the running OpenPods via applet.act().
 */
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
    readonly property var set: st && st.settings ? st.settings : ({})
    readonly property var caps: st && st.caps ? st.caps : []

    function has(cap) { return caps.indexOf(cap) >= 0 }
    function known(v) { return v !== null && v !== undefined }
    function act(msg) { applet.act(msg) }
    function openPage(name) {
        const page = ({ airpods: airpodsPage, controls: controlsPage, mic: micPage, hearing: hearingPage,
                        general: generalPage })[name]
        if (!page) return
        stack.pop(null)
        stack.push(page)
    }

    collapseMarginsHint: true
    Layout.minimumWidth: Kirigami.Units.gridUnit * 18
    Layout.preferredWidth: Kirigami.Units.gridUnit * 20
    Layout.preferredHeight: Kirigami.Units.gridUnit * 26

    // the tray shows the applet title; sub pages get their own heading with a back button
    header: PlasmaExtras.PlasmoidHeading {
        visible: stack.depth > 1
        contentItem: RowLayout {
            spacing: Kirigami.Units.smallSpacing
            PlasmaComponents3.ToolButton {
                icon.name: full.mirrored ? "go-next" : "go-previous"
                display: PlasmaComponents3.AbstractButton.IconOnly
                text: i18n("Back")
                onClicked: stack.pop()
                PlasmaComponents3.ToolTip.text: text
                PlasmaComponents3.ToolTip.visible: hovered
            }
            Kirigami.Heading {
                Layout.fillWidth: true
                level: 3
                elide: Text.ElideRight
                text: stack.currentItem ? (stack.currentItem as SettingsPage)?.title ?? "" : ""
            }
        }
    }

    Connections {
        target: full.applet
        function onExpandedChanged() {
            if (!full.applet.expanded) stack.pop(null)  // always open on the overview
        }
        function onPageRequested(name) { full.openPage(name) }
    }

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

    QQC2.StackView {
        id: stack
        anchors.fill: parent
        visible: !!full.st
        initialItem: overviewPage
    }

    // ================================================================================================ overview
    Component {
        id: overviewPage
        SettingsPage {
            title: "OpenPods"

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
                        onTriggered: full.act({ type: "update" })
                    }
                ]
            }

            // ---------------------------------------------------------- no AirPods paired yet
            PlasmaExtras.PlaceholderMessage {
                Layout.fillWidth: true
                Layout.margins: Kirigami.Units.gridUnit
                visible: !full.device
                iconName: "audio-headphones"
                text: i18n("No AirPods paired")
                explanation: i18n("Open the case next to the PC, hold the button on the back until the light flashes white, then pair them in the Bluetooth settings.")
                helpfulAction: QQC2.Action {
                    text: i18n("Bluetooth Settings")
                    icon.name: "preferences-system-bluetooth"
                    onTriggered: full.act({ type: "openBluetoothSettings" })
                }
            }

            // ---------------------------------------------------------- device
            RowLayout {
                Layout.fillWidth: true
                Layout.margins: Kirigami.Units.smallSpacing
                visible: !!full.device
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
                        text: full.device ? full.device.name : ""
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
                    onClicked: full.act({ type: full.connected ? "disconnect" : "connect", id: full.device.id })
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
                        { key: "left", label: i18n("Left"), ear: "left" },
                        { key: "right", label: i18n("Right"), ear: "right" },
                        { key: "case", label: i18n("Case"), ear: "" },
                        { key: "headphone", label: i18n("Battery"), ear: "" },
                    ]
                    delegate: ColumnLayout {
                        id: cell
                        required property var modelData
                        readonly property var bat: full.st && full.st.battery ? full.st.battery[modelData.key] : null
                        readonly property bool known: !!bat && bat.pct !== null && bat.pct !== undefined
                        readonly property string ear: full.connected && full.st && full.st.ear && modelData.ear
                                                      ? full.st.ear[modelData.ear] || "" : ""
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
                            text: cell.modelData.label + (cell.ear === "inEar" ? " · " + i18n("in ear")
                                                        : cell.ear === "inCase" ? " · " + i18n("in case") : "")
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
                                full.act({ type: "setListeningMode", mode: m.id })
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

            // ---------------------------------------------------------- quick switches
            SectionHeading {
                visible: full.connected
                text: i18n("Quick Settings")
            }
            SwitchRow {
                visible: full.connected && full.known(full.set.conversationAwareness)
                text: i18n("Conversation Awareness")
                subtitle: i18n("Lowers media when you speak")
                isOn: !!full.set.conversationAwareness
                onFlip: value => full.act({ type: "setToggle", name: "conversationAwareness", value })
            }
            SwitchRow {
                text: i18n("HD Microphone")
                subtitle: full.st && full.st.mic && full.st.mic.streaming
                          ? i18n("Active · %1", full.st.mic.recorders.join(", "))
                          : i18n("High-quality AirPods mic, music stays AAC")
                isOn: !!full.prefs.hdMic
                onFlip: value => full.act({ type: "setPref", key: "hdMic", value })
            }

            // ---------------------------------------------------------- sub pages
            SectionHeading { text: i18n("Settings") }
            NavRow {
                visible: !!full.device
                iconName: "audio-headphones"
                text: i18n("AirPods")
                subtitle: i18n("Ear detection, volume, noise control")
                onClicked: full.openPage("airpods")
            }
            NavRow {
                visible: !!full.device
                iconName: "input-touchpad"
                text: i18n("Press and Hold")
                subtitle: i18n("Stem, press speed, tone volume")
                onClicked: full.openPage("controls")
            }
            NavRow {
                iconName: "audio-input-microphone"
                text: i18n("Microphone")
                subtitle: full.prefs.hdMic ? i18n("HD microphone on") : i18n("HD microphone off")
                onClicked: full.openPage("mic")
            }
            NavRow {
                visible: !!full.device && (full.has("hearingAid") || full.has("mediaAssist") || full.has("heartRate"))
                iconName: "preferences-desktop-accessibility"
                text: i18n("Hearing & Health")
                subtitle: i18n("Hearing assistance, heart rate")
                onClicked: full.openPage("hearing")
            }
            NavRow {
                iconName: "configure"
                text: i18n("General")
                subtitle: i18n("Startup, notifications, updates")
                onClicked: full.openPage("general")
            }
            Item { Layout.preferredHeight: Kirigami.Units.smallSpacing }
        }
    }

    // notice at the top of every AirPods page while not connected (values are the last known ones)
    component NotConnectedNote: Kirigami.InlineMessage {
        Layout.fillWidth: true
        Layout.margins: Kirigami.Units.smallSpacing
        visible: !full.connected
        type: Kirigami.MessageType.Information
        text: i18n("Connect the AirPods to change these settings.")
    }

    // ================================================================================================ AirPods
    Component {
        id: airpodsPage
        SettingsPage {
            title: i18n("AirPods")
            NotConnectedNote {}
            SwitchRow {
                visible: full.has("earDetection")
                enabled: full.connected
                text: i18n("Automatic Ear Detection")
                subtitle: i18n("Pauses when you take out an AirPod")
                isOn: !!full.set.earDetection
                onFlip: value => full.act({ type: "setToggle", name: "earDetection", value })
            }
            SwitchRow {
                visible: full.has("conversationAwareness")
                enabled: full.connected
                text: i18n("Conversation Awareness")
                subtitle: i18n("Lowers media and lets voices in when you start speaking")
                isOn: !!full.set.conversationAwareness
                onFlip: value => full.act({ type: "setToggle", name: "conversationAwareness", value })
            }
            SwitchRow {
                visible: full.has("personalizedVolume")
                enabled: full.connected
                text: i18n("Personalized Volume")
                subtitle: i18n("Adjusts media volume to your surroundings")
                isOn: !!full.set.personalizedVolume
                onFlip: value => full.act({ type: "setToggle", name: "personalizedVolume", value })
            }
            SwitchRow {
                visible: full.has("oneBudAnc")
                enabled: full.connected
                text: i18n("Noise Cancellation with One AirPod")
                subtitle: i18n("Keeps noise control on when only one AirPod is in")
                isOn: !!full.set.oneBudAnc
                onFlip: value => full.act({ type: "setToggle", name: "oneBudAnc", value })
            }
            SwitchRow {
                visible: full.has("allowOff")
                enabled: full.connected
                text: i18n("Allow “Off” Mode")
                subtitle: i18n("Adds “Off” to the noise control modes")
                isOn: !!full.set.allowOff
                onFlip: value => full.act({ type: "setToggle", name: "allowOff", value })
            }
            Item { Layout.preferredHeight: Kirigami.Units.smallSpacing }
        }
    }

    // ================================================================================================ press and hold
    Component {
        id: controlsPage
        SettingsPage {
            id: controls
            title: i18n("Press and Hold")
            readonly property var stemModes: full.st && full.st.stemModes ? full.st.stemModes : []

            NotConnectedNote {}
            SectionHeading {
                visible: full.has("listeningMode")
                text: i18n("Press and hold the stem to switch between")
            }
            Repeater {
                model: [
                    { id: "noiseCancellation", text: i18n("Noise Cancellation"), cap: "listeningMode" },
                    { id: "transparency", text: i18n("Transparency"), cap: "listeningMode" },
                    { id: "adaptive", text: i18n("Adaptive"), cap: "adaptive" },
                    { id: "off", text: i18n("Off"), cap: "listeningMode" },
                ]
                delegate: PlasmaComponents3.CheckDelegate {
                    id: modeBox
                    required property var modelData
                    readonly property bool on: controls.stemModes.indexOf(modelData.id) >= 0
                    Layout.fillWidth: true
                    visible: full.has(modelData.cap)
                    text: modelData.text
                    checked: on
                    // at least two modes must stay selected (AirPods refuse fewer)
                    enabled: !!full.device && !(on && controls.stemModes.length <= 2)
                    onToggled: {
                        const next = controls.stemModes.filter(m => m !== modelData.id)
                        if (checked) next.push(modelData.id)
                        full.act({ type: "setStemModes", id: full.device.id, modes: next })
                        checked = Qt.binding(() => modeBox.on)
                    }
                }
            }

            SectionHeading {
                visible: full.has("pressSpeed") || full.has("holdDuration")
                text: i18n("Stem")
            }
            ChoiceRow {
                visible: full.has("pressSpeed")
                enabled: full.connected
                text: i18n("Press speed")
                subtitle: i18n("How fast you press twice or three times")
                options: [{ value: "default", text: i18n("Default") }, { value: "slower", text: i18n("Slower") },
                          { value: "slowest", text: i18n("Slowest") }]
                current: full.set.pressSpeed
                onPick: value => full.act({ type: "setPressSpeed", value })
            }
            ChoiceRow {
                visible: full.has("holdDuration")
                enabled: full.connected
                text: i18n("Press and hold duration")
                options: [{ value: "default", text: i18n("Default") }, { value: "shorter", text: i18n("Shorter") },
                          { value: "shortest", text: i18n("Shortest") }]
                current: full.set.holdDuration
                onPick: value => full.act({ type: "setHoldDuration", value })
            }

            SectionHeading {
                visible: full.has("toneVolume")
                text: i18n("Tone volume")
            }
            ValueSlider {
                visible: full.has("toneVolume")
                enabled: full.connected
                from: 15
                to: 100
                stepSize: 5
                current: full.known(full.set.toneVolume) ? full.set.toneVolume : 100
                suffix: " %"
                onCommit: value => full.act({ type: "setToneVolume", value })
            }
            PlasmaComponents3.Label {
                Layout.fillWidth: true
                Layout.leftMargin: Kirigami.Units.largeSpacing
                Layout.rightMargin: Kirigami.Units.largeSpacing
                visible: full.has("toneVolume")
                opacity: 0.7
                font: Kirigami.Theme.smallFont
                wrapMode: Text.Wrap
                text: i18n("Volume of the sounds the AirPods play themselves, e.g. when switching modes.")
            }
            Item { Layout.preferredHeight: Kirigami.Units.smallSpacing }
        }
    }

    // ================================================================================================ microphone
    Component {
        id: micPage
        SettingsPage {
            title: i18n("Microphone")
            SwitchRow {
                text: i18n("HD Microphone")
                subtitle: i18n("Apple's high-quality mic stream. Music keeps playing in AAC instead of switching to the headset profile.")
                isOn: !!full.prefs.hdMic
                onFlip: value => full.act({ type: "setPref", key: "hdMic", value })
            }
            PlasmaComponents3.Label {
                Layout.fillWidth: true
                Layout.leftMargin: Kirigami.Units.largeSpacing
                Layout.rightMargin: Kirigami.Units.largeSpacing
                visible: !!full.prefs.hdMic
                opacity: 0.7
                font: Kirigami.Theme.smallFont
                wrapMode: Text.Wrap
                text: full.st && full.st.mic && full.st.mic.streaming
                      ? i18n("In use by %1", full.st.mic.recorders.join(", "))
                      : i18n("Ready – starts as soon as an app records from “AirPods Mic (HD)”.")
            }
            SectionHeading {
                visible: full.has("micSide")
                text: i18n("Microphone side")
            }
            ChoiceRow {
                visible: full.has("micSide")
                enabled: full.connected
                text: i18n("Use the microphone of")
                options: [{ value: "automatic", text: i18n("Automatic") }, { value: "left", text: i18n("Left AirPod") },
                          { value: "right", text: i18n("Right AirPod") }]
                current: full.set.micSide
                onPick: value => full.act({ type: "setMicSide", side: value })
            }
            Item { Layout.preferredHeight: Kirigami.Units.smallSpacing }
        }
    }

    // ================================================================================================ hearing & health
    Component {
        id: hearingPage
        SettingsPage {
            title: i18n("Hearing & Health")
            NotConnectedNote {}
            SwitchRow {
                visible: full.has("hearingAid")
                enabled: full.connected && full.set.hearingAidEnrolled !== false
                text: i18n("Hearing Aid")
                subtitle: full.set.hearingAidEnrolled === false
                          ? i18n("Set it up once with an iPhone (hearing test) to use it here.")
                          : i18n("Clinical-grade hearing assistance")
                isOn: !!full.set.hearingAidEnabled
                onFlip: value => full.act({ type: "setHearingAid", value })
            }
            SectionHeading {
                visible: full.has("mediaAssist")
                text: i18n("Media Assist")
            }
            SwitchRow {
                visible: full.has("mediaAssist")
                enabled: full.connected
                text: i18n("Phone and video calls")
                subtitle: i18n("Uses your hearing profile for calls")
                isOn: !!full.set.mediaAssistCalls
                onFlip: value => full.act({ type: "setMediaAssist", name: "calls", value })
            }
            SwitchRow {
                visible: full.has("mediaAssist")
                enabled: full.connected
                text: i18n("Music and video")
                subtitle: i18n("Uses your hearing profile for media")
                isOn: !!full.set.mediaAssistMedia
                onFlip: value => full.act({ type: "setMediaAssist", name: "media", value })
            }
            SectionHeading {
                visible: full.has("heartRate")
                text: i18n("Health")
            }
            SwitchRow {
                visible: full.has("heartRate")
                enabled: full.connected
                readonly property var hr: full.st && full.st.heartRate ? full.st.heartRate : ({})
                text: i18n("Heart Rate")
                subtitle: hr.heartRate && hr.heartRateBpm ? i18n("%1 BPM", hr.heartRateBpm)
                                                         : i18n("Measures your heart rate while you wear them")
                isOn: !!hr.heartRate
                onFlip: value => full.act({ type: "setHeartRate", value })
            }
            Item { Layout.preferredHeight: Kirigami.Units.smallSpacing }
        }
    }

    // ================================================================================================ general
    Component {
        id: generalPage
        SettingsPage {
            title: i18n("General")

            SwitchRow {
                text: i18n("Start with Linux")
                subtitle: i18n("OpenPods runs in the background, this applet is its interface")
                isOn: !!full.prefs.startup
                onFlip: value => full.act({ type: "setPref", key: "startup", value })
            }
            SwitchRow {
                text: i18n("Window when AirPods are nearby")
                subtitle: i18n("When the case is opened")
                isOn: !!full.prefs.popup
                onFlip: value => full.act({ type: "setPref", key: "popup", value })
            }
            SwitchRow {
                text: i18n("Connect automatically")
                subtitle: i18n("As soon as the AirPods go from the case into your ears")
                isOn: !!full.prefs.autoConnect
                onFlip: value => full.act({ type: "setPref", key: "autoConnect", value })
            }

            SectionHeading {
                visible: !!full.device
                text: i18n("Lower other audio during calls")
            }
            ValueSlider {
                visible: !!full.device
                enabled: !!full.device
                from: 10
                to: 90
                stepSize: 5
                current: full.st && full.st.duckPercent ? full.st.duckPercent : 50
                suffix: " %"
                onCommit: value => full.act({ type: "setHostSetting", id: full.device.id, name: "duckPercent", value })
            }

            SectionHeading { text: i18n("Updates") }
            SwitchRow {
                text: i18n("Update automatically")
                subtitle: i18n("Installs new versions when OpenPods starts")
                isOn: !!(full.st && full.st.update && full.st.update.auto)
                onFlip: value => full.act({ type: "setAutoUpdate", value })
            }
            RowLayout {
                id: updRow
                readonly property var upd: full.st && full.st.update ? full.st.update : ({})
                Layout.fillWidth: true
                Layout.leftMargin: Kirigami.Units.largeSpacing
                Layout.rightMargin: Kirigami.Units.largeSpacing
                PlasmaComponents3.Label {
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                    text: updRow.upd.available ? i18n("Version %1 · %2 is available", updRow.upd.version, updRow.upd.available)
                        : updRow.upd.status === "checking" ? i18n("Version %1 · checking…", updRow.upd.version)
                        : updRow.upd.checked ? i18n("Version %1 · up to date", updRow.upd.version)
                        : i18n("Version %1", updRow.upd.version)
                }
                PlasmaComponents3.Button {
                    text: updRow.upd.available ? i18n("Update") : i18n("Check now")
                    icon.name: updRow.upd.available ? "download" : "view-refresh"
                    enabled: !updRow.upd.installing && updRow.upd.status !== "checking"
                    onClicked: full.act({ type: updRow.upd.available ? "update" : "checkUpdate" })
                }
            }

            SectionHeading { text: i18n("More") }
            NavRow {
                iconName: "preferences-system-bluetooth"
                text: i18n("Bluetooth Settings")
                subtitle: i18n("Pair new AirPods")
                onClicked: full.act({ type: "openBluetoothSettings" })
            }
            NavRow {
                iconName: "documentinfo"
                text: i18n("Release Notes")
                onClicked: full.applet.showAbout()
            }
            NavRow {
                iconName: "license"
                text: i18n("License")
                subtitle: i18n("GPL-3.0 · based on WPods")
                onClicked: full.act({ type: "openLegal", name: "license" })
            }
            NavRow {
                iconName: "application-exit"
                text: i18n("Quit OpenPods")
                subtitle: i18n("Stops the background service until the next login")
                onClicked: full.act({ type: "quit" })
            }
            Item { Layout.preferredHeight: Kirigami.Units.smallSpacing }
        }
    }

    // slider that sends its value once on release (the AirPods don't like a stream of writes)
    component ValueSlider: RowLayout {
        id: vs
        property real from
        property real to
        property real stepSize: 1
        property real current
        property string suffix
        signal commit(int value)

        Layout.fillWidth: true
        Layout.leftMargin: Kirigami.Units.largeSpacing
        Layout.rightMargin: Kirigami.Units.largeSpacing
        spacing: Kirigami.Units.smallSpacing

        PlasmaComponents3.Slider {
            id: vsSlider
            Layout.fillWidth: true
            enabled: vs.enabled
            from: vs.from
            to: vs.to
            stepSize: vs.stepSize
            snapMode: QQC2.Slider.SnapAlways
            Binding on value {
                when: !vsSlider.pressed
                value: vs.current
                restoreMode: Binding.RestoreNone
            }
            onPressedChanged: if (!pressed && Math.round(value) !== Math.round(vs.current)) vs.commit(Math.round(value))
        }
        PlasmaComponents3.Label {
            Layout.minimumWidth: Kirigami.Units.gridUnit * 2.5
            horizontalAlignment: Text.AlignRight
            text: Math.round(vsSlider.value) + vs.suffix
        }
    }
}
