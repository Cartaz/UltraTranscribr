import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ScrollView {
    id: page
    clip: true
    contentWidth: availableWidth
    contentHeight: pageContent.implicitHeight + 4
    ColumnLayout {
        id: pageContent
        width: page.availableWidth - 19
        spacing: 18
        GridLayout {
            id: topPanels
            objectName: 'fileTopPanels'
            Layout.fillWidth: true
            Layout.fillHeight: false
            columns: page.availableWidth >= 1050 ? 2 : 1
            uniformCellWidths: true
            columnSpacing: 18
            rowSpacing: 18
            Card {
                objectName: 'fileInputCard'
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumWidth: 0
                Layout.preferredWidth: 1
                Layout.preferredHeight: 290
                CardHead {

                    title: 'Selezione file'
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
                            enabled: !settings.dirty && !settings.saving && !meeting.busy && !live.activeCount
                            onClicked: files.choose()
                        }
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    FieldLabel {
                        text: 'Lingua dei nuovi file'
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        LanguageCombo {
                            objectName: 'fileLanguageField'
                            Layout.fillWidth: true
                            Layout.minimumWidth: 45
                            selectedValue: files.language

                            onChosen: value => files.editLanguage(value)
                        }
                        NeuButton {
                            text: 'Predefinita'
                            compact: true
                            onClicked: files.resetLanguage()
                        }
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    NeuToggle {
                        id: song
                        Layout.fillWidth: true
                        text: 'Modalità musica'
                    }
                    NeuToggle {
                        id: isolate
                        Layout.fillWidth: true
                        enabled: song.checked
                        text: 'Isola voce'
                    }
                }
                RowLayout {
                    NeuButton {
                        text: 'Accoda'
                        selected: true
                        enabled: !settings.dirty && !settings.saving && !meeting.busy && !live.activeCount
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
                objectName: 'fileQueueCard'
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumWidth: 0
                Layout.preferredWidth: 1
                Layout.preferredHeight: 180 + (fileQueue.count ? Math.min(230, fileQueue.count * 80) - 46 : 0)
                CardHead {

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
                    text: Theme.statusName(files.status) + ' · ' + files.queueSummary
                }
                RowLayout {
                    Layout.fillWidth: true
                    FieldLabel {
                        text: 'File corrente'
                    }
                    NeuProgress {
                        Layout.fillWidth: true
                        value: files.progress
                    }
                    Help {
                        text: Math.round(files.progress) + '%'
                    }
                }
                QueueList {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    queueModel: fileQueue
                }
            }
        }
        Card {
            objectName: 'fileTranscriptCard'
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 180
            Layout.preferredHeight: Math.max(220, page.availableHeight - topPanels.implicitHeight - 22)
            CardHead {

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
            NeuField {
                Layout.fillWidth: true
                visible: files.hasSession
                text: files.title
                placeholderText: 'Titolo della trascrizione'
                Accessible.name: 'Titolo della trascrizione'
                maximumLength: 120
                onEditingFinished: files.rename(text)
            }
            Transcript {
                Layout.fillWidth: true
                Layout.fillHeight: true
                text: files.text
            }
        }
    }
}
