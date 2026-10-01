import QtQuick
import QtQuick.Layouts
RowLayout {
    id: root
    property string kicker: ''
    property string title: ''
    default property alias actions: toolbar.data
    Layout.fillWidth: true; implicitHeight: Math.max(39,titleColumn.implicitHeight); spacing: 14
    Column { id: titleColumn; Layout.fillWidth: true; spacing: 4; Text { text: root.kicker; visible: text.length>0; color: Theme.accent; font.family: Theme.font; font.pixelSize: 10; font.weight: Font.ExtraBold; font.letterSpacing: 1.8 } Text { width: parent.width; wrapMode: Text.WordWrap; text: root.title; color: Theme.primary; font.family: Theme.font; font.pixelSize: 18; font.bold: true } }
    RowLayout { id: toolbar; spacing: 9 }
}
