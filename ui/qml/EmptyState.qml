import QtQuick
Item {
    id: root
    property string text: ''
    property bool centered: false
    implicitHeight: centered ? 150 : 46
    InsetSurface { anchors.fill: parent; strong: root.centered }
    Text { anchors.fill: parent; anchors.margins: 14; text: root.text; color: Theme.muted; font.family: Theme.font; font.pixelSize: 14; wrapMode: Text.WordWrap; verticalAlignment: Text.AlignVCenter; horizontalAlignment: root.centered ? Text.AlignHCenter : Text.AlignLeft }
}
