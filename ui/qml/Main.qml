import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: shell
    objectName: 'mainWindow'
    width: 1200
    height: 800
    minimumWidth: 1200
    minimumHeight: 800
    title: 'UltraTranscribr'
    color: Theme.surface
    property string view: 'live'
    property var confirmationAction: null
    function confirm(message, action) {
        confirmationAction = action;
        confirmText.text = message;
        confirmation.open();
    }
    onViewChanged: {
        if (view === 'live' || view === 'meeting')
            sources.refresh();
        if (view === 'history' || view === 'meeting')
            archive.refresh();
        if (view === 'settings')
            settings.refreshModels();
        if (view === 'logs')
            runtime.refreshLog();
    }
    Item {
        anchors.fill: parent
        anchors.margins: 18
        Item {
            id: sidebar
            objectName: 'sidebar'
            width: 210
            height: parent.height
            RaisedSurface {
                anchors.fill: parent
                radius: Theme.radiusXL
            }
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 14
                anchors.topMargin: 18
                anchors.bottomMargin: 18
                spacing: 20
                RowLayout {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 44
                    Layout.leftMargin: 5
                    Layout.rightMargin: 5
                    spacing: 11
                    Item {
                        Layout.preferredWidth: 34
                        Layout.preferredHeight: 40
                        RaisedSurface {
                            anchors.fill: parent
                            radius: 13
                            soft: true
                        }
                        Canvas {
                            anchors.centerIn: parent
                            width: 23
                            height: 23
                            onPaint: {
                                let c = getContext('2d');
                                c.strokeStyle = '#ff6600';
                                c.lineWidth = 1.7;
                                c.lineCap = 'round';
                                c.beginPath();
                                c.moveTo(4, 12);
                                c.lineTo(6, 12);
                                c.moveTo(8, 7);
                                c.lineTo(8, 17);
                                c.moveTo(11, 4);
                                c.lineTo(11, 20);
                                c.moveTo(14, 8);
                                c.lineTo(14, 16);
                                c.moveTo(17, 10);
                                c.lineTo(17, 14);
                                c.moveTo(20, 12);
                                c.lineTo(21, 12);
                                c.stroke();
                            }
                        }
                    }
                    Column {
                        Layout.minimumWidth: 0
                        Layout.fillWidth: true
                        spacing: 2
                        Text {
                            textFormat: Text.PlainText
                            width: 128
                            text: 'UltraTranscribr'
                            color: Theme.primary
                            font.family: Theme.font
                            font.pixelSize: 15
                            font.bold: true
                        }
                        Help {
                            text: 'v' + appVersion
                        }
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 9
                    NeuButton {
                        objectName: 'navLive'
                        Layout.fillWidth: true
                        text: 'Live'
                        alignLeft: true
                        selected: shell.view === 'live'
                        onClicked: shell.view = 'live'
                    }
                    NeuButton {
                        objectName: 'navFile'
                        Layout.fillWidth: true
                        text: 'File'
                        alignLeft: true
                        selected: shell.view === 'file'
                        onClicked: shell.view = 'file'
                    }
                    NeuButton {
                        objectName: 'navMeeting'
                        Layout.fillWidth: true
                        text: 'Riunione'
                        alignLeft: true
                        selected: shell.view === 'meeting'
                        onClicked: shell.view = 'meeting'
                    }
                    NeuButton {
                        objectName: 'navHistory'
                        Layout.fillWidth: true
                        text: 'Cronologia'
                        alignLeft: true
                        selected: shell.view === 'history'
                        onClicked: shell.view = 'history'
                    }
                    NeuButton {
                        objectName: 'navSettings'
                        Layout.fillWidth: true
                        text: 'Impostazioni'
                        alignLeft: true
                        selected: shell.view === 'settings'
                        onClicked: shell.view = 'settings'
                    }
                    NeuButton {
                        objectName: 'navLogs'
                        Layout.fillWidth: true
                        text: 'Log'
                        alignLeft: true
                        selected: shell.view === 'logs'
                        onClicked: shell.view = 'logs'
                    }
                }
                Item {
                    Layout.fillHeight: true
                }
                Item {
                    Layout.fillWidth: true
                    implicitHeight: 56
                    InsetSurface {
                        anchors.fill: parent
                    }
                    RowLayout {
                        anchors.fill: parent
                        anchors.margins: 12
                        spacing: 9
                        Rectangle {
                            implicitWidth: 9
                            implicitHeight: 9
                            radius: 4.5
                            color: runtime.status === 'Standby' ? Theme.muted : Theme.accent
                        }
                        Column {
                            spacing: 2
                            Help {
                                text: 'Backend'
                            }
                            Text {
                                textFormat: Text.PlainText
                                text: runtime.status
                                color: Theme.primary
                                font.family: Theme.font
                                font.pixelSize: 12
                                font.bold: true
                            }
                        }
                    }
                }
            }
        }
        ColumnLayout {
            anchors.left: sidebar.right
            anchors.leftMargin: 24
            anchors.right: parent.right
            anchors.rightMargin: 2
            anchors.top: parent.top
            anchors.topMargin: 2
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 2
            spacing: 0
            Item {
                objectName: 'topbar'
                Layout.fillWidth: true
                implicitHeight: 31
                Text {
                    textFormat: Text.PlainText
                    x: 4
                    y: 5
                    text: ({
                            live: 'TRASCRIZIONE LIVE',
                            file: 'TRASCRIZIONE FILE',
                            meeting: 'RIUNIONE',
                            history: 'CRONOLOGIA',
                            settings: 'IMPOSTAZIONI',
                            logs: 'LOG E DIAGNOSTICA'
                        })[shell.view]
                    color: Theme.accent
                    font.family: Theme.font
                    font.pixelSize: 11
                    font.weight: Font.ExtraBold
                    font.letterSpacing: 1.98
                }
            }
            StackLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                currentIndex: ({
                        live: 0,
                        file: 1,
                        meeting: 2,
                        history: 3,
                        settings: 4,
                        logs: 5
                    })[shell.view]
                LivePage {
                    objectName: 'livePage'
                }
                FilePage {
                    objectName: 'filePage'
                }
                MeetingPage {
                    objectName: 'meetingPage'
                }
                HistoryPage {
                    objectName: 'historyPage'
                }
                SettingsPage {
                    objectName: 'settingsPage'
                }
                LogsPage {
                    objectName: 'logsPage'
                }
            }
        }
    }
    Item {
        visible: !!feedback.message
        x: shell.width - width - 24
        y: 58
        width: Math.min(480, shell.width - 48)
        height: noticeText.implicitHeight + 22
        z: 20
        RaisedSurface {
            anchors.fill: parent
            radius: 16
            selected: true
        }
        RowLayout {
            anchors.fill: parent
            anchors.margins: 13
            Text {
                id: noticeText
                textFormat: Text.PlainText
                Layout.fillWidth: true
                text: feedback.message
                color: Theme.primary
                wrapMode: Text.WordWrap
                font.family: Theme.font
                font.pixelSize: 14
            }
            NeuButton {
                text: '×'
                compact: true
                onClicked: feedback.dismiss()
            }
        }
    }
    Popup {
        id: confirmation
        anchors.centerIn: parent
        modal: true
        padding: 20
        width: Math.min(480, shell.width - 40)
        closePolicy: Popup.CloseOnEscape
        background: RaisedSurface {
            radius: 16
        }
        ColumnLayout {
            width: parent.width
            spacing: 16
            Text {
                textFormat: Text.PlainText
                text: 'Conferma'
                color: Theme.primary
                font.family: Theme.font
                font.pixelSize: 18
                font.bold: true
            }
            Text {
                id: confirmText
                textFormat: Text.PlainText
                Layout.fillWidth: true
                color: Theme.primary
                font.family: Theme.font
                font.pixelSize: 14
                wrapMode: Text.WordWrap
            }
            RowLayout {
                Layout.alignment: Qt.AlignRight
                NeuButton {
                    text: 'Annulla'
                    onClicked: {
                        shell.confirmationAction = null;
                        confirmation.close();
                    }
                }
                NeuButton {
                    text: 'Conferma'
                    selected: true
                    onClicked: {
                        let action = shell.confirmationAction;
                        shell.confirmationAction = null;
                        confirmation.close();
                        if (action)
                            action();
                    }
                }
            }
        }
        onClosed: shell.confirmationAction = null
    }
    DropArea {
        anchors.fill: parent
        enabled: shell.view !== 'meeting'
        onDropped: drop => {
            if (drop.hasUrls) {
                files.dropFiles(drop.urls);
                shell.view = 'file';
                drop.acceptProposedAction();
            }
        }
    }
    Shortcut {
        sequence: 'Ctrl+1'
        onActivated: shell.view = 'live'
    }
    Shortcut {
        sequence: 'Ctrl+2'
        onActivated: shell.view = 'file'
    }
    Shortcut {
        sequence: 'Ctrl+3'
        onActivated: shell.view = 'meeting'
    }
}
