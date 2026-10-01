import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
Item {
    id: root
    property var queueModel
    implicitHeight: queueModel.count ? Math.min(230,queueModel.count*80) : 46
    EmptyState { anchors.fill: parent; visible: root.queueModel.count===0; text: 'Coda vuota.' }
    ListView { id: list; anchors.fill: parent; visible: root.queueModel.count>0; model: root.queueModel; reuseItems: true; cacheBuffer: 0; spacing: 10; clip: true; ScrollBar.vertical: ScrollBar {}
        delegate: Item { required property var record; width: list.width-10; height: 70; RaisedSurface { anchors.fill: parent; soft: true; radius: 12 }
            RowLayout { anchors.fill: parent; anchors.margins: 14
                Column { Layout.fillWidth: true; spacing: 3; Text { width: parent.width; text: record.path || record.source_path || record.id || ''; color: Theme.primary; font.family: Theme.font; font.pixelSize: 14; font.bold: true; elide: Text.ElideRight } Help { width: parent.width; text: record.error || Theme.statusName(record.status); maximumLineCount: 1; elide: Text.ElideRight } }
                ColumnLayout { Layout.preferredWidth: 180; Help { text: Theme.statusName(record.status) } NeuProgress { Layout.fillWidth: true; value: record.progress || 0 } }
            }
        }
    }
}
