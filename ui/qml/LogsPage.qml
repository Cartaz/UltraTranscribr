import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: page
    RowLayout {
        x: 2
        y: 2
        width: parent.width - 19
        spacing: 18
        Card {
            objectName: 'logsCard'
            Layout.fillWidth: true
            Layout.preferredWidth: parent.width - 318
            Layout.preferredHeight: 351.39
            Layout.alignment: Qt.AlignTop
            CardHead {
                kicker: 'RUNTIME'
                title: 'Log applicazione'
                CheckBox {
                    id: follow
                    text: 'Auto-scroll'
                    checked: true
                    font.family: Theme.font
                    font.pixelSize: 12
                    palette.windowText: Theme.secondary
                    palette.highlight: Theme.accent
                    indicator: Rectangle {
                        x: 3
                        y: (parent.height - height) / 2
                        width: 12
                        height: 12
                        radius: 2
                        color: follow.checked ? Theme.accent : Theme.surface
                        border.color: Theme.secondary
                        Text {
                            textFormat: Text.PlainText
                            anchors.centerIn: parent
                            text: follow.checked ? '✓' : ''
                            color: Theme.surface
                            font.pixelSize: 11
                        }
                    }
                }
                NeuButton {
                    compact: true
                    text: 'Aggiorna'
                    onClicked: runtime.refreshLog()
                }
                NeuButton {
                    compact: true
                    text: 'Copia'
                    onClicked: feedback.copy(runtime.logText)
                }
            }
            Transcript {
                Layout.fillWidth: true
                Layout.fillHeight: true
                text: runtime.logText
                monospace: true
                autoScroll: follow.checked
                placeholder: 'Nessun log persistente disponibile.'
            }
        }
        Card {
            objectName: 'diagnosticsCard'
            Layout.fillWidth: true
            Layout.preferredWidth: 300
            Layout.minimumWidth: 300
            Layout.preferredHeight: 351.39
            Layout.alignment: Qt.AlignTop
            CardHead {
                kicker: 'AUDIO'
                title: 'Diagnostica dispositivi'
                NeuButton {
                    compact: true
                    text: 'Esegui'
                    onClicked: runtime.runDiagnostics()
                }
            }
            Help {
                Layout.fillWidth: true
                text: 'Mostra output predefinito, monitor, dispositivi e stream applicazione PipeWire/PulseAudio.'
            }
            Transcript {
                Layout.fillWidth: true
                Layout.fillHeight: true
                text: runtime.diagnostics
                monospace: true
            }
        }
    }
}
