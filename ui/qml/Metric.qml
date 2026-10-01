import QtQuick
import QtQuick.Layouts
RowLayout {
    id: root
    property string label: ''
    property string value: ''
    implicitHeight: 28
    Text { text: root.label; color: Theme.muted; font.family: Theme.font; font.pixelSize: 14 }
    Text { Layout.fillWidth: true; text: root.value; color: Theme.primary; font.family: Theme.font; font.pixelSize: 14; horizontalAlignment: Text.AlignRight; elide: Text.ElideRight }
}
