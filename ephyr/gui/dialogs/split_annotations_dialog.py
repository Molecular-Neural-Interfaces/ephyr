# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


class SplitAnnotationsDialog(QDialog):
    """Choose which rows of one group stay together. The rest form the second group."""

    def __init__(self, *, title: str, intro: str, columns: list[str], rows: list[list[str]], parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(780, 480)
        self.setMinimumWidth(640)

        self._selected_rows: list[int] = []

        layout = QVBoxLayout(self)

        intro_label = QLabel(intro)
        intro_label.setWordWrap(True)
        layout.addWidget(intro_label)

        self.table = QTableWidget(0, 1 + len(columns))
        self.table.setHorizontalHeaderLabels(["", *columns])
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setVisible(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setStretchLastSection(True)
        self.table.setColumnWidth(0, 36)
        layout.addWidget(self.table)

        for row_index, values in enumerate(rows):
            self.table.insertRow(row_index)
            check_item = QTableWidgetItem()
            check_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            check_item.setCheckState(Qt.CheckState.Unchecked)
            self.table.setItem(row_index, 0, check_item)
            for column_index, value in enumerate(values, start=1):
                text_item = QTableWidgetItem(value)
                text_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.table.setItem(row_index, column_index, text_item)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        buttons = QHBoxLayout()
        self.btn_all = QPushButton("Select all")
        self.btn_none = QPushButton("Unselect all")
        self.btn_odd = QPushButton("Select odd")
        self.btn_even = QPushButton("Select even")
        self.btn_odd.setToolTip("Check the 1st, 3rd, 5th, … rows")
        self.btn_even.setToolTip("Check the 2nd, 4th, 6th, … rows")
        self.btn_cancel = QPushButton("Cancel")
        self.btn_split = QPushButton("Split")
        for button in (self.btn_all, self.btn_none, self.btn_odd, self.btn_even, self.btn_cancel, self.btn_split):
            button.setAutoDefault(False)
            buttons.addWidget(button)
        self.btn_split.setDefault(True)
        layout.addLayout(buttons)

        self.btn_all.clicked.connect(lambda: self._set_checked(lambda row: True))
        self.btn_none.clicked.connect(lambda: self._set_checked(lambda row: False))
        self.btn_odd.clicked.connect(lambda: self._set_checked(lambda row: row % 2 == 0))
        self.btn_even.clicked.connect(lambda: self._set_checked(lambda row: row % 2 == 1))
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_split.clicked.connect(self._on_split_clicked)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.cellClicked.connect(self._on_cell_clicked)
        self._update_status()

    def selected_row_indexes(self) -> list[int]:
        return list(self._selected_rows)

    def _checked_rows(self) -> list[int]:
        checked = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                checked.append(row)
        return checked

    def _set_checked(self, predicate) -> None:
        self.table.blockSignals(True)
        try:
            for row in range(self.table.rowCount()):
                item = self.table.item(row, 0)
                if item is None:
                    continue
                item.setCheckState(Qt.CheckState.Checked if predicate(row) else Qt.CheckState.Unchecked)
        finally:
            self.table.blockSignals(False)
        self._update_status()

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

    def _update_status(self) -> None:
        checked = len(self._checked_rows())
        total = self.table.rowCount()
        ready = 0 < checked < total
        self.btn_split.setEnabled(ready)
        if total == 0:
            self.status_label.setText("This group has no rows to split.")
        elif ready:
            self.status_label.setText(f"{checked} checked, {total - checked} left in the other group.")
        else:
            self.status_label.setText("Check some rows and leave at least one unchecked.")

    def _on_split_clicked(self) -> None:
        checked = self._checked_rows()
        total = self.table.rowCount()
        if not checked or len(checked) == total:
            self._update_status()
            return
        self._selected_rows = checked
        self.accept()
