import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root
    property var record: ({})
    property int segmentIndex: -1
    property bool documentMode: false
    signal seekRequested(real seconds)
    signal editing
    implicitHeight: Math.max(100, content.implicitHeight + 20)
    function syncText() {
        let value = root.record.draft_text || '';
        if (editor.text !== value) {
            let cursor = editor.cursorPosition;
            editor.syncing = true;
            editor.text = value;
            editor.cursorPosition = Math.min(cursor, editor.length);
            editor.syncing = false;
        }
    }
    onRecordChanged: Qt.callLater(syncText)
    Component.onCompleted: syncText()
    Rectangle {
        anchors.fill: parent
        radius: 10
        color: root.record.active ? '#292018' : root.documentMode ? Theme.surface : '#1b1b1b'
        border.width: root.record.active || root.record.uncertain || root.record.overlap ? 1 : 0
        border.color: Theme.accent
    }
    GridLayout {
        id: content
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 10
        columns: root.documentMode || width < 650 ? 1 : 2
        columnSpacing: 14
        rowSpacing: 5
        ColumnLayout {
            Layout.preferredWidth: content.columns === 1 ? -1 : 195
            Layout.fillWidth: content.columns === 1
            spacing: 4
            RowLayout {
                CompactAction {
                    text: Theme.timestamp(root.record.start || 0)
                    onClicked: root.seekRequested(root.record.start || 0)
                    ToolTip.visible: hovered
                    ToolTip.text: 'Ascolta da questo punto'
                }
                Help {
                    text: '– ' + Theme.timestamp(root.record.end || 0)
                }
            }
            EnumCombo {
                objectName: 'reviewSpeaker' + root.segmentIndex
                Layout.fillWidth: true
                model: root.record.speaker_options || []
                selectedValue: root.record.speaker_choice || ''
                displayText: currentIndex === 0 ? root.record.speaker_name || 'Speaker ?' : currentText
                ToolTip.visible: hovered
                ToolTip.text: currentIndex === 0 ? 'Assegnazione automatica · ' + (root.record.speaker_name || 'Speaker ?') : 'Assegnazione manuale'
                onChosen: value => meeting.setSpeaker(root.segmentIndex, value)
            }
        }
        ColumnLayout {
            Layout.fillWidth: true
            TextArea {
                id: editor
                property bool syncing: false
                objectName: 'reviewEditor' + root.segmentIndex
                Layout.fillWidth: true
                Layout.minimumHeight: 54
                textFormat: TextEdit.PlainText
                color: Theme.primary
                font.family: Theme.font
                font.pixelSize: 15
                wrapMode: TextEdit.Wrap
                selectByMouse: true
                activeFocusOnTab: true
                padding: 6
                background: Rectangle {
                    color: editor.activeFocus ? '#252525' : 'transparent'
                    radius: 5
                }
                onTextChanged: if (activeFocus && !syncing)
                    meeting.editText(root.segmentIndex, text)
                onActiveFocusChanged: {
                    if (activeFocus)
                        root.editing();
                    else
                        meeting.saveAll();
                }
                Keys.priority: Keys.BeforeItem
                Keys.onPressed: event => {
                    if ((event.modifiers & Qt.ControlModifier) && (event.key === Qt.Key_Z || event.key === Qt.Key_Y)) {
                        if (event.key === Qt.Key_Y || (event.modifiers & Qt.ShiftModifier))
                            meeting.redo();
                        else
                            meeting.undo();
                        event.accepted = true;
                    }
                }
            }
            Help {
                Layout.fillWidth: true
                visible: !!root.record.overlap || !!root.record.uncertain || !!root.record.quality_note
                text: root.record.quality_note || (root.record.overlap ? 'Voci sovrapposte' : 'Interlocutore incerto')
                color: Theme.accent
            }
        }
    }
}
