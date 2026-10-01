import QtQuick
import QtQuick.Controls

Item {
    id: root
    property string text: ''
    property string placeholder: 'Il testo trascritto apparirà qui.'
    property bool monospace: false
    property bool autoScroll: false
    InsetSurface {
        anchors.fill: parent
        strong: true
    }
    ScrollView {
        id: scroll
        anchors.fill: parent
        anchors.margins: 15
        clip: true
        TextArea {
            id: area
            textFormat: TextEdit.PlainText
            text: root.text || root.placeholder
            readOnly: true
            selectByMouse: true
            activeFocusOnTab: true
            wrapMode: TextEdit.Wrap
            color: root.text ? (root.monospace ? Theme.secondary : Theme.primary) : Theme.muted
            font.family: root.monospace ? 'DejaVu Sans Mono' : Theme.font
            font.pixelSize: root.monospace ? 12 : 14
            background: null
            padding: 0
            onTextChanged: if (root.autoScroll)
                Qt.callLater(() => scroll.contentItem.contentY = Math.max(0, area.height - scroll.availableHeight))
        }
    }
}
