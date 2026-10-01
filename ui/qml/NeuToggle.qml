import QtQuick
import QtQuick.Controls
Switch {
    id: control
    property string description: ''
    implicitHeight: description ? 52 : 42; implicitWidth: 240; padding: 13; opacity: enabled ? 1 : .42
    font.family: Theme.font; font.pixelSize: 13; activeFocusOnTab: true
    indicator: Item { width: 40; height: 22; x: control.width-width-13; y: (control.height-height)/2; InsetSurface { anchors.fill: parent; radius: 11; selected: control.checked || control.activeFocus } Rectangle { x: control.checked ? 21 : 5; y: 4; width: 14; height: 14; radius: 7; color: control.checked ? Theme.accent : Theme.muted; Behavior on x { NumberAnimation { duration: 120 } } } }
    contentItem: Column { rightPadding: 48; spacing: 2; Text { text: control.text; color: Theme.primary; font.family: Theme.font; font.pixelSize: 13; font.bold: true } Text { width: control.width-75; text: control.description; color: Theme.muted; wrapMode: Text.WordWrap; font.family: Theme.font; font.pixelSize: 11 } }
    background: InsetSurface { radius: Theme.radiusMD }
}
