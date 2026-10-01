import QtQuick
import QtQuick.Controls

Button {
    id: control
    property bool selected: false
    property bool compact: false
    property bool alignLeft: false
    property bool wrapText: false
    property color normalColor: Theme.secondary
    implicitHeight: compact ? 30 : 36
    implicitWidth: label.implicitWidth + (compact ? 20 : 28)
    padding: compact ? 10 : 14
    font.family: Theme.font
    font.pixelSize: 14
    opacity: enabled ? 1 : .42
    activeFocusOnTab: true
    contentItem: Text {
        id: label
        textFormat: Text.PlainText
        text: control.text
        font: control.font
        color: control.selected ? Theme.accent : control.hovered ? Theme.primary : control.normalColor
        horizontalAlignment: control.alignLeft ? Text.AlignLeft : Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        wrapMode: control.wrapText ? Text.WordWrap : Text.NoWrap
        elide: control.wrapText ? Text.ElideNone : Text.ElideRight
    }
    background: Item {
        RaisedSurface {
            anchors.fill: parent
            radius: Theme.radiusMD
            soft: true
            visible: !control.down && !control.selected && !control.activeFocus && !control.flat
        }
        InsetSurface {
            anchors.fill: parent
            radius: Theme.radiusMD
            visible: control.down || control.selected || control.activeFocus
            selected: control.selected || control.activeFocus
        }
    }
}
