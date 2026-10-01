import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ScrollView {
    id: page
    property bool advanced: false
    clip: true
    contentWidth: availableWidth
    contentHeight: pageContent.implicitHeight + 4
    ColumnLayout {
        id: pageContent
        width: page.availableWidth - 19
        x: 2
        y: 4
        spacing: 20
        Item {
            Layout.preferredWidth: 430
            Layout.maximumWidth: 430
            Layout.alignment: Qt.AlignLeft
            implicitHeight: 42
            InsetSurface {
                anchors.fill: parent
            }
            RowLayout {
                anchors.fill: parent
                anchors.margins: 4
                spacing: 7
                uniformCellSizes: true
                NeuButton {
                    text: 'Normali'
                    Layout.fillWidth: true
                    implicitHeight: 35
                    flat: true
                    selected: !page.advanced
                    onClicked: page.advanced = false
                }
                NeuButton {
                    text: 'Avanzate'
                    Layout.fillWidth: true
                    implicitHeight: 35
                    flat: true
                    selected: page.advanced
                    onClicked: page.advanced = true
                }
            }
        }
        GridLayout {
            Layout.fillWidth: true
            columns: 2
            columnSpacing: 18
            rowSpacing: 36
            visible: !page.advanced
            Card {
                objectName: 'recognitionCard'
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.preferredWidth: 1
                Layout.row: 0
                Layout.column: 0
                Layout.preferredHeight: 296.5
                CardHead {
                    kicker: 'TRASCRIZIONE'
                    title: 'Riconoscimento'
                    NeuButton {
                        text: 'Ripristina'
                        compact: true
                        enabled: !runtime.busy && !settings.saving
                        onClicked: settings.reset('recognition')
                    }
                }
                GridLayout {
                    Layout.fillWidth: true
                    columns: 2
                    columnSpacing: 13
                    rowSpacing: 13
                    SettingField {
                        keyName: 'model_size'
                        label: 'Modello'
                        options: [
                            {
                                value: 'large-v3',
                                label: 'Large v3'
                            },
                            {
                                value: 'large-v3-turbo',
                                label: 'Large v3 Turbo'
                            },
                            {
                                value: 'medium',
                                label: 'Medium'
                            }
                        ]
                    }
                    SettingField {
                        keyName: 'language'
                        label: 'Lingua'
                    }
                    SettingField {
                        Layout.columnSpan: 2
                        keyName: 'audio_source'
                        label: 'Sorgente predefinita'
                        options: [
                            {
                                value: 'system',
                                label: 'Audio di sistema'
                            },
                            {
                                value: 'application',
                                label: 'Applicazione'
                            },
                            {
                                value: 'microphone',
                                label: 'Microfono'
                            }
                        ]
                    }
                }
                NeuToggle {
                    Layout.fillWidth: true
                    text: 'VAD'
                    description: 'Voice activity detection del server.'
                    checked: !!settings.values.vad_filter
                    onToggled: settings.edit('vad_filter', checked)
                }
                Item {
                    Layout.fillHeight: true
                }
            }
            Card {
                objectName: 'modelManagerCard'
                Layout.fillWidth: true
                Layout.preferredHeight: 358.796875
                Layout.columnSpan: 2
                Layout.row: 1
                Layout.column: 0
                CardHead {
                    kicker: 'MODELLI'
                    title: 'Gestione modelli Whisper'
                    NeuButton {
                        text: 'Aggiorna'
                        compact: true
                        onClicked: settings.refreshModels()
                    }
                }
                Help {
                    Layout.fillWidth: true
                    text: 'Scarica in anticipo i modelli disponibili o libera spazio. I download interrotti vengono ripresi dal file parziale quando possibile.'
                }
                ListView {
                    id: modelList
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    model: whisperModels
                    spacing: 10
                    reuseItems: true
                    cacheBuffer: 0
                    clip: true
                    delegate: Item {
                        required property var record
                        width: modelList.width - 5
                        height: 74
                        InsetSurface {
                            anchors.fill: parent
                        }
                        RowLayout {
                            anchors.fill: parent
                            anchors.margins: 13
                            spacing: 14
                            Column {
                                Layout.fillWidth: true
                                spacing: 4
                                Text {
                                    textFormat: Text.PlainText
                                    text: Theme.modelName(record.model)
                                    color: Theme.primary
                                    font.family: Theme.font
                                    font.pixelSize: 14
                                    font.bold: true
                                }
                                Help {
                                    text: record.installed ? (Number(record.size_bytes) / 1048576).toFixed(1) + ' MiB' : 'Minimo atteso: ' + (Number(record.min_bytes) / 1048576).toFixed(1) + ' MiB'
                                }
                            }
                            ColumnLayout {
                                Layout.preferredWidth: Math.min(460, modelList.width * .54)
                                RowLayout {
                                    Rectangle {
                                        implicitWidth: 9
                                        implicitHeight: 9
                                        radius: 4.5
                                        color: record.installed ? Theme.accent : Theme.muted
                                    }
                                    Help {
                                        text: settings.modelBusy === record.model ? 'Operazione in corso' : record.installed ? 'Installato' : 'Non installato'
                                        color: Theme.secondary
                                        font.bold: true
                                    }
                                }
                                NeuProgress {
                                    Layout.fillWidth: true
                                    value: record.progress || 0
                                }
                                Help {
                                    text: record.installed ? "Pronto all'uso" : 'Non scaricato'
                                    font.pixelSize: 11
                                }
                            }
                            NeuButton {
                                compact: true
                                text: record.installed ? 'Elimina' : record.partial_bytes ? 'Riprendi' : 'Scarica'
                                selected: !record.installed
                                enabled: !runtime.busy && !settings.modelBusy
                                onClicked: {
                                    let id = record.model;
                                    if (record.installed)
                                        shell.confirm('Eliminare ' + Theme.modelName(id) + ' dal disco?', () => settings.manageModel(id, true));
                                    else
                                        settings.manageModel(id, false);
                                }
                            }
                        }
                    }
                }
            }
            Card {
                objectName: 'retentionCard'
                Layout.alignment: Qt.AlignTop
                Layout.row: 2
                Layout.column: 0
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                Layout.preferredHeight: 274.59
                CardHead {
                    kicker: 'CRONOLOGIA'
                    title: 'Conservazione'
                    NeuButton {
                        text: 'Ripristina'
                        compact: true
                        enabled: !runtime.busy && !settings.saving
                        onClicked: settings.reset('history')
                    }
                }
                SettingField {
                    keyName: 'history_retention_days'
                    label: 'Conserva per giorni'
                    numeric: true
                }
                SettingField {
                    keyName: 'meeting_audio_retention_days'
                    label: 'Audio riunioni (giorni)'
                    numeric: true
                }
                Help {
                    Layout.fillWidth: true
                    text: 'Default 90 giorni. Imposta 0 per conservare le trascrizioni senza scadenza automatica. L’audio delle riunioni ha una conservazione indipendente.'
                }
            }
            Card {
                objectName: 'dictationSettingsCard'
                Layout.row: 2
                Layout.column: 1
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                Layout.preferredHeight: 329.75
                CardHead {
                    kicker: 'DETTATURA'
                    title: 'Inserimento globale'
                    NeuButton {
                        text: 'Ripristina'
                        compact: true
                        enabled: !runtime.busy && !settings.saving
                        onClicked: settings.reset('dictation')
                    }
                }
                SettingField {
                    keyName: 'dictation_activation_mode'
                    label: 'Attivazione'
                    options: [
                        {
                            value: 'push_to_talk',
                            label: 'Push-to-talk'
                        },
                        {
                            value: 'toggle',
                            label: 'Toggle'
                        }
                    ]
                }
                SettingField {
                    keyName: 'dictation_insertion_mode'
                    label: 'Inserimento'
                    options: [
                        {
                            value: 'live',
                            label: 'Live progressivo'
                        },
                        {
                            value: 'final',
                            label: 'Solo testo finale'
                        }
                    ]
                }
                Help {
                    Layout.fillWidth: true
                    text: 'Usa la scorciatoia globale per dettare nell’applicazione attiva. Su Wayland autorizza i portali di KDE per scorciatoie e inserimento del testo.'
                }
                Item {
                    Layout.fillHeight: true
                }
            }
        }
        GridLayout {
            Layout.fillWidth: true
            columns: 2
            columnSpacing: 18
            rowSpacing: 36
            visible: page.advanced
            Card {
                objectName: 'tuningCard'
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                Layout.preferredHeight: 228
                Layout.alignment: Qt.AlignTop
                CardHead {
                    kicker: 'TRASCRIZIONE'
                    title: 'Regolazioni avanzate'
                    NeuButton {
                        text: 'Ripristina'
                        compact: true
                        enabled: !runtime.busy && !settings.saving
                        onClicked: settings.reset('tuning')
                    }
                }
                GridLayout {
                    Layout.fillWidth: true
                    columns: 2
                    columnSpacing: 13
                    rowSpacing: 13
                    SettingField {
                        keyName: 'beam_size'
                        label: 'Beam size'
                        numeric: true
                    }
                    SettingField {
                        keyName: 'vad_min_silence_ms'
                        label: 'Silenzio VAD (ms)'
                        numeric: true
                    }
                    SettingField {
                        keyName: 'buffer_warn_threshold'
                        label: 'Soglia buffer'
                        numeric: true
                    }
                }
                Item {
                    Layout.fillHeight: true
                }
            }
            Card {
                objectName: 'audioSettingsCard'
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                Layout.preferredHeight: 300
                CardHead {
                    kicker: 'AUDIO'
                    title: 'Acquisizione avanzata'
                    NeuButton {
                        text: 'Ripristina'
                        compact: true
                        enabled: !runtime.busy && !settings.saving
                        onClicked: settings.reset('audio')
                    }
                }
                GridLayout {
                    Layout.fillWidth: true
                    columns: 2
                    columnSpacing: 13
                    rowSpacing: 13
                    SettingField {
                        keyName: 'chunk_ms'
                        label: 'Chunk (ms)'
                        numeric: true
                    }
                    SettingField {
                        keyName: 'channels'
                        label: 'Canali'
                        options: [
                            {
                                value: '1',
                                label: 'Mono'
                            },
                            {
                                value: '2',
                                label: 'Stereo'
                            }
                        ]
                    }
                    SettingField {
                        Layout.columnSpan: 2
                        keyName: 'sink_name'
                        label: 'Sink/dispositivo forzato'
                        hint: 'Vuoto = automatico'
                    }
                    SettingField {
                        Layout.columnSpan: 2
                        keyName: 'sink_search_keyword'
                        label: 'Filtro microfono (opzionale)'
                        hint: 'Vuoto = microfono predefinito'
                    }
                }
            }
            Card {
                objectName: 'backendCard'
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                Layout.preferredHeight: 462.59
                CardHead {
                    kicker: 'BACKEND'
                    title: 'SYCL'
                    NeuButton {
                        text: 'Ripristina'
                        compact: true
                        enabled: !runtime.busy && !settings.saving
                        onClicked: settings.reset('backend')
                    }
                }
                GridLayout {
                    Layout.fillWidth: true
                    columns: 2
                    columnSpacing: 13
                    rowSpacing: 13
                    SettingField {
                        keyName: 'server_port'
                        label: 'Porta server'
                        numeric: true
                    }
                    SettingField {
                        keyName: 'gpu_layers'
                        label: 'GPU layers'
                        numeric: true
                    }
                    SettingField {
                        keyName: 'compute_type'
                        label: 'Compute type'
                    }
                    SettingField {
                        keyName: 'device'
                        label: 'Device'
                        locked: true
                        fixedValue: 'sycl'
                    }
                    SettingField {
                        keyName: 'sample_rate'
                        label: 'Sample rate'
                        locked: true
                        fixedValue: '16000 Hz'
                    }
                    SettingField {
                        keyName: 'dtype'
                        label: 'Formato'
                        locked: true
                        fixedValue: 'float32'
                    }
                    SettingField {
                        keyName: 'backend_instances'
                        label: 'Istanze backend'
                        numeric: true
                    }
                }
                NeuToggle {
                    Layout.fillWidth: true
                    text: 'Precarica modello'
                    description: 'Avvia il modello installato selezionato all’apertura.'
                    checked: !!settings.values.preload_model
                    onToggled: settings.edit('preload_model', checked)
                }
                Help {
                    Layout.fillWidth: true
                    text: "I parametri di avvio di whisper-server vengono applicati integralmente al successivo avvio dell'app."
                }
            }
            Card {
                objectName: 'geometryCard'
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                Layout.preferredHeight: 186.17
                Layout.alignment: Qt.AlignTop
                CardHead {
                    kicker: 'FINESTRA'
                    title: 'Geometria automatica'
                }
                EmptyState {
                    Layout.fillWidth: true
                    implicitHeight: 97
                    text: 'Salvataggio automatico attivo\nUltraTranscribr memorizza posizione e dimensioni e rispetta sempre il minimo 1200 × 800.'
                }
            }
        }
        Card {
            objectName: "saveSettingsCard"
            Layout.fillWidth: true
            Layout.topMargin: -2
            CardHead {
                kicker: 'SALVATAGGIO'
                title: 'Applica configurazione'
                NeuButton {
                    text: 'Salva impostazioni'
                    selected: true
                    enabled: !runtime.busy && !settings.saving
                    onClicked: settings.save()
                }
            }
            Help {
                Layout.fillWidth: true
                text: 'I valori vengono validati dal modello Settings Python. I reset agiscono solo sulla sezione scelta.'
            }
        }
    }
}
