import QtQuick
import QtQuick.Controls

Item {
    id: root
    property string text: ''
    property string placeholder: 'Il testo trascritto apparirà qui.'
    property bool monospace: false
    property bool autoScroll: false
    property bool following: autoScroll
    function followLatest() {
        following = true;
        Qt.callLater(() => viewport.contentY = Math.max(0, viewport.contentHeight - scroll.availableHeight));
    }
    function syncText() {
        let previousY = viewport.contentY;
        let start = area.selectionStart;
        let end = area.selectionEnd;
        let next = root.text || root.placeholder;
        if (next.indexOf(area.text) === 0)
            area.insert(area.length, next.slice(area.length));
        else if (area.text !== next)
            area.text = next;
        if (start !== end)
            area.select(start, end);
        Qt.callLater(() => {
            if (root.autoScroll && root.following && start === end)
                root.followLatest();
            else
                viewport.contentY = previousY;
        });
    }
    onTextChanged: syncText()
    Component.onCompleted: syncText()
    InsetSurface {
        anchors.fill: parent
        strong: true
    }
    ScrollView {
        id: scroll
        anchors.fill: parent
        anchors.margins: 12
        clip: true
        ScrollBar.vertical: ScrollBar {
            policy: ScrollBar.AsNeeded
            onPressedChanged: if (pressed)
                root.following = false
        }
        Flickable {
            id: viewport
            objectName: 'transcriptViewport'
            width: scroll.availableWidth
            height: scroll.availableHeight
            contentWidth: width
            contentHeight: area.height
            clip: true
            TextArea {
                id: area
                objectName: 'transcriptText'
                width: viewport.width
                height: Math.max(viewport.height, implicitHeight)
                textFormat: TextEdit.PlainText
                readOnly: true
                Keys.onPressed: event => {
                    if ([Qt.Key_Up, Qt.Key_PageUp, Qt.Key_Home].indexOf(event.key) >= 0)
                        root.following = false;
                    event.accepted = false;
                }
                selectByMouse: true
                activeFocusOnTab: true
                wrapMode: TextEdit.Wrap
                color: root.text ? (root.monospace ? Theme.secondary : Theme.primary) : Theme.secondary
                font.family: root.monospace ? 'DejaVu Sans Mono' : Theme.font
                font.pixelSize: root.monospace ? 12 : 14
                background: null
                padding: 0
            }
        }
        WheelHandler {
            target: null
            onWheel: event => {
                if (event.angleDelta.y > 0)
                    root.following = false;
                event.accepted = false;
            }
        }
        Connections {
            target: viewport
            function onMovementStarted() {
                root.following = false;
            }
        }
    }
    NeuButton {
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: 14
        visible: root.autoScroll && !root.following
        compact: true
        text: 'Torna al live'
        onClicked: root.followLatest()
    }
}
