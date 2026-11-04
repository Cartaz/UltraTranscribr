import QtQuick
import QtQuick.Layouts

Item {
    id: root
    property real padding: 14
    default property alias content: container.data
    implicitHeight: container.implicitHeight + 28
    RaisedSurface {
        anchors.fill: parent
    }
    ColumnLayout {
        id: container
        anchors.fill: parent
        anchors.margins: root.padding
        anchors.topMargin: 14
        anchors.bottomMargin: 14
        spacing: 9
    }
}
