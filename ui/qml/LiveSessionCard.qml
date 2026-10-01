import QtQuick
import QtQuick.Layouts

Item {
    id: card
    property var record: ({})
    opacity: record.terminal ? .78 : 1
    RaisedSurface {
        anchors.fill: parent
        soft: true
        radius: Theme.radiusLG
    }
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 13
        spacing: 10
        RowLayout {
            Layout.fillWidth: true
            Column {
                Layout.fillWidth: true
                spacing: 3
                Text {
                    textFormat: Text.PlainText
                    text: Theme.sourceName(card.record.source || 'system').toUpperCase()
                    color: Theme.accent
                    font.family: Theme.font
                    font.pixelSize: 10
                    font.bold: true
                    font.letterSpacing: 1.8
                }
                Text {
                    textFormat: Text.PlainText
                    width: parent.width
                    text: card.record.source_path || Theme.sourceName(card.record.source || 'system')
                    color: Theme.primary
                    font.family: Theme.font
                    font.pixelSize: 15
                    font.bold: true
                    elide: Text.ElideRight
                }
                Help {
                    width: parent.width
                    text: card.record.id || ''
                    maximumLineCount: 1
                    elide: Text.ElideRight
                }
            }
            Help {
                text: Theme.statusName(card.record.status)
            }
        }
        Item {
            Layout.fillWidth: true
            implicitHeight: 73
            InsetSurface {
                anchors.fill: parent
            }
            GridLayout {
                anchors.fill: parent
                anchors.margins: 12
                columns: 2
                rowSpacing: 1
                columnSpacing: 14
                uniformCellWidths: true
                Metric {
                    Layout.fillWidth: true
                    label: 'Modello'
                    value: Theme.modelName(card.record.model)
                }
                Metric {
                    Layout.fillWidth: true
                    label: 'Lingua'
                    value: card.record.language || 'auto'
                }
                Metric {
                    Layout.fillWidth: true
                    label: 'Coda'
                    value: Math.round(card.record.queue_wait_ms || 0) + ' ms'
                }
                Metric {
                    Layout.fillWidth: true
                    label: 'Routing'
                    value: card.record.route_status || (card.record.source === 'application' ? 'isolato' : 'diretto')
                }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            FieldLabel {
                text: 'Buffer'
            }
            NeuProgress {
                Layout.fillWidth: true
                value: card.record.buffer_level || 0
            }
            Help {
                text: Math.round(card.record.buffer_level || 0) + '%'
            }
        }
        Transcript {
            Layout.fillWidth: true
            Layout.fillHeight: true
            text: card.record.text || ''
        }
        RowLayout {
            NeuButton {
                compact: true
                text: 'Copia'
                enabled: !!card.record.text
                onClicked: live.copy(card.record.id)
            }
            NeuButton {
                compact: true
                text: 'Completa buffer'
                enabled: !card.record.terminal && !card.record.draining && !!card.record.capture_running
                onClicked: live.stop(card.record.id, true)
            }
            NeuButton {
                compact: true
                text: 'Ferma'
                enabled: !card.record.terminal
                onClicked: live.stop(card.record.id, false)
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
