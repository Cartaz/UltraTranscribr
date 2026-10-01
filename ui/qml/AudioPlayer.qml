import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtMultimedia

Item {
    id: root
    property url source: ''
    readonly property int position: player.position
    readonly property int duration: player.duration
    readonly property bool playing: player.playbackState === MediaPlayer.PlayingState
    property real pendingSeek: -1
    implicitHeight: 54
    implicitWidth: 300
    function clock(milliseconds) {
        let seconds = Math.floor(Math.max(0, milliseconds) / 1000);
        return Math.floor(seconds / 60) + ':' + String(seconds % 60).padStart(2, '0');
    }
    function seek(seconds) {
        if (!isFinite(seconds) || seconds < 0 || !root.source.toString())
            return;
        if (player.duration > 0 && player.seekable && player.mediaStatus !== MediaPlayer.LoadingMedia) {
            player.position = Math.min(seconds * 1000, player.duration);
            pendingSeek = -1;
        } else {
            pendingSeek = seconds;
        }
    }
    onSourceChanged: {
        pendingSeek = -1;
        player.stop();
    }
    Component.onDestruction: {
        player.stop();
        player.source = '';
    }
    MediaPlayer {
        id: player
        objectName: 'audioMediaPlayer'
        source: root.source
        audioOutput: AudioOutput {
            id: output
            objectName: 'audioOutput'
        }
        onMediaStatusChanged: if ((mediaStatus === MediaPlayer.LoadedMedia || mediaStatus === MediaPlayer.BufferedMedia) && root.pendingSeek >= 0)
            root.seek(root.pendingSeek)
        onErrorOccurred: (error, message) => feedback.show(message)
    }
    Rectangle {
        anchors.fill: parent
        radius: height / 2
        color: '#333333'
    }
    component IconButton: Button {
        id: control
        property string glyph: 'play'
        implicitWidth: 32
        implicitHeight: 32
        activeFocusOnTab: true
        background: Rectangle {
            radius: 16
            color: control.hovered ? '#444444' : 'transparent'
            border.width: control.activeFocus ? 1 : 0
            border.color: Theme.primary
        }
        contentItem: Canvas {
            id: canvas
            Connections {
                target: control
                function onGlyphChanged() { canvas.requestPaint(); }
                function onEnabledChanged() { canvas.requestPaint(); }
            }
            onPaint: {
                let c = getContext('2d');
                c.reset();
                c.translate(width / 2 - 10, height / 2 - 10);
                c.globalAlpha = control.enabled ? 1 : .4;
                c.fillStyle = '#e1e1e1';
                c.strokeStyle = '#e1e1e1';
                c.lineWidth = 1.7;
                if (control.glyph === 'play') {
                    c.beginPath(); c.moveTo(7, 4); c.lineTo(7, 16); c.lineTo(15, 10); c.closePath(); c.fill();
                } else if (control.glyph === 'pause') {
                    c.fillRect(6, 4, 3, 12); c.fillRect(12, 4, 3, 12);
                } else if (control.glyph === 'menu') {
                    for (let y of [4, 10, 16]) { c.beginPath(); c.arc(10, y, 1.5, 0, Math.PI * 2); c.fill(); }
                } else {
                    c.beginPath(); c.moveTo(3, 7); c.lineTo(6, 7); c.lineTo(11, 3); c.lineTo(11, 17); c.lineTo(6, 13); c.lineTo(3, 13); c.closePath(); c.fill();
                    if (control.glyph === 'muted') {
                        c.beginPath(); c.moveTo(14, 7); c.lineTo(19, 13); c.moveTo(19, 7); c.lineTo(14, 13); c.stroke();
                    } else {
                        c.beginPath(); c.arc(10, 10, 5, -.85, .85); c.stroke();
                        c.beginPath(); c.arc(10, 10, 8, -.85, .85); c.stroke();
                    }
                }
            }
        }
    }
    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 14
        anchors.rightMargin: 10
        spacing: 6
        IconButton {
            objectName: 'audioPlayButton'
            glyph: root.playing ? 'pause' : 'play'
            enabled: !!root.source.toString()
            Accessible.name: root.playing ? 'Pausa' : 'Riproduci'
            ToolTip.text: Accessible.name
            ToolTip.visible: hovered
            onClicked: root.playing ? player.pause() : player.play()
        }
        Text {
            textFormat: Text.PlainText
            text: root.clock(player.position) + ' / ' + root.clock(player.duration)
            color: Theme.primary
            font.family: Theme.font
            font.pixelSize: 13
        }
        Slider {
            id: slider
            objectName: 'audioSeekSlider'
            Layout.fillWidth: true
            Layout.minimumWidth: 20
            implicitHeight: 32
            enabled: player.seekable && player.duration > 0
            Accessible.name: 'Posizione audio'
            from: 0
            to: Math.max(1, player.duration)
            value: player.position
            onMoved: player.position = value
            background: Rectangle {
                x: slider.leftPadding
                y: (slider.height - height) / 2
                width: slider.availableWidth
                height: 4
                radius: 2
                color: '#555555'
                Rectangle {
                    width: slider.visualPosition * parent.width
                    height: parent.height
                    radius: 2
                    color: '#e1e1e1'
                }
                border.width: slider.activeFocus ? 1 : 0
                border.color: Theme.primary
            }
            handle: Rectangle {
                visible: slider.enabled && (slider.hovered || slider.pressed || slider.activeFocus)
                x: slider.leftPadding + slider.visualPosition * (slider.availableWidth - width)
                y: (slider.height - height) / 2
                width: 10
                height: 10
                radius: 5
                color: Theme.primary
            }
        }
        IconButton {
            objectName: 'audioMuteButton'
            glyph: output.muted ? 'muted' : 'volume'
            enabled: !!root.source.toString()
            Accessible.name: output.muted ? 'Riattiva audio' : 'Disattiva audio'
            ToolTip.text: Accessible.name
            ToolTip.visible: hovered
            onClicked: output.muted = !output.muted
        }
        IconButton {
            objectName: 'audioMenuButton'
            glyph: 'menu'
            implicitWidth: 24
            Accessible.name: 'Opzioni audio'
            onClicked: options.open()
            Menu {
                id: options
                y: parent.height
                MenuItem {
                    text: 'Volume'
                    enabled: false
                }
                Slider {
                    objectName: 'audioVolumeSlider'
                    width: 180
                    from: 0
                    to: 1
                    value: output.volume
                    Accessible.name: 'Volume audio'
                    onMoved: output.volume = value
                }
                MenuSeparator {}
                MenuItem {
                    text: 'Velocità 0.5×'
                    checkable: true
                    checked: player.playbackRate === .5
                    onTriggered: player.playbackRate = .5
                }
                MenuItem {
                    text: 'Velocità 1×'
                    checkable: true
                    checked: player.playbackRate === 1
                    onTriggered: player.playbackRate = 1
                }
                MenuItem {
                    objectName: 'audioSpeed1.5'
                    text: 'Velocità 1.5×'
                    checkable: true
                    checked: player.playbackRate === 1.5
                    onTriggered: player.playbackRate = 1.5
                }
                MenuItem {
                    text: 'Velocità 2×'
                    checkable: true
                    checked: player.playbackRate === 2
                    onTriggered: player.playbackRate = 2
                }
            }
        }
    }
}
