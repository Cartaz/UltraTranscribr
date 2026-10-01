import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtMultimedia

RowLayout {
    id: root
    property url source: ''
    function seek(seconds) {
        player.position = seconds * 1000;
    }
    MediaPlayer {
        id: player
        source: root.source
        audioOutput: AudioOutput {}
        onErrorOccurred: (error, message) => feedback.show(message)
    }
    NeuButton {
        text: player.playbackState === MediaPlayer.PlayingState ? 'Pausa' : 'Riproduci'
        enabled: !!root.source
        onClicked: player.playbackState === MediaPlayer.PlayingState ? player.pause() : player.play()
    }
    Slider {
        id: slider
        Layout.fillWidth: true
        background: Item {
            x: slider.leftPadding
            y: slider.topPadding + (slider.availableHeight - height) / 2
            width: slider.availableWidth
            height: 7
            InsetSurface {
                anchors.fill: parent
                radius: 3.5
            }
            Rectangle {
                height: parent.height
                width: slider.visualPosition * parent.width
                radius: 3.5
                color: Theme.accent
            }
        }
        handle: Rectangle {
            x: slider.leftPadding + slider.visualPosition * (slider.availableWidth - width)
            y: slider.topPadding + (slider.availableHeight - height) / 2
            width: 14
            height: 14
            radius: 7
            color: Theme.accent
        }
        from: 0
        to: Math.max(1, player.duration)
        value: player.position
        onMoved: player.position = value
    }
    Help {
        text: Math.floor(player.position / 1000) + ' / ' + Math.floor(player.duration / 1000) + ' s'
    }
}
