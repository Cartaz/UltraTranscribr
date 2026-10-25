import QtQuick

Item {
    id: root
    property real value: 0
    implicitHeight: 11
    InsetSurface {
        anchors.fill: parent
        radius: 6
    }
    Rectangle {
        x: 1
        y: 1
        width: Math.max(0, (parent.width - 2) * Math.min(100, Math.max(0, root.value)) / 100)
        height: parent.height - 2
        radius: 5
        color: Theme.accent
    }
}
