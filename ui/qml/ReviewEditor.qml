import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: root
    objectName: 'reviewEditorModes'
    property string mode: 'compact'
    property bool following: true
    property int selectedIndex: 0
    property var selectedRecord: ({})
    signal seekRequested(real seconds)
    function syncSelected() {
        selectedRecord = meetingSegments.get(selectedIndex);
    }
    function followCurrent() {
        if (!following || !meeting.activeIndices.length)
            return;
        let index = meeting.activeIndices[0];
        selectedIndex = index;
        syncSelected();
        if (mode === 'columns')
            indexList.positionViewAtIndex(index, ListView.Contain);
        else
            review.positionViewAtIndex(index, ListView.Contain);
    }
    onSelectedIndexChanged: syncSelected()
    onModeChanged: {
        syncSelected();
        Qt.callLater(followCurrent);
    }
    Component.onCompleted: syncSelected()
    Connections {
        target: meeting
        function onPlaybackChanged() {
            root.followCurrent();
        }
        function onReviewChanged() {
            root.syncSelected();
        }
    }
    Connections {
        target: meetingSegments
        function onDataChanged() {
            root.syncSelected();
        }
        function onModelReset() {
            root.selectedIndex = 0;
            root.syncSelected();
        }
    }
    RowLayout {
        Layout.fillWidth: true
        EnumCombo {
            objectName: 'reviewLayoutChoice'
            Layout.fillWidth: true
            model: [
                {
                    value: 'compact',
                    label: 'Lista compatta'
                },
                {
                    value: 'columns',
                    label: 'Due colonne'
                },
                {
                    value: 'document',
                    label: 'Documento continuo'
                }
            ]
            selectedValue: root.mode
            onChosen: value => root.mode = value
        }
        NeuButton {
            compact: true
            text: root.following ? 'Pausa sincronizzazione' : 'Riprendi sincronizzazione'
            selected: root.following
            onClicked: {
                root.following = !root.following;
                root.followCurrent();
            }
        }
    }
    RowLayout {
        Layout.fillWidth: true
        Layout.preferredHeight: 570
        ListView {
            id: indexList
            visible: root.mode === 'columns'
            Layout.preferredWidth: Math.min(220, root.width * .32)
            Layout.fillHeight: true
            model: meetingSegments
            clip: true
            reuseItems: true
            spacing: 5
            ScrollBar.vertical: ScrollBar {
                policy: ScrollBar.AlwaysOn
            }
            onMovementStarted: root.following = false
            delegate: NeuButton {
                required property var record
                required property int index
                width: indexList.width - 16
                height: 83
                wrapText: true
                alignLeft: true
                selected: root.selectedIndex === index
                text: Theme.timestamp(record.start || 0) + ' · ' + record.speaker_name + '\n' + String(record.draft_text || '').slice(0, 48)
                onClicked: {
                    root.following = false;
                    root.selectedIndex = index;
                }
            }
        }
        ScrollView {
            visible: root.mode === 'columns'
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: availableWidth
            clip: true
            ScrollBar.vertical: ScrollBar {
                policy: ScrollBar.AsNeeded
            }
            ReviewSegment {
                width: parent.width - 16
                documentMode: true
                record: root.selectedRecord
                segmentIndex: root.selectedIndex
                onEditing: root.following = false
                onSeekRequested: seconds => root.seekRequested(seconds)
            }
        }
        ListView {
            id: review
            objectName: 'meetingReviewList'
            visible: root.mode !== 'columns'
            Layout.fillWidth: true
            Layout.fillHeight: true
            model: meetingSegments
            reuseItems: true
            cacheBuffer: 0
            clip: true
            spacing: root.mode === 'document' ? 2 : 8
            ScrollBar.vertical: ScrollBar {
                policy: ScrollBar.AlwaysOn
                width: 14
            }
            onMovementStarted: root.following = false
            WheelHandler {
                target: null
                onWheel: event => {
                    root.following = false;
                    event.accepted = false;
                }
            }
            delegate: Item {
                required property var record
                required property int index
                objectName: 'reviewSegment' + index
                width: review.width - 18
                height: segment.implicitHeight
                ReviewSegment {
                    id: segment
                    anchors.fill: parent
                    record: parent.record
                    segmentIndex: parent.index
                    documentMode: root.mode === 'document'
                    onEditing: root.following = false
                    onSeekRequested: seconds => root.seekRequested(seconds)
                }
            }
        }
    }
}
