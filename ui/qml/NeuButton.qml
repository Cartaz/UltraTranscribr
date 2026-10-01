import QtQuick
import QtQuick.Controls
Button {
    id: control
    property bool selected: false
    property bool compact: false
    property bool alignLeft: false
    implicitHeight: compact ? 32 : 37
    implicitWidth: label.implicitWidth+(compact ? 20 : 28)
    padding: compact ? 10 : 14
    font.family: Theme.font; font.pixelSize: 14
    opacity: enabled ? 1 : .42
    activeFocusOnTab: true
    contentItem: Text { id: label; text: control.text; font: control.font; color: control.selected || control.hovered ? Theme.accent : Theme.secondary; horizontalAlignment: control.alignLeft ? Text.AlignLeft : Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight }
    background: Item {
        RaisedSurface { anchors.fill: parent; radius: Theme.radiusMD; soft: true; visible: !control.down && !control.selected && !control.activeFocus && !control.flat }
        InsetSurface { anchors.fill: parent; radius: Theme.radiusMD; visible: control.down || control.selected || control.activeFocus; selected: control.selected || control.activeFocus }
    }
}
