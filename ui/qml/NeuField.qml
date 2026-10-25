import QtQuick
import QtQuick.Controls

TextField {
    id: control
    implicitHeight: 36
    padding: 10
    leftPadding: 12
    font.family: Theme.font
    font.pixelSize: 14
    color: readOnly ? Theme.muted : Theme.primary
    placeholderTextColor: Theme.muted
    selectByMouse: true
    activeFocusOnTab: true
    opacity: enabled ? 1 : .42
    background: InsetSurface {
        radius: Theme.radiusSM
        selected: control.activeFocus
    }
}
