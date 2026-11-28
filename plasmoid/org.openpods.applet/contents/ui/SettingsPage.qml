/* Scrollable page for the applet's StackView; children go into one column. */
import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents3

PlasmaComponents3.ScrollView {
    id: page
    property string title
    default property alias content: col.data

    // sub pages sit under a PlasmoidHeading, which collapses the popup's margins: bring the gap back ourselves
    leftPadding: QQC2.StackView.index > 0 ? Kirigami.Units.smallSpacing : 0
    rightPadding: leftPadding
    contentWidth: availableWidth
    QQC2.ScrollBar.horizontal.policy: QQC2.ScrollBar.AlwaysOff

    ColumnLayout {
        id: col
        width: page.availableWidth
        spacing: Kirigami.Units.smallSpacing
    }
}
