import QtQuick
Window {
    width: 460; height: 76; color: 'transparent'
    flags: Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus | Qt.WindowTransparentForInput
    Item { anchors.fill: parent; anchors.margins: 10; RaisedSurface { anchors.fill: parent; radius: 16; selected: true }
        Row { anchors.fill: parent; anchors.margins: 18; spacing: 14
            Rectangle { anchors.verticalCenter: parent.verticalCenter; width: 10; height: 10; radius: 5; color: Theme.accent }
            Column { anchors.verticalCenter: parent.verticalCenter; width: 320; spacing: 1; Text { text: 'Dettatura'; color: Theme.accent; font.family: Theme.font; font.pixelSize: 13; font.bold: true } Text { text: 'Sto ascoltando…'; color: Theme.primary; font.family: Theme.font; font.pixelSize: 12 } }
            Row { anchors.verticalCenter: parent.verticalCenter; spacing: 4; height: 24; Repeater { model: 5; Rectangle { id: bar; required property int index; width: 3; radius: 3; color: Theme.accent; anchors.verticalCenter: parent.verticalCenter; SequentialAnimation on height { loops: Animation.Infinite; NumberAnimation { from: 7; to: 22; duration: 450+bar.index*40 } NumberAnimation { from: 22; to: 7; duration: 450+bar.index*40 } } } } }
        }
    }
}
