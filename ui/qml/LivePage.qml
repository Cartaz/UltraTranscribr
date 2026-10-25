import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: page
    spacing: 18
    RowLayout {
        id: inputRow
        Layout.fillWidth: true
        Layout.alignment: Qt.AlignTop
        spacing: 18
        Card {
            objectName: 'liveInputCard'
            Layout.fillWidth: true
            Layout.preferredWidth: (inputRow.width - 18) * .54
            Layout.preferredHeight: sources.source === 'microphone' ? 455 : 375.59375
            CardHead {
                kicker: 'INGRESSO'
                title: 'Sorgente audio'
                NeuButton {
                    text: 'Aggiorna sorgenti'
                    onClicked: sources.refresh()
                }
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 7
                FieldLabel {
                    text: 'Sorgente'
                }
                Item {
                    Layout.fillWidth: true
                    implicitHeight: 45
                    InsetSurface {
                        anchors.fill: parent
                    }
                    RowLayout {
                        anchors.fill: parent
                        anchors.margins: 5
                        spacing: 7
                        uniformCellSizes: true
                        NeuButton {
                            Layout.fillWidth: true
                            implicitHeight: 35
                            padding: 9
                            flat: true
                            text: 'Audio di sistema'
                            selected: sources.source === 'system'
                            onClicked: sources.setSource('system')
                        }
                        NeuButton {
                            Layout.fillWidth: true
                            implicitHeight: 35
                            padding: 9
                            flat: true
                            text: 'Applicazione'
                            selected: sources.source === 'application'
                            onClicked: sources.setSource('application')
                        }
                        NeuButton {
                            Layout.fillWidth: true
                            implicitHeight: 35
                            padding: 9
                            flat: true
                            text: 'Microfono'
                            selected: sources.source === 'microphone'
                            onClicked: sources.setSource('microphone')
                        }
                    }
                }
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 7
                FieldLabel {
                    text: sources.source === 'application' ? 'Stream applicazione' : 'Dispositivo'
                }
                NeuCombo {
                    objectName: 'liveDeviceCombo'
                    Layout.fillWidth: true
                    model: sources.source === 'application' ? playbackStreams : audioDevices
                    selectedValue: sources.selected
                    onChosen: value => sources.select(value)
                }
                Help {
                    Layout.fillWidth: true
                    text: sources.source === 'application' ? 'Seleziona uno stream PipeWire/PulseAudio. Verrà isolato e ripristinato automaticamente al termine.' : "Automatico usa il monitor dell'uscita audio predefinita o il microfono predefinito."
                }
            }
            Item {
                Layout.fillWidth: true
                implicitHeight: 47
                InsetSurface {
                    anchors.fill: parent
                }
                RowLayout {
                    anchors.fill: parent
                    anchors.margins: 11
                    spacing: 9
                    Rectangle {
                        implicitWidth: 9
                        implicitHeight: 9
                        radius: 4.5
                        color: sources.health.status === 'playing' || sources.health.status === 'available' ? Theme.accent : Theme.muted
                    }
                    Column {
                        Layout.fillWidth: true
                        spacing: 2
                        Text {
                            textFormat: Text.PlainText
                            text: sources.health.label || 'Verifica sorgente'
                            color: Theme.primary
                            font.family: Theme.font
                            font.pixelSize: 12
                            font.bold: true
                        }
                        Help {
                            width: parent.width
                            text: sources.health.detail || ''
                            maximumLineCount: 1
                            elide: Text.ElideRight
                        }
                    }
                }
            }
            NeuToggle {
                id: recordToggle
                Layout.fillWidth: true
                visible: sources.source === 'microphone'
                text: 'Salva registrazione'
                description: 'Solo Microfono. Default OFF; la copia FLAC viene associata alla sessione Live.'
            }
            NeuButton {
                text: 'Aggiungi sessione'
                selected: true
                enabled: !files.busy && !meeting.busy && (sources.source !== 'application' || !!sources.selected)
                onClicked: live.start(recordToggle.checked)
            }
        }
        Card {
            objectName: 'liveStatusCard'
            Layout.fillWidth: true
            Layout.preferredWidth: (inputRow.width - 18) * .46
            Layout.preferredHeight: sources.source === 'microphone' ? 455 : 375.59375
            CardHead {
                kicker: 'SESSIONE'
                title: 'Stato live'
                Rectangle {
                    implicitWidth: 9
                    implicitHeight: 9
                    Layout.alignment: Qt.AlignTop
                    Layout.topMargin: 4
                    radius: 4.5
                    color: live.activeCount ? Theme.accent : Theme.muted
                }
            }
            Item {
                Layout.fillWidth: true
                implicitHeight: 91
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
                        value: live.activeCount ? 'In esecuzione' : 'Idle'
                    }
                    Metric {
                        Layout.fillWidth: true
                        label: 'Sorgente'
                        value: Theme.sourceName(sources.source)
                    }
                    Metric {
                        Layout.fillWidth: true
                        label: 'Ingresso'
                        value: sources.selected || 'Automatico'
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
                }
            }
            Item {
                Layout.fillHeight: true
            }
        }
    }
    Card {
        objectName: 'liveSessionsCard'
        Layout.fillWidth: true
        Layout.fillHeight: true
        CardHead {
            kicker: 'SESSIONI LIVE'
            title: 'Trascrizioni indipendenti'
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
        Help {
            text: live.activeCount + ' sessioni attive'
            Layout.topMargin: -13
            Layout.bottomMargin: 13
        }
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            EmptyState {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 4
                visible: liveSessions.count === 0
                centered: true
                text: 'Nessuna sessione Live. Scegli una sorgente e premi “Aggiungi sessione”.'
            }
            ListView {
                id: sessions
                anchors.fill: parent
                anchors.margins: 4
                visible: liveSessions.count > 0
                model: liveGroups
                spacing: 16
                clip: true
                reuseItems: true
                cacheBuffer: 0
                ScrollBar.vertical: ScrollBar {}
                delegate: RowLayout {
                    id: pair
                    required property var record
                    width: sessions.width - 10
                    height: 335
                    spacing: 16
                    LiveSessionCard {
                        Layout.preferredWidth: (pair.width - 16) / 2
                        Layout.fillHeight: true
                        record: pair.record.left
                    }
                    Item {
                        Layout.preferredWidth: (pair.width - 16) / 2
                        Layout.fillHeight: true
                        LiveSessionCard {
                            anchors.fill: parent
                            record: pair.record.right
                            visible: !!record.id
                        }
                    }
                }
            }
        }
    }
}
