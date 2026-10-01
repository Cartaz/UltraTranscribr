"""Stable-role Qt models; snapshots and drafts stay in Python."""

from copy import deepcopy
from PySide6.QtCore import QAbstractListModel, QModelIndex, Property, Qt, Signal, Slot


class RecordModel(QAbstractListModel):
    countChanged = Signal()
    RecordRole = Qt.ItemDataRole.UserRole + 1

    def __init__(self, rows=(), parent=None):
        super().__init__(parent)
        self._rows = deepcopy(list(rows))

    def roleNames(self):
        return {self.RecordRole: b"record"}

    def rowCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else len(self._rows)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if (
            index.isValid()
            and 0 <= index.row() < len(self._rows)
            and role == self.RecordRole
        ):
            return deepcopy(self._rows[index.row()])
        return None

    @Property(int, notify=countChanged)
    def count(self):
        return len(self._rows)

    @Slot(int, result="QVariantMap")
    def get(self, index):
        return deepcopy(self._rows[index]) if 0 <= index < len(self._rows) else {}

    def rows(self):
        return deepcopy(self._rows)

    def replace(self, rows):
        rows = deepcopy(list(rows))
        if rows == self._rows:
            return
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()
        self.countChanged.emit()

    def update(self, row_index, **values):
        if not 0 <= row_index < len(self._rows):
            raise IndexError("riga non valida")
        row = {**self._rows[row_index], **deepcopy(values)}
        if row != self._rows[row_index]:
            self._rows[row_index] = row
            self.dataChanged.emit(
                self.index(row_index, 0), self.index(row_index, 0), [self.RecordRole]
            )

    def append(self, row):
        i = len(self._rows)
        self.beginInsertRows(QModelIndex(), i, i)
        self._rows.append(deepcopy(row))
        self.endInsertRows()
        self.countChanged.emit()

    def upsert(self, row, key="id"):
        for i, old in enumerate(self._rows):
            if old.get(key) == row.get(key):
                self.update(i, **row)
                return
        self.append(row)

    def remove(self, index):
        if 0 <= index < len(self._rows):
            self.beginRemoveRows(QModelIndex(), index, index)
            self._rows.pop(index)
            self.endRemoveRows()
            self.countChanged.emit()

    def remove_key(self, value, key="id"):
        for i, row in enumerate(self._rows):
            if row.get(key) == value:
                self.remove(i)
                return
