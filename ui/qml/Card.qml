import QtQuick
import QtQuick.Layouts

Item {
    id: root
    property real padding: 20
    default property alias content: container.data
    implicitHeight: container.implicitHeight + 36
    RaisedSurface {
        anchors.fill: parent
    }
    ColumnLayout {
        id: container
        anchors.fill: parent
        anchors.margins: root.padding
        anchors.topMargin: 18
        anchors.bottomMargin: 18
        spacing: 13
    }
}
