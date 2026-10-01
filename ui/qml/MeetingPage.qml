import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
ScrollView {
    id: page
    property bool fromFile: false
    property real acquisitionHeight: 499.9375+(fromFile ? Math.min(260,meetingDrafts.count*92) : Math.max(0,Math.min(280,meetingSources.count*61)-61))
    clip: true; contentWidth: availableWidth
    ColumnLayout { width: page.availableWidth-19; x: 2; y: 2; spacing: 18
        RowLayout { Layout.fillWidth: true; spacing: 18; Layout.alignment: Qt.AlignTop
            Card { objectName: 'meetingInputCard'; Layout.fillWidth: true; Layout.preferredWidth: 1; Layout.preferredHeight: page.acquisitionHeight; Layout.fillHeight: true
                CardHead { kicker: 'RIUNIONE'; title: 'Acquisisci e analizza' }
                RowLayout { Layout.fillWidth: true; uniformCellSizes: true; NeuButton { Layout.fillWidth: true; text: 'In tempo reale'; selected: !page.fromFile; enabled: !meeting.busy; onClicked: page.fromFile=false } NeuButton { Layout.fillWidth: true; text: 'Da registrazione'; selected: page.fromFile; enabled: !meeting.busy; onClicked: page.fromFile=true } }
                CardHead { visible: !page.fromFile; kicker: 'SORGENTI'; title: 'Audio realtime'; NeuButton { text: 'Aggiorna'; compact: true; onClicked: sources.refresh() } NeuButton { text: 'Aggiungi sorgente'; compact: true; enabled: !meeting.busy && meetingSources.count<8; onClicked: meeting.addSource() } }
                ListView { id: inputs; visible: !page.fromFile; Layout.fillWidth: true; Layout.preferredHeight: Math.min(280,meetingSources.count*61); model: meetingSources; spacing: 9; reuseItems: true; cacheBuffer: 0; clip: true
                    delegate: Item { required property var record; required property int index; width: inputs.width; height: 61; InsetSurface { anchors.fill: parent }
                        RowLayout { anchors.fill: parent; anchors.margins: 9; spacing: 7
                            Text { Layout.preferredWidth: 88; text: 'Sorgente '+(index+1); color: Theme.primary; font.family: Theme.font; font.pixelSize: 13; font.bold: true }
                            EnumCombo { Layout.preferredWidth: 106; Layout.minimumWidth: 0; model: [{value:'microphone',label:'Microfono'},{value:'system',label:'Sistema'},{value:'application',label:'Applicazione'}]; selectedValue: record.source; enabled: !meeting.busy; onChosen: value=>meeting.editSource(index,'source',value) }
                            NeuCombo { Layout.fillWidth: true; Layout.minimumWidth: 0; model: record.source==='microphone' ? microphones : record.source==='system' ? monitors : playbackStreams; selectedValue: record.selected_input; enabled: !meeting.busy; onChosen: value=>meeting.editSource(index,'selected_input',value) }
                            NeuButton { text: '×'; compact: true; Layout.preferredWidth: 26; implicitWidth: 26; enabled: !meeting.busy && meetingSources.count>1; onClicked: meeting.removeSource(index); ToolTip.text: 'Rimuovi sorgente' }
                        }
                    }
                }
                Help { Layout.fillWidth: true; visible: !page.fromFile; text: 'Puoi combinare fino a 8 sorgenti: microfono, audio di sistema e singole applicazioni. Ogni sorgente viene conservata come traccia separata e sincronizzata nel mix della riunione.' }
                ColumnLayout { Layout.fillWidth: true; visible: page.fromFile; FieldLabel { text: 'Registrazioni audio o video' }
                    RowLayout { Layout.fillWidth: true; NeuField { Layout.fillWidth: true; readOnly: true; text: meetingDrafts.count===1 ? meetingDrafts.get(0).path : meetingDrafts.count ? meetingDrafts.count+' registrazioni selezionate' : ''; placeholderText: 'Nessun file selezionato' } NeuButton { text: 'Seleziona file'; enabled: !meeting.busy; onClicked: meeting.choose(language.text,Number(speakerCount.text)) } }
                    Help { Layout.fillWidth: true; text: 'Puoi selezionare più registrazioni. Verranno elaborate una alla volta con la stessa pipeline Whisper + Community-1, evitando inferenze GPU concorrenti.' }
                }
                RowLayout { Layout.fillWidth: true
                    ColumnLayout { Layout.fillWidth: true; Layout.preferredWidth: 1; FieldLabel { text: page.fromFile ? 'Lingua predefinita' : 'Lingua' } NeuField { id: language; Layout.fillWidth: true; text: settings.values.language || 'auto' } }
                    ColumnLayout { Layout.fillWidth: true; Layout.preferredWidth: 1; FieldLabel { text: page.fromFile ? 'Interlocutori predefiniti' : 'Interlocutori' } NeuField { id: speakerCount; Layout.fillWidth: true; text: '0'; validator: IntValidator { bottom: 0; top: 20 } } }
                }
                Help { Layout.fillWidth: true; text: page.fromFile ? '0 = rilevamento automatico. Dopo la selezione puoi modificare i valori separatamente per ogni registrazione.' : '0 = rilevamento automatico degli interlocutori.' }
                ListView { id: drafts; visible: page.fromFile && meetingDrafts.count>0; Layout.fillWidth: true; Layout.preferredHeight: Math.min(260,meetingDrafts.count*92); model: meetingDrafts; reuseItems: true; cacheBuffer: 0; clip: true; spacing: 9
                    delegate: ColumnLayout { required property var record; required property int index; width: drafts.width-8; height: 83; Help { Layout.fillWidth: true; text: record.path; elide: Text.ElideRight; maximumLineCount: 1 }
                        RowLayout { Layout.fillWidth: true; NeuField { Layout.fillWidth: true; text: record.language; onTextEdited: meeting.editDraft(index,'language',text) } NeuField { Layout.preferredWidth: 80; text: String(record.num_speakers); validator: IntValidator { bottom: 0; top: 20 } onTextEdited: meeting.editDraft(index,'num_speakers',Number(text)) } NeuButton { text: 'Rimuovi'; compact: true; onClicked: meeting.removeDraft(index) } }
                    }
                }
                Flow { Layout.fillWidth: true; Layout.preferredHeight: implicitHeight; spacing: 9
                    NeuButton { text: page.fromFile ? (meetingDrafts.count>1 ? 'Avvia batch ('+meetingDrafts.count+')' : 'Analizza registrazione') : 'Avvia riunione'; selected: true; enabled: !runtime.busy; onClicked: meeting.start(page.fromFile,language.text,Number(speakerCount.text)) }
                    NeuButton { text: 'Termina e analizza'; enabled: meeting.runtime.status==='recording'; onClicked: meeting.finish() }
                    NeuButton { text: 'Annulla'; enabled: meeting.busy; onClicked: meeting.cancel() }
                }
            }
            Card { objectName: 'meetingStatusCard'; Layout.fillWidth: true; Layout.preferredWidth: 1; Layout.preferredHeight: page.acquisitionHeight; Layout.fillHeight: true
                CardHead { kicker: 'STATO'; title: 'Pipeline riunione'; Rectangle { implicitWidth: 9; implicitHeight: 9; Layout.alignment: Qt.AlignTop; Layout.topMargin: 4; radius: 4.5; color: meeting.busy ? Theme.accent : Theme.muted } }
                Item { Layout.fillWidth: true; implicitHeight: 91; InsetSurface { anchors.fill: parent }
                    GridLayout { anchors.fill: parent; anchors.margins: 13; anchors.topMargin: 3; anchors.bottomMargin: 3; columns: 2; rowSpacing: 0; columnSpacing: 16; uniformCellWidths: true
                        Metric { Layout.fillWidth: true; label: 'Stato'; value: Theme.statusName(meeting.runtime.status) }
                        Metric { Layout.fillWidth: true; label: 'Durata'; value: meeting.duration }
                        Metric { Layout.fillWidth: true; label: 'Sorgenti'; value: meeting.runtime.sources ? String(meeting.runtime.sources.length || (meeting.runtime.mode==='file' ? 1 : '—')) : '—' }
                        Metric { Layout.fillWidth: true; label: 'Modello'; value: Theme.modelName(meeting.runtime.model) }
                        Metric { Layout.fillWidth: true; label: 'Lingua'; value: meeting.runtime.language || '—' }
                    }
                }
                FieldLabel { text: 'Trascrizione' }
                NeuProgress { Layout.fillWidth: true; value: meeting.runtime.progress || 0 }
                FieldLabel { text: 'Diarizzazione' }
                NeuProgress { Layout.fillWidth: true; value: meeting.runtime.diarization_progress || 0 }
                Help { Layout.fillWidth: true; text: 'La prima diarizzazione scarica Community-1 da Hugging Face; dopo il download il modello viene riutilizzato localmente.' }
                Help { visible: !!meeting.modelProgress.model && meeting.busy; Layout.fillWidth: true; text: (meeting.modelProgress.model || '')+' '+(meeting.modelProgress.percent || 0)+'%' }
                Item { Layout.fillHeight: true }
            }
        }
        Card { Layout.fillWidth: true; visible: meetingQueue.count>0
            CardHead { kicker: 'BATCH'; title: 'Coda riunioni'; NeuButton { text: 'Pulisci completate'; compact: true; onClicked: meeting.clearQueue() } NeuButton { text: 'Annulla coda'; compact: true; onClicked: meeting.cancelQueue() } }
            QueueList { Layout.fillWidth: true; queueModel: meetingQueue }
        }
        Card { objectName: 'meetingArchiveCard'; Layout.fillWidth: true
            CardHead { kicker: 'ARCHIVIO'; title: 'Riunioni recenti'; NeuButton { text: 'Aggiorna'; compact: true; onClicked: archive.refresh() } }
            EmptyState { Layout.fillWidth: true; visible: meetingsModel.count===0; text: 'Nessuna riunione salvata.' }
            ListView { id: recent; visible: meetingsModel.count>0; Layout.fillWidth: true; Layout.preferredHeight: Math.min(300,meetingsModel.count*57); model: meetingsModel; reuseItems: true; cacheBuffer: 0; clip: true; spacing: 9
                delegate: RowLayout { required property var record; width: recent.width; height: 48; NeuButton { Layout.fillWidth: true; text: record.name || record.id; alignLeft: true; onClicked: meeting.select(record.id) } NeuButton { text: 'Elimina'; compact: true; enabled: !meeting.dirty && !meeting.saving; onClicked: { let id=record.id; shell.confirm('Eliminare questa riunione e il relativo audio?',()=>archive.deleteSession(id)) } } }
            }
        }
        RowLayout { visible: !!meeting.review.id; Layout.fillWidth: true; Layout.alignment: Qt.AlignTop; spacing: 18
            Card { objectName: 'meetingReviewCard'; Layout.fillWidth: true; Layout.preferredWidth: 356; Layout.horizontalStretchFactor: 4; Layout.alignment: Qt.AlignTop
                CardHead { kicker: 'REVISIONE'; title: meeting.review.name || 'Riunione' }
                ListView { id: tracks; visible: meetingTracks.count>0; Layout.fillWidth: true; Layout.preferredHeight: Math.min(180,meetingTracks.count*42); model: meetingTracks; reuseItems: true; cacheBuffer: 0; clip: true
                    delegate: Help { required property var record; width: tracks.width; height: 42; text: (record.label || Theme.sourceName(record.source))+' · '+(record.selected_input || 'Automatico') }
                }
                AudioPlayer { id: audio; Layout.fillWidth: true; source: meeting.audioUrl }
                Flow { Layout.fillWidth: true; Layout.preferredHeight: implicitHeight; spacing: 8; NeuButton { text: 'Esporta .txt'; compact: true; onClicked: meeting.export('txt') } NeuButton { text: 'Esporta .srt'; compact: true; onClicked: meeting.export('srt') } NeuButton { text: 'Esporta .vtt'; compact: true; onClicked: meeting.export('vtt') } NeuButton { text: 'Elimina audio'; compact: true; enabled: !!meeting.audioUrl; onClicked: shell.confirm('Eliminare l’audio della riunione?',()=>meeting.deleteAudio()) } }
                FieldLabel { text: 'Interlocutori per il ricalcolo' }
                NeuField { id: recalc; Layout.fillWidth: true; text: '0'; validator: IntValidator { bottom: 0; top: 20 } }
                NeuButton { text: 'Ricalcola diarizzazione'; selected: true; enabled: !runtime.busy && !meeting.dirty && !meeting.saving; onClicked: meeting.rerun(Number(recalc.text)) }
                ListView { id: speakers; Layout.fillWidth: true; Layout.preferredHeight: Math.min(250,meetingSpeakers.count*55); model: meetingSpeakers; reuseItems: true; cacheBuffer: 0; clip: true
                    delegate: RowLayout { required property var record; required property int index; width: speakers.width; height: 50; Help { text: record.id } NeuField { id: speakerName; Layout.fillWidth: true; text: record.draft_name == null ? record.name : record.draft_name; onTextEdited: meeting.editSpeakerName(index,text) } NeuButton { text: 'Salva'; compact: true; enabled: !meeting.saving; onClicked: meeting.renameSpeaker(record.id,speakerName.text) } }
                }
                Transcript { Layout.fillWidth: true; Layout.preferredHeight: 220; text: meeting.review.full_text || meeting.review.text || ''; placeholder: 'Raw Whisper' }
            }
            Card { objectName: 'meetingCorrectionsCard'; Layout.fillWidth: true; Layout.preferredWidth: 535; Layout.horizontalStretchFactor: 6; Layout.alignment: Qt.AlignTop
                CardHead { kicker: 'CORREZIONI'; title: 'Trascrizione per interlocutore' }
                RowLayout { NeuButton { text: 'Salva tutto'; selected: true; enabled: meeting.dirty && !meeting.saving; onClicked: meeting.saveAll() } NeuButton { text: 'Annulla correzioni'; enabled: meeting.dirty && !meeting.saving; onClicked: meeting.discardEdits() } Help { text: meeting.dirty ? 'Modifiche non salvate' : 'Tutto salvato' } }
                Help { Layout.fillWidth: true; text: 'Speaker e testo possono essere corretti senza modificare il raw Whisper.' }
                ListView { id: review; objectName: 'meetingReviewList'; Layout.fillWidth: true; Layout.preferredHeight: 520; model: meetingSegments; reuseItems: true; cacheBuffer: 0; clip: true; spacing: 5; ScrollBar.vertical: ScrollBar {}
                    delegate: Item { required property var record; required property int index; width: review.width-10; height: Math.max(99,editor.implicitHeight+46+(record.uncertain || record.overlap ? 20 : 0))
                        InsetSurface { anchors.fill: parent; radius: 12 }
                        Rectangle { anchors.fill: parent; color: 'transparent'; radius: 12; border.width: record.uncertain || record.overlap ? 1 : 0; border.color: Theme.accent }
                        ColumnLayout { anchors.fill: parent; anchors.margins: 9; spacing: 4
                            RowLayout { Layout.fillWidth: true; NeuButton { text: Math.floor(record.start || 0)+' s'; compact: true; onClicked: audio.seek(record.start || 0) } NeuCombo { Layout.fillWidth: true; model: meetingSpeakers; keyRole: 'id'; selectedValue: record.speaker; onChosen: value=>meeting.setSpeaker(index,value) } NeuButton { text: 'Salva'; compact: true; enabled: !!record.dirty && !meeting.saving; onClicked: meeting.saveSegment(index) } }
                            Help { visible: !!record.uncertain || !!record.overlap; text: record.overlap ? 'Voci sovrapposte' : 'Interlocutore incerto'; color: Theme.accent }
                            TextArea { id: editor; objectName: 'reviewEditor'+index; Layout.fillWidth: true; Layout.fillHeight: true; text: record.draft_text || ''; color: Theme.primary; font.family: Theme.font; font.pixelSize: 14; wrapMode: TextEdit.Wrap; selectByMouse: true; background: null; padding: 6; onTextChanged: if (activeFocus) meeting.editText(index,text) }
                        }
                    }
                }
            }
        }
    }
    DropArea { anchors.fill: parent; onDropped: drop=> { if (drop.hasUrls) { page.fromFile=true; meeting.dropFiles(drop.urls,language.text,Number(speakerCount.text)); drop.acceptProposedAction() } } }
}
