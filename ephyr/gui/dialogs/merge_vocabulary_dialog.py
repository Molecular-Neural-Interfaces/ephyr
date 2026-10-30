# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


@dataclass(frozen=True)
class MergeGroupOption:
    group_id: int
    name: str
    color: str
    count: int


class MergeVocabularyDialog(QDialog):
    """Pick vocabulary groups to replace with one new group."""

    def __init__(self, *, title: str, groups: list[MergeGroupOption], parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(640, 420)
        self.setMinimumWidth(520)

        self._groups = list(groups)
        self._selected_ids: list[int] = []
        self._name = ""

        layout = QVBoxLayout(self)

        intro = QLabel("Check the groups to replace with one group, and name that group.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["", "ID", "Name", "Color", "Count"])
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setWordWrap(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 36)
        layout.addWidget(self.table)

        for row_index, group in enumerate(self._groups):
            self.table.insertRow(row_index)
            check_item = QTableWidgetItem()
            check_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            check_item.setCheckState(Qt.CheckState.Unchecked)
            check_item.setData(Qt.ItemDataRole.UserRole, group.group_id)
            self.table.setItem(row_index, 0, check_item)

            id_item = QTableWidgetItem(str(group.group_id))
            id_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(row_index, 1, id_item)

            name_item = QTableWidgetItem(group.name)
            name_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(row_index, 2, name_item)

            color_value = group.color or ""
            color_item = QTableWidgetItem(color_value.upper())
            color_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            color = QColor(color_value)
            if color.isValid():
                color_item.setBackground(color)
            self.table.setItem(row_index, 3, color_item)

            count_item = QTableWidgetItem(str(group.count))
            count_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(row_index, 4, count_item)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Name of the merged group")
        layout.addWidget(QLabel("Merged group name"))
        layout.addWidget(self.name_edit)
        color_note = QLabel("The merged group keeps the color of the checked group with the smallest ID.")
        color_note.setWordWrap(True)
        layout.addWidget(color_note)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_merge = QPushButton("Merge")
        self.btn_cancel.setAutoDefault(False)
        self.btn_merge.setAutoDefault(False)
        self.btn_merge.setDefault(True)
        buttons.addWidget(self.btn_cancel)
        buttons.addWidget(self.btn_merge)
        layout.addLayout(buttons)

        self.btn_cancel.clicked.connect(self.reject)
        self.btn_merge.clicked.connect(self._on_merge_clicked)
        self.name_edit.textChanged.connect(lambda _text: self._update_status())
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.cellClicked.connect(self._on_cell_clicked)
        self._update_status()

    def selection(self) -> tuple[list[int], str]:
        return list(self._selected_ids), self._name

    def _checked_ids(self) -> list[int]:
        checked = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is None or item.checkState() != Qt.CheckState.Checked:
                continue
            group_id = item.data(Qt.ItemDataRole.UserRole)
            if group_id is not None:
                checked.append(int(group_id))
        return checked

    def _validation_error(self) -> str | None:
        checked = self._checked_ids()
        if len(checked) < 2:
            return "Select at least two groups."
        name = self.name_edit.text().strip()
        if not name:
            return "Enter a name for the merged group."
        removed = set(checked)
        taken = {group.name for group in self._groups if group.group_id not in removed}
        if name in taken:
            return f"Name '{name}' is already used."
        return None

    def _update_status(self) -> None:
        error = self._validation_error()
        self.btn_merge.setEnabled(error is None)
        if error is None:
            self.status_label.setText(f"{len(self._checked_ids())} groups selected.")
        else:
            self.status_label.setText(error)

    def _on_cell_clicked(self, row: int, column: int) -> None:
        if column == 0:
            return
        item = self.table.item(row, 0)
        if item is None:
            return
        item.setCheckState(
            Qt.CheckState.Unchecked if item.checkState() == Qt.CheckState.Checked else Qt.CheckState.Checked
        )

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() == 0:
            self._update_status()

    def _on_merge_clicked(self) -> None:
        if self._validation_error() is not None:
            self._update_status()
            return
        self._selected_ids = self._checked_ids()
        self._name = self.name_edit.text().strip()
        self.accept()
