/* One setting with a switch: title, optional grey subtitle, whole row clickable (like KDE's own applets). */
import QtQuick
import QtQuick.Layouts

import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents3

PlasmaComponents3.ItemDelegate {
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
                wrapMode: Text.Wrap
            }
        }
        PlasmaComponents3.Switch {
            id: sw
            enabled: row.enabled
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
