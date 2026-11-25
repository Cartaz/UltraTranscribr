import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: page
    spacing: 12
    Card {
        objectName: 'liveInputCard'
        Layout.fillWidth: true
        Layout.preferredHeight: Math.max(224, implicitHeight)
        CardHead {
            title: 'Sorgente audio'
            NeuButton {
                text: 'Aggiorna sorgenti'
                compact: true
                onClicked: sources.refresh()
            }
        }
        RowLayout {
            Layout.fillWidth: true
            NeuButton {
                text: 'Audio di sistema'
                selected: sources.source === 'system'
                onClicked: sources.setSource('system')
            }
            NeuButton {
                text: 'Applicazione'
                selected: sources.source === 'application'
                onClicked: sources.setSource('application')
            }
            NeuButton {
                text: 'Microfono'
                selected: sources.source === 'microphone'
                onClicked: sources.setSource('microphone')
            }
        }
        RowLayout {
            Layout.fillWidth: true
            ColumnLayout {
                Layout.fillWidth: true
                FieldLabel {
                    text: sources.source === 'application' ? 'Applicazione' : 'Dispositivo'
                }
                NeuCombo {
                    objectName: 'liveDeviceCombo'
                    Layout.fillWidth: true
                    model: sources.source === 'application' ? playbackStreams : audioDevices
                    selectedValue: sources.selected
                    onChosen: value => sources.select(value)
                    ToolTip.visible: hovered
                    ToolTip.text: 'Automatico usa il dispositivo predefinito. Gli stream applicazione vengono isolati per la durata della registrazione.'
                }
            }
            ColumnLayout {
                Layout.preferredWidth: 230
                FieldLabel {
                    text: 'Lingua'
                }
                LanguageCombo {
                    objectName: 'liveLanguageField'
                    Layout.fillWidth: true
                    selectedValue: live.language
                    onChosen: value => live.editLanguage(value)
                }
            }
            NeuButton {
                text: '↺'
                compact: true
                onClicked: live.resetLanguage()
                ToolTip.text: 'Usa la lingua predefinita'
                ToolTip.visible: hovered
            }
        }
        RowLayout {
            Layout.fillWidth: true
            NeuToggle {
                id: recordToggle
                objectName: 'liveRecordToggle'
                visible: sources.source === 'microphone'
                Layout.preferredWidth: 245
                checked: live.recordAudio
                onToggled: live.editRecording(checked)
                text: 'Salva registrazione'
            }
            Help {
                Layout.fillWidth: true
                visible: sources.health.available === false || ['error', 'unavailable', 'disconnected', 'missing'].indexOf(sources.health.status) >= 0
                text: sources.health.detail || sources.health.label || ''
                color: Theme.accent
            }
            Item {
                Layout.fillWidth: true
            }
            NeuButton {
                text: 'Inizia registrazione'
                selected: true
                enabled: !settings.dirty && !settings.saving && !files.busy && !meeting.busy && (sources.source !== 'application' || !!sources.selected)
                onClicked: live.start(recordToggle.checked)
            }
        }
    }
    Card {
        objectName: 'liveSessionsCard'
        Layout.fillWidth: true
        Layout.fillHeight: true
        CardHead {
            title: 'Trascrizioni in corso'
            NeuButton {
                text: 'Completa tutte'
                compact: true
                enabled: live.activeCount > 0
                onClicked: live.stopAll(true)
            }
            NeuButton {
                text: 'Ferma tutte'
                compact: true
                enabled: live.activeCount > 0
                onClicked: live.stopAll(false)
            }
        }
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            EmptyState {
                anchors.fill: parent
                visible: liveSessions.count === 0
                centered: true
                text: 'Scegli una sorgente e premi “Inizia registrazione”.'
            }
            GridView {
                id: sessions
                anchors.fill: parent
                visible: liveSessions.count > 0
                model: liveSessions
                clip: true
                cellWidth: width > 1050 ? width / 2 : width
                cellHeight: Math.max(320, height)
                ScrollBar.vertical: ScrollBar {
                    policy: ScrollBar.AsNeeded
                }
                delegate: LiveSessionCard {
                    width: sessions.cellWidth - 12
                    height: sessions.cellHeight - 8
                }
            }
        }
    }
}
