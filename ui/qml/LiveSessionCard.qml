import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: card
    required property var record
    RaisedSurface {
        anchors.fill: parent
        soft: true
        radius: Theme.radiusMD
    }
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 12
        spacing: 8
        RowLayout {
            Layout.fillWidth: true
            NeuField {
                Layout.fillWidth: true
                text: card.record.name || Theme.sourceName(card.record.source)
                maximumLength: 120
                Accessible.name: 'Titolo trascrizione'
                onEditingFinished: live.rename(card.record.id, text)
            }
            Help {
                text: card.record.terminal ? Theme.statusName(card.record.status) : ''
            }
        }
        RowLayout {
            Layout.fillWidth: true
            visible: (card.record.pending_audio_s || 0) > 0
            Help {
                text: Number(card.record.pending_audio_s || 0).toFixed(1) + ' s di audio in attesa'
                color: (card.record.buffer_level || 0) >= 100 ? Theme.accent : Theme.secondary
            }
            Help {
                text: (card.record.spooled_chunks || 0) > 0 ? 'Conservato anche su disco' : ''
            }
        }
        Transcript {
            objectName: 'liveTranscript' + card.record.id
            Layout.fillWidth: true
            Layout.fillHeight: true
            text: card.record.text || ''
            autoScroll: true
        }
        Flow {
            Layout.fillWidth: true
            Layout.preferredHeight: implicitHeight
            spacing: 6
            NeuButton {
                compact: true
                text: 'Copia'
                enabled: !!card.record.text
                onClicked: live.copy(card.record.id)
            }
            NeuButton {
                compact: true
                text: 'Termina e completa'
                enabled: !card.record.terminal && !card.record.draining && !!card.record.capture_running
                onClicked: live.stop(card.record.id, true)
                ToolTip.visible: hovered
                ToolTip.text: 'Ferma la cattura e trascrive tutto l’audio residuo.'
            }
            NeuButton {
                compact: true
                text: 'Ferma'
                enabled: !card.record.terminal
                onClicked: live.stop(card.record.id, false)
                ToolTip.visible: hovered
                ToolTip.text: 'Interrompe subito. L’audio non ancora trascritto resta disponibile nel recovery.'
            }
            NeuButton {
                compact: true
                text: 'Rimuovi'
                enabled: !!card.record.terminal
                onClicked: live.remove(card.record.id)
            }
        }
    }
}
