from __future__ import annotations

from typing import Dict, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QMessageBox,
    QColorDialog,
)

from weegit.core.weegit_session import PeriodVocabularyEntry
from weegit.gui.qt_weegit_session_manager_wrapper import QtWeegitSessionManagerWrapper


class PeriodsVocabularyDialog(QDialog):
    """Dialog that manages period vocabulary entries and lets user select one."""

    def __init__(self, session_manager: QtWeegitSessionManagerWrapper, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Periods")
        self.resize(360, 320)

        self._session_manager = session_manager
        self._selected_period_vocabulary_id: Optional[int] = None
        self._pending_selection_id: Optional[int] = None
        self._is_updating_table = False

        self._build_ui()
        self._connect_signals()
        self._populate_table(self._session_manager.periods_vocabulary)

    def _build_ui(self):
        layout = QVBoxLayout(self)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["ID", "Name", "Color"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.DoubleClicked | QTableWidget.EditTrigger.SelectedClicked)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)

        buttons_layout = QHBoxLayout()
        self.btn_add = QPushButton("Add")
        self.btn_remove = QPushButton("Remove")
        self.btn_select = QPushButton("Select")
        buttons_layout.addWidget(self.btn_add)
        buttons_layout.addWidget(self.btn_remove)
        buttons_layout.addWidget(self.btn_select)
        layout.addLayout(buttons_layout)

        self._update_buttons_state()

    def _connect_signals(self):
        self.btn_add.clicked.connect(self._on_add_clicked)
        self.btn_remove.clicked.connect(self._on_remove_clicked)
        self.btn_select.clicked.connect(self._on_select_clicked)
        self.table.itemSelectionChanged.connect(self._update_buttons_state)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)

        self._session_manager.periods_vocabulary_changed.connect(self._populate_table)

    def _populate_table(self, vocabulary: Dict[int, PeriodVocabularyEntry]):
        self._is_updating_table = True
        self.table.setRowCount(0)
        for row_idx, (period_vocabulary_id, entry) in enumerate(sorted(vocabulary.items(), key=lambda item: item[0])):
            self.table.insertRow(row_idx)

            id_item = QTableWidgetItem(str(period_vocabulary_id))
            id_item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(row_idx, 0, id_item)

            name_item = QTableWidgetItem(entry.name)
            name_item.setFlags(
                Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsEditable
            )
            self.table.setItem(row_idx, 1, name_item)

            color_value = entry.color or "#00AA55"
            color_item = QTableWidgetItem(color_value.upper())
            color_item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
            color = QColor(color_value)
            if color.isValid():
                color_item.setBackground(color)
            self.table.setItem(row_idx, 2, color_item)

            if self._pending_selection_id is not None and period_vocabulary_id == self._pending_selection_id:
                self.table.selectRow(row_idx)

        self._pending_selection_id = None
        self._is_updating_table = False
        self._update_buttons_state()

    def _on_add_clicked(self):
        try:
            new_id = self._session_manager.add_period_vocabulary()
        except ValueError as exc:
            QMessageBox.warning(self, "Warning", str(exc))
            return

        self._pending_selection_id = new_id

    def _on_remove_clicked(self):
        selected_id = self._current_selected_period_vocabulary_id()
        if selected_id is None:
            return

        try:
            self._session_manager.remove_period_vocabulary(selected_id)
        except ValueError as exc:
            QMessageBox.warning(self, "Warning", str(exc))

    def _on_select_clicked(self):
        selected_id = self._current_selected_period_vocabulary_id()
        if selected_id is None:
            QMessageBox.information(self, "Select period", "Please select a period from the list.")
            return

        self._selected_period_vocabulary_id = selected_id
        self.accept()

    def _on_item_changed(self, item: QTableWidgetItem):
        if self._is_updating_table or item.column() != 1:
            return

        period_vocabulary_id_item = self.table.item(item.row(), 0)
        if not period_vocabulary_id_item:
            return

        period_vocabulary_id = int(period_vocabulary_id_item.text())
        new_name = item.text().strip()
        try:
            self._session_manager.set_period_vocabulary_name(period_vocabulary_id, new_name)
        except ValueError as exc:
            QMessageBox.warning(self, "Warning", str(exc))
            self._is_updating_table = True
            current_entry = self._session_manager.periods_vocabulary.get(period_vocabulary_id)
            item.setText(current_entry.name if current_entry else new_name)
            self._is_updating_table = False

    def _on_cell_double_clicked(self, row: int, column: int):
        if column != 2:
            return
        id_item = self.table.item(row, 0)
        color_item = self.table.item(row, 2)
        if not id_item or not color_item:
            return
        period_vocabulary_id = int(id_item.text())
        initial_color = QColor(color_item.text())
        selected = QColorDialog.getColor(initial_color, self, "Select period color")
        if not selected.isValid():
            return
        self._session_manager.set_period_vocabulary_color(period_vocabulary_id, selected.name())

    def _current_selected_period_vocabulary_id(self) -> Optional[int]:
        selected_ranges = self.table.selectedRanges()
        if not selected_ranges:
            return None

        row = selected_ranges[0].topRow()
        id_item = self.table.item(row, 0)
        if not id_item:
            return None
        return int(id_item.text())

    def _update_buttons_state(self):
        has_selection = self._current_selected_period_vocabulary_id() is not None
        self.btn_remove.setEnabled(has_selection)
        self.btn_select.setEnabled(has_selection)

    def get_selected_period_vocabulary_id(self) -> Optional[int]:
        return self._selected_period_vocabulary_id

