import QtQuick
import QtQuick.Controls

ComboBox {
    id: control
    property string selectedValue: ''
    signal chosen(string value)
    textRole: 'label'
    valueRole: 'value'
    font.family: Theme.font
    font.pixelSize: 14
    implicitHeight: 38
    padding: 10
    rightPadding: 28
    activeFocusOnTab: true
    opacity: enabled ? 1 : .42
    function syncSelection() {
        currentIndex = Math.max(0, indexOfValue(selectedValue));
    }
    onSelectedValueChanged: syncSelection()
    onModelChanged: Qt.callLater(syncSelection)
    Component.onCompleted: syncSelection()
    onActivated: chosen(currentValue)
    contentItem: Text {
        textFormat: Text.PlainText
        text: control.displayText
        font: control.font
        color: Theme.primary
        elide: Text.ElideRight
        verticalAlignment: Text.AlignVCenter
    }
    background: InsetSurface {
        radius: Theme.radiusSM
        selected: control.activeFocus
    }
    indicator: Text {
        textFormat: Text.PlainText
        x: control.width - 22
        y: 10
        text: '⌄'
        color: Theme.secondary
    }
    delegate: ItemDelegate {
        id: choice
        required property var modelData
        required property int index
        highlighted: control.highlightedIndex === index
        width: control.width
        text: modelData.label
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
        objectName: control.objectName + 'Popup'
        onOpened: choiceList.revealCurrent()
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
            id: choiceList
            objectName: control.objectName + 'Choices'
            function revealCurrent() {
                if (currentIndex >= 0)
                    positionViewAtIndex(currentIndex, ListView.Contain);
            }
            implicitHeight: contentHeight
            model: control.popup.visible ? control.delegateModel : null
            currentIndex: control.highlightedIndex
            onCurrentIndexChanged: Qt.callLater(revealCurrent)
            onCountChanged: Qt.callLater(revealCurrent)
            clip: true
            reuseItems: true
        }
    }
}
