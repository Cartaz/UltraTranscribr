import QtQuick
import QtQuick.Layouts

ColumnLayout {
    spacing: 18
    RowLayout {
        id: inputRow
        Layout.fillWidth: true
        spacing: 18
        Card {
            objectName: 'fileInputCard'
            Layout.fillWidth: true
            Layout.preferredWidth: (inputRow.width - 18) * .54
            Layout.preferredHeight: 324
            CardHead {
                kicker: 'MEDIA'
                title: 'Trascrivi un file'
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 7
                FieldLabel {
                    text: 'File audio o video'
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 9
                    NeuField {
                        Layout.fillWidth: true
                        readOnly: true
                        text: files.selection
                        placeholderText: 'Nessun file selezionato'
                    }
                    NeuButton {
                        text: 'Sfoglia multipli'
                        enabled: !meeting.busy && !live.activeCount
                        onClicked: files.choose()
                    }
                }
            }
            NeuToggle {
                id: song
                Layout.fillWidth: true
                text: 'Modalità musica'
                description: 'Preserva ripetizioni utili nei testi cantati.'
            }
            NeuToggle {
                id: isolate
                Layout.fillWidth: true
                enabled: song.checked
                text: 'Isola voce'
                description: 'Usa Demucs se installato; solo in modalità musica.'
            }
            RowLayout {
                NeuButton {
                    text: 'Accoda'
                    selected: true
                    enabled: !meeting.busy && !live.activeCount
                    onClicked: files.start(song.checked, isolate.checked)
                }
                NeuButton {
                    text: 'Ferma'
                    enabled: files.busy
                    onClicked: files.cancel()
                }
            }
        }
        Card {
            objectName: 'fileStatusCard'
            Layout.fillWidth: true
            Layout.preferredWidth: (inputRow.width - 18) * .46
            Layout.preferredHeight: 324
            CardHead {
                kicker: 'SESSIONE'
                title: 'Elaborazione file'
                Rectangle {
                    implicitWidth: 9
                    implicitHeight: 9
                    Layout.alignment: Qt.AlignTop
                    Layout.topMargin: 4
                    radius: 4.5
                    color: files.busy ? Theme.accent : Theme.muted
                }
            }
            Item {
                Layout.fillWidth: true
                implicitHeight: 63
                InsetSurface {
                    anchors.fill: parent
                }
                GridLayout {
                    anchors.fill: parent
                    anchors.margins: 13
                    anchors.topMargin: 3
                    anchors.bottomMargin: 3
                    columns: 2
                    columnSpacing: 16
                    rowSpacing: 0
                    uniformCellWidths: true
                    Metric {
                        Layout.fillWidth: true
                        label: 'Stato'
                        value: Theme.statusName(files.status)
                    }
                    Metric {
                        Layout.fillWidth: true
                        label: 'Modello'
                        value: Theme.modelName(settings.values.model_size)
                    }
                    Metric {
                        Layout.fillWidth: true
                        label: 'Lingua'
                        value: settings.values.language || 'auto'
                    }
                    Metric {
                        Layout.fillWidth: true
                        label: 'File'
                        value: files.selection || '—'
                    }
                }
            }
            NeuProgress {
                Layout.fillWidth: true
                value: files.progress
            }
            Help {
                text: 'Avanzamento: ' + Math.round(files.progress) + '%.'
            }
            Item {
                Layout.fillHeight: true
            }
        }
    }
    Card {
        objectName: 'fileQueueCard'
        Layout.fillWidth: true
        Layout.topMargin: 12
        Layout.preferredHeight: 168.796875 + (fileQueue.count ? Math.min(230, fileQueue.count * 80) - 46 : 0)
        CardHead {
            kicker: 'BATCH'
            title: 'Coda file'
            NeuButton {
                text: 'Pulisci completati'
                compact: true
                onClicked: files.clearFinished()
            }
            NeuButton {
                text: 'Annulla coda'
                compact: true
                enabled: files.busy
                onClicked: files.cancel()
            }
        }
        Help {
            Layout.fillWidth: true
            text: 'Seleziona più file oppure trascinali nella finestra. La coda usa un solo worker File alla volta e conserva la cronologia di ogni elemento.'
        }
        QueueList {
            Layout.fillWidth: true
            Layout.fillHeight: true
            queueModel: fileQueue
        }
    }
    Card {
        objectName: 'fileTranscriptCard'
        Layout.fillWidth: true
        Layout.fillHeight: true
        Layout.minimumHeight: 120
        CardHead {
            kicker: 'OUTPUT'
            title: 'Trascrizione file'
            NeuButton {
                text: 'Copia'
                compact: true
                onClicked: feedback.copy(files.text)
            }
            NeuButton {
                text: 'Pulisci'
                compact: true
                enabled: !files.busy
                onClicked: files.clearText()
            }
        }
        Transcript {
            Layout.fillWidth: true
            Layout.fillHeight: true
            text: files.text
        }
    }
}
