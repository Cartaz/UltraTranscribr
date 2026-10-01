import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
ScrollView {
    id: page
    clip: true; contentWidth: availableWidth
    ColumnLayout { width: page.availableWidth-19; x: 2; y: 2; spacing: 18
        RowLayout { Layout.fillWidth: true; spacing: 18; Layout.alignment: Qt.AlignTop
            Card { objectName: 'historyListCard'; Layout.fillWidth: true; Layout.preferredWidth: 320.75; Layout.horizontalStretchFactor: 36; Layout.minimumWidth: 320; Layout.preferredHeight: Math.max(435,historyModel.count ? Math.min(448,historyModel.count*94)+145 : 435); Layout.alignment: Qt.AlignTop
                RowLayout { Layout.fillWidth: true; Layout.preferredHeight: 80; spacing: 12
                    Column { Layout.fillWidth: true; Layout.alignment: Qt.AlignTop; spacing: 4; Text { text: 'AUTOSAVE'; color: Theme.accent; font.family: Theme.font; font.pixelSize: 10; font.bold: true; font.letterSpacing: 1.8 } Text { width: parent.width; text: 'Trascrizioni recenti'; wrapMode: Text.WordWrap; color: Theme.primary; font.family: Theme.font; font.pixelSize: 18; font.bold: true } }
                    NeuField { Layout.preferredWidth: 138; Layout.alignment: Qt.AlignTop; placeholderText: 'Cerca testo o sorgente…'; onTextEdited: archive.search(text) }
                }
                EmptyState { Layout.fillWidth: true; visible: historyModel.count===0; text: 'Nessuna trascrizione salvata.' }
                ListView { id: list; Layout.fillWidth: true; Layout.preferredHeight: Math.min(448,historyModel.count*94); visible: historyModel.count>0; model: historyModel; reuseItems: true; spacing: 9; clip: true; cacheBuffer: 0; ScrollBar.vertical: ScrollBar {}
                    delegate: Item { required property var record; width: list.width-5; height: 85
                        NeuButton { anchors.fill: parent; selected: archive.selected.id===record.id; onClicked: archive.select(record.id) }
                        Column { anchors.fill: parent; anchors.margins: 13; spacing: 5; Text { width: parent.width; text: record.name || record.source_path || record.id; color: Theme.primary; font.family: Theme.font; font.pixelSize: 14; font.bold: true; elide: Text.ElideRight } Help { text: Theme.statusName(record.status)+' · '+(record.language || 'auto') } Help { width: parent.width; text: record.started_at || ''; maximumLineCount: 1; elide: Text.ElideRight } }
                    }
                }
                Item { Layout.fillHeight: true }
            }
            Card { objectName: 'historyDetailCard'; Layout.fillWidth: true; Layout.preferredWidth: 570.25; Layout.horizontalStretchFactor: 64; Layout.minimumWidth: 0; Layout.preferredHeight: archive.selected.id ? 620 : 435; Layout.alignment: Qt.AlignTop
                RowLayout { Layout.fillWidth: true; Layout.preferredHeight: 115; spacing: 15
                    Column { Layout.preferredWidth: 133; Layout.alignment: Qt.AlignTop; spacing: 4; Text { text: 'SESSIONE'; color: Theme.accent; font.family: Theme.font; font.pixelSize: 10; font.bold: true; font.letterSpacing: 1.8 } Text { width: 133; text: archive.selected.name || (archive.selected.id ? 'Trascrizione' : 'Seleziona una trascrizione'); wrapMode: Text.WordWrap; color: Theme.primary; font.family: Theme.font; font.pixelSize: 18; font.bold: true } }
                    ColumnLayout { Layout.fillWidth: true; Layout.alignment: Qt.AlignTop; spacing: 9
                        NeuField { id: sessionName; Layout.fillWidth: true; placeholderText: 'Nome sessione'; text: archive.selected.name || ''; maximumLength: 120; enabled: !!archive.selected.id }
                        Flow { Layout.fillWidth: true; Layout.preferredHeight: implicitHeight; spacing: 9
                            NeuButton { text: 'Rinomina'; compact: true; enabled: !!archive.selected.id; onClicked: archive.rename(sessionName.text) }
                            NeuButton { text: 'Copia'; compact: true; enabled: !!archive.selected.id; onClicked: feedback.copy(archive.text) }
                            NeuButton { text: 'Esporta .txt'; compact: true; enabled: !!archive.selected.id; onClicked: archive.export('txt') }
                            NeuButton { text: 'Esporta .vtt'; compact: true; enabled: !!archive.selected.id; onClicked: archive.export('vtt') }
                            NeuButton { text: 'Esporta .srt'; compact: true; enabled: !!archive.selected.id; onClicked: archive.export('srt') }
                            NeuButton { text: 'Elimina'; compact: true; enabled: !!archive.selected.id && !meeting.dirty && !meeting.saving; onClicked: { let id=archive.selected.id; shell.confirm('Eliminare questa trascrizione?',()=>archive.deleteSession(id)) } }
                            NeuButton { text: 'Apri revisione'; compact: true; visible: archive.selected.kind==='meeting'; onClicked: { meeting.select(archive.selected.id); shell.view='meeting' } }
                        }
                    }
                }
                GridLayout { visible: !!archive.selected.id; Layout.fillWidth: true; columns: 2; columnSpacing: 16
                    Metric { Layout.fillWidth: true; label: 'Tipo'; value: archive.selected.kind || '' }
                    Metric { Layout.fillWidth: true; label: 'Stato'; value: Theme.statusName(archive.selected.status) }
                    Metric { Layout.fillWidth: true; label: 'Modello'; value: Theme.modelName(archive.selected.model) }
                    Metric { Layout.fillWidth: true; label: 'Lingua'; value: archive.selected.language || 'auto' }
                    Metric { Layout.fillWidth: true; label: 'Avvio'; value: archive.selected.started_at || '' }
                    Metric { Layout.fillWidth: true; label: 'Sorgente'; value: archive.selected.source || '' }
                }
                RowLayout { visible: !!archive.selected.id; Layout.fillWidth: true; FieldLabel { text: 'Vista testo' } NeuCombo { id: profile; Layout.fillWidth: true; model: postprocessProfiles; labelRole: 'label'; keyRole: 'id'; selectedValue: archive.profile; onChosen: value=>archive.setProfile(value) } NeuButton { text: 'Genera profilo'; compact: true; enabled: archive.profile!=='raw'; onClicked: archive.generate(archive.profile) } }
                AudioPlayer { Layout.fillWidth: true; visible: !!archive.recording.exists; source: archive.recording.url || '' }
                NeuButton { text: 'Elimina audio'; visible: !!archive.recording.exists; onClicked: shell.confirm('Eliminare la registrazione microfono?',()=>archive.deleteRecording()) }
                Transcript { Layout.fillWidth: true; Layout.preferredHeight: 270; text: archive.text; placeholder: 'Il contenuto della sessione selezionata apparirà qui.' }
                Item { Layout.fillHeight: true }
            }
        }
        Card { objectName: 'recoveryCard'; Layout.fillWidth: true; Layout.preferredHeight: recoveryModel.count ? implicitHeight : 177.59
            CardHead { kicker: 'RECOVERY'; title: 'Audio non trascritto' }
            Help { Layout.fillWidth: true; text: 'I recovery WAV possono essere ritrascritti con il modello e la lingua correnti. Il file originale resta disponibile finché non lo elimini esplicitamente.' }
            EmptyState { Layout.fillWidth: true; visible: recoveryModel.count===0; text: 'Nessun audio da recuperare.' }
            ListView { id: recovery; Layout.fillWidth: true; Layout.preferredHeight: Math.min(300,recoveryModel.count*70); visible: recoveryModel.count>0; model: recoveryModel; reuseItems: true; spacing: 9; clip: true; cacheBuffer: 0
                delegate: RowLayout { required property var record; width: recovery.width; height: 60; Help { Layout.fillWidth: true; text: record.path || record.name || '' } NeuButton { compact: true; text: 'Ritrascrivi'; onClicked: archive.recover(record.path) } NeuButton { compact: true; text: 'Elimina'; onClicked: { let path=record.path; shell.confirm('Eliminare questo audio da recuperare?',()=>archive.deleteRecovery(path)) } } }
            }
        }
    }
}
