/* A setting with a fixed set of values: title + subtitle on the left, combo box on the right. */
import QtQuick
import QtQuick.Layouts

import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents3

RowLayout {
    id: choice
    property string text
    property string subtitle
    property var options: []      // [{ value, text }]
    property var current          // value currently set on the AirPods
    signal pick(var value)

    Layout.fillWidth: true
    Layout.leftMargin: Kirigami.Units.largeSpacing
    Layout.rightMargin: Kirigami.Units.largeSpacing
    Layout.topMargin: Kirigami.Units.smallSpacing
    Layout.bottomMargin: Kirigami.Units.smallSpacing
    spacing: Kirigami.Units.largeSpacing

    ColumnLayout {
        Layout.fillWidth: true
        spacing: 0
        PlasmaComponents3.Label {
            Layout.fillWidth: true
            text: choice.text
            wrapMode: Text.Wrap
        }
        PlasmaComponents3.Label {
            Layout.fillWidth: true
            visible: choice.subtitle.length > 0
            text: choice.subtitle
            opacity: 0.7
            font: Kirigami.Theme.smallFont
            wrapMode: Text.Wrap
        }
    }
    PlasmaComponents3.ComboBox {
        id: box
        enabled: choice.enabled
        model: choice.options
        textRole: "text"
        valueRole: "value"
        currentIndex: {
            for (let k = 0; k < choice.options.length; ++k) if (choice.options[k].value === choice.current) return k
            return -1
        }
        onActivated: index => choice.pick(choice.options[index].value)
    }
}
