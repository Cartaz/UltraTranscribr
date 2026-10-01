import QtQuick
import QtQuick.Controls

ComboBox {
    id: control
    property string keyRole: 'value'
    property string labelRole: 'name'
    property string selectedValue: ''
    signal chosen(string value)
    function syncSelection() {
        if (!model || typeof model.get !== 'function')
            return;
        for (let i = 0; i < model.count; i++)
            if (String(model.get(i)[keyRole] == null ? '' : model.get(i)[keyRole]) === selectedValue) {
                currentIndex = i;
                return;
            }
        currentIndex = !selectedValue && model.count ? 0 : -1;
    }
    onSelectedValueChanged: syncSelection()
    onModelChanged: syncSelection()
    Component.onCompleted: syncSelection()
    Connections {
        target: control.model
        function onCountChanged() {
            control.syncSelection();
        }
    }
    textRole: 'record'
    font.family: Theme.font
    font.pixelSize: 14
    implicitHeight: 38
    padding: 10
    rightPadding: 28
    activeFocusOnTab: true
    opacity: enabled ? 1 : .42
    contentItem: Text {
        textFormat: Text.PlainText
        text: control.currentIndex >= 0 && control.model && typeof control.model.get === 'function' ? control.model.get(control.currentIndex)[control.labelRole] || '' : control.selectedValue ? 'Non disponibile (' + control.selectedValue + ')' : ''
        font: control.font
        color: Theme.primary
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
    indicator: Text {
        textFormat: Text.PlainText
        x: control.width - 22
        y: 10
        text: '⌄'
        color: Theme.secondary
    }
    background: InsetSurface {
        radius: Theme.radiusSM
        selected: control.activeFocus
    }
    onActivated: chosen(String(model.get(currentIndex)[keyRole] == null ? '' : model.get(currentIndex)[keyRole]))
    delegate: ItemDelegate {
        id: choice
        required property var record
        width: control.width
        text: record[control.labelRole] || ''
        font: control.font
        contentItem: Text {
            textFormat: Text.PlainText
            text: choice.text
            font: control.font
            color: Theme.primary
        }
        background: Rectangle {
            color: Theme.surface
            border.color: Theme.accent
            border.width: choice.highlighted ? 1 : 0
        }
    }
    popup: Popup {
        y: control.height + 3
        width: control.width
        padding: 5
        height: Math.min(260, contentItem.implicitHeight + 10)
        background: Rectangle {
            color: Theme.surface
            radius: 12
            border.color: Theme.secondary
        }
        contentItem: ListView {
            implicitHeight: contentHeight
            model: control.popup.visible ? control.delegateModel : null
            clip: true
            reuseItems: true
            ScrollIndicator.vertical: ScrollIndicator {}
        }
    }
}
