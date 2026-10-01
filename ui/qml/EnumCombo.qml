import QtQuick
import QtQuick.Controls
ComboBox {
    id: control
    property string selectedValue: ''
    signal chosen(string value)
    textRole: 'label'; valueRole: 'value'; font.family: Theme.font; font.pixelSize: 14
    implicitHeight: 37; padding: 10; rightPadding: 28; activeFocusOnTab: true; opacity: enabled ? 1 : .42
    onSelectedValueChanged: currentIndex=Math.max(0,indexOfValue(selectedValue))
    Component.onCompleted: currentIndex=Math.max(0,indexOfValue(selectedValue))
    onActivated: chosen(currentValue)
    contentItem: Text { text: control.displayText; font: control.font; color: Theme.primary; elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter }
    background: InsetSurface { radius: Theme.radiusSM; selected: control.activeFocus }
    indicator: Text { x: control.width-22; y: 10; text: '⌄'; color: Theme.secondary }
    delegate: ItemDelegate { id: choice; required property var modelData; width: control.width; text: modelData.label; contentItem: Text { text: choice.text; font: control.font; color: Theme.primary } background: Rectangle { color: Theme.surface; border.color: Theme.accent; border.width: choice.highlighted ? 1 : 0 } }
    popup: Popup { y: control.height+3; width: control.width; padding: 5; height: Math.min(260,contentItem.implicitHeight+10); background: Rectangle { color: Theme.surface; radius: 12; border.color: Theme.secondary } contentItem: ListView { implicitHeight: contentHeight; model: control.popup.visible ? control.delegateModel : null; clip: true; reuseItems: true } }
}
