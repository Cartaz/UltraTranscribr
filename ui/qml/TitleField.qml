import QtQuick

// Editable title that is not bound to its model value: frequent model updates
// (Live text, File progress) must not overwrite what the user is typing, and
// finishing without typing must not pin a computed title as a custom name.
NeuField {
    id: field
    property string committed: ''
    property bool edited: false
    signal commit(string value)
    maximumLength: 120
    Component.onCompleted: text = committed
    onCommittedChanged: if (!edited) text = committed
    onTextEdited: edited = true
    onEditingFinished: {
        const value = text;
        const changed = edited && value !== committed;
        edited = false;
        if (changed)
            commit(value);
        else
            text = committed;
    }
}
