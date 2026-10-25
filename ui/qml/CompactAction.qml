import QtQuick
import QtQuick.Controls

// The original review uses plain browser buttons, not neumorphic toolbar buttons.
Button {
    id: control
    implicitWidth: label.implicitWidth + 16
    implicitHeight: 22
    padding: 2
    leftPadding: 8
    rightPadding: 8
    font.family: Theme.font
    font.pixelSize: 14
    opacity: enabled ? 1 : .42
    activeFocusOnTab: true
    contentItem: Text {
        id: label
        textFormat: Text.PlainText
        text: control.text
        font: control.font
        color: Theme.primary
        verticalAlignment: Text.AlignVCenter
        horizontalAlignment: Text.AlignHCenter
    }
    background: Rectangle {
        radius: 2
        color: control.down ? '#555555' : '#6b6b6b'
        border.width: control.activeFocus ? 1 : 0
        border.color: Theme.accent
    }
}
