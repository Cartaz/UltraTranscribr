import QtQuick
import QtQuick.Layouts

ColumnLayout {
    id: root
    property string keyName
    property string label
    property var options: []
    property bool numeric: false
    property bool locked: false
    property string fixedValue: ''
    property string hint: ''
    Layout.fillWidth: true
    Layout.minimumWidth: 0
    Layout.preferredWidth: 1
    spacing: 7
    FieldLabel {
        text: root.label
    }
    NeuField {
        objectName: root.keyName + 'Field'
        Layout.fillWidth: true
        visible: root.options.length === 0
        text: root.locked ? root.fixedValue : String(settings.values[root.keyName] == null ? '' : settings.values[root.keyName])
        placeholderText: root.hint
        readOnly: root.locked
        inputMethodHints: root.numeric ? Qt.ImhDigitsOnly : Qt.ImhNone
        onTextEdited: settings.edit(root.keyName, root.numeric ? Number(text) : text)
    }
    EnumCombo {
        objectName: root.keyName + 'Control'
        Layout.fillWidth: true
        visible: root.options.length > 0
        model: root.options
        selectedValue: String(settings.values[root.keyName] || '')
        enabled: !runtime.busy && !settings.saving && !settings.modelBusy
        onChosen: value => root.keyName === 'model_size' ? settings.selectModel(value) : settings.edit(root.keyName, value)
    }
}
