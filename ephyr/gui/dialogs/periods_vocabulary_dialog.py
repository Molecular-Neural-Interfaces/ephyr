# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from typing import Dict, List, Optional

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
)

from ephyr.core.ephyr_session import Period, PeriodVocabularyEntry
from ephyr.gui._utils import pick_saturated_color
from ephyr.gui.dialogs.merge_vocabulary_dialog import MergeGroupOption, MergeVocabularyDialog
from ephyr.gui.dialogs.split_annotations_dialog import SplitAnnotationsDialog
from ephyr.gui.qt_ephyr_session_manager_wrapper import QtEphyrSessionManagerWrapper
from ephyr.gui.vocabulary_names import allocate_unique_vocabulary_name


class PeriodsVocabularyDialog(QDialog):
    """Dialog that manages period vocabulary entries and lets user select one."""

    def __init__(self, session_manager: QtEphyrSessionManagerWrapper, parent=None, *, allow_add: bool = True):
        super().__init__(parent)
        self.setWindowTitle("Periods")
        self.resize(700, 360)

        self._session_manager = session_manager
        self._allow_add = allow_add
        self._selected_period_vocabulary_id: Optional[int] = None
        self._pending_selection_id: Optional[int] = None
        self._is_updating_table = False
        self._group_counts: Dict[int, int] = {}

        self._build_ui()
        self._connect_signals()
        self._populate_table(self._session_manager.periods_vocabulary)

    def _build_ui(self):
        layout = QVBoxLayout(self)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Visible", "ID", "Name", "Color"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.DoubleClicked | QTableWidget.EditTrigger.SelectedClicked)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)

        buttons_layout = QHBoxLayout()
        self.btn_add = QPushButton("New period name")
        self.btn_merge = QPushButton("Merge")
        self.btn_merge.setToolTip("Merge period groups into one")
        self.btn_remove = QPushButton("Remove")
        self.btn_select = QPushButton("Add")
        self.btn_split = QPushButton("Split")
        self.btn_split.setToolTip("Split the selected group into two")
        buttons_layout.addWidget(self.btn_add)
        buttons_layout.addWidget(self.btn_merge)
        buttons_layout.addWidget(self.btn_remove)
        buttons_layout.addWidget(self.btn_select)
        buttons_layout.addWidget(self.btn_split)
        layout.addLayout(buttons_layout)

        self._update_buttons_state()

    def _connect_signals(self):
        self.btn_add.clicked.connect(self._on_add_clicked)
        self.btn_merge.clicked.connect(self._on_merge_clicked)
        self.btn_remove.clicked.connect(self._on_remove_clicked)
        self.btn_select.clicked.connect(self._on_select_clicked)
        self.btn_split.clicked.connect(self._on_split_clicked)
        self.table.itemSelectionChanged.connect(self._update_buttons_state)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)

        self._session_manager.periods_vocabulary_changed.connect(self._populate_table)

    def _populate_table(self, vocabulary: Dict[int, PeriodVocabularyEntry]):
        selected_id = self._current_selected_period_vocabulary_id()
        target_selection_id = self._pending_selection_id if self._pending_selection_id is not None else selected_id

        counts: Dict[int, int] = {}
        for period in self._session_manager.periods:
            counts[period.period_name_id] = counts.get(period.period_name_id, 0) + 1
        self._group_counts = counts

        self._is_updating_table = True
        self.table.setRowCount(0)
        for row_idx, (period_vocabulary_id, entry) in enumerate(sorted(vocabulary.items(), key=lambda item: item[0])):
            self.table.insertRow(row_idx)

            visible_item = QTableWidgetItem()
            visible_item.setFlags(
                Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable
            )
            visible_item.setCheckState(
                Qt.CheckState.Checked if entry.is_visible else Qt.CheckState.Unchecked
            )
            self.table.setItem(row_idx, 0, visible_item)

            id_item = QTableWidgetItem(str(period_vocabulary_id))
            id_item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(row_idx, 1, id_item)

            name_item = QTableWidgetItem(entry.name)
            name_item.setFlags(
                Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsEditable
            )
            self.table.setItem(row_idx, 2, name_item)

            color_value = entry.color or "#00AA55"
            color_item = QTableWidgetItem(color_value.upper())
            color_item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
            color = QColor(color_value)
            if color.isValid():
                color_item.setBackground(color)
            self.table.setItem(row_idx, 3, color_item)

            if target_selection_id is not None and period_vocabulary_id == target_selection_id:
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
        if self._is_updating_table or item.column() not in (0, 2):
            return

        period_vocabulary_id_item = self.table.item(item.row(), 1)
        if not period_vocabulary_id_item:
            return

        period_vocabulary_id = int(period_vocabulary_id_item.text())
        if item.column() == 0:
            self._session_manager.set_period_vocabulary_visibility(
                period_vocabulary_id,
                item.checkState() == Qt.CheckState.Checked,
            )
            return

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
        if column != 3:
            return
        id_item = self.table.item(row, 1)
        color_item = self.table.item(row, 3)
        if not id_item or not color_item:
            return
        period_vocabulary_id = int(id_item.text())
        initial_color = QColor(color_item.text())
        selected = pick_saturated_color(initial_color, self, "Select period color")
        if not selected.isValid():
            return
        self._session_manager.set_period_vocabulary_color(period_vocabulary_id, selected.name())

    def _current_selected_period_vocabulary_id(self) -> Optional[int]:
        selected_ranges = self.table.selectedRanges()
        if not selected_ranges:
            return None

        row = selected_ranges[0].topRow()
        id_item = self.table.item(row, 1)
        if not id_item:
            return None
        return int(id_item.text())

    def _update_buttons_state(self):
        selected_id = self._current_selected_period_vocabulary_id()
        has_selection = selected_id is not None
        self.btn_remove.setEnabled(has_selection)
        self.btn_select.setEnabled(self._allow_add and has_selection)
        self.btn_split.setEnabled(has_selection and self._group_counts.get(selected_id, 0) >= 2)
        self.btn_merge.setEnabled(len(self._session_manager.periods_vocabulary) >= 2)

    def _on_split_clicked(self):
        selected_id = self._current_selected_period_vocabulary_id()
        if selected_id is None:
            return
        entry = self._session_manager.periods_vocabulary.get(selected_id)
        if entry is None:
            return
        periods = sorted(
            (period for period in self._session_manager.periods if period.period_name_id == selected_id),
            key=lambda period: (period.start_t_ms, period.id),
        )
        if len(periods) < 2:
            QMessageBox.information(self, "Split", "Select a group with at least two periods.")
            return

        taken = {
            other.name
            for vocabulary_id, other in self._session_manager.periods_vocabulary.items()
            if vocabulary_id != selected_id
        }
        selected_name = allocate_unique_vocabulary_name(taken, f"{entry.name}1")
        other_name = allocate_unique_vocabulary_name(taken, f"{entry.name}2")
        columns, rows = _period_split_table(periods)
        dialog = SplitAnnotationsDialog(
            title=f"Split periods: {entry.name}",
            intro=(
                f'Rows are in start-time order. Checked rows become "{selected_name}". '
                f'Unchecked rows become "{other_name}".'
            ),
            columns=columns,
            rows=rows,
            parent=self,
        )
        if not dialog.exec():
            return
        selected_period_ids = [periods[index].id for index in dialog.selected_row_indexes()]
        try:
            created = self._session_manager.split_period_vocabulary(
                selected_id, selected_period_ids, selected_name, other_name
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Split", str(exc))
            return
        if created is not None:
            self._select_vocabulary_id(created[0])

    def _on_merge_clicked(self):
        vocabulary = self._session_manager.periods_vocabulary
        if len(vocabulary) < 2:
            QMessageBox.information(self, "Merge", "At least two period groups are needed.")
            return
        groups = [
            MergeGroupOption(
                group_id=vocabulary_id,
                name=entry.name,
                color=entry.color,
                count=self._group_counts.get(vocabulary_id, 0),
            )
            for vocabulary_id, entry in sorted(vocabulary.items())
        ]
        dialog = MergeVocabularyDialog(title="Merge periods", groups=groups, parent=self)
        if not dialog.exec():
            return
        vocabulary_ids, name = dialog.selection()
        try:
            created = self._session_manager.merge_period_vocabulary(vocabulary_ids, name)
        except ValueError as exc:
            QMessageBox.warning(self, "Merge", str(exc))
            return
        if created is not None:
            self._select_vocabulary_id(created)

    def _select_vocabulary_id(self, vocabulary_id: int):
        for row in range(self.table.rowCount()):
            id_item = self.table.item(row, 1)
            if id_item is not None and id_item.text() == str(vocabulary_id):
                self.table.selectRow(row)
                return

    def get_selected_period_vocabulary_id(self) -> Optional[int]:
        return self._selected_period_vocabulary_id


def _period_split_table(periods: List[Period]) -> tuple[List[str], List[List[str]]]:
    extra_keys: List[str] = []
    for period in periods:
        for key in period.extra:
            if key not in extra_keys:
                extra_keys.append(key)
    columns = ["ID", "Start (ms)", "End (ms)", "Duration (ms)", "Source", "Channel", "Value", *extra_keys]
    rows: List[List[str]] = []
    for period in periods:
        rows.append([
            str(period.id),
            f"{period.start_t_ms:.3f}",
            f"{period.end_t_ms:.3f}",
            f"{period.end_t_ms - period.start_t_ms:.3f}",
            period.source_id or "",
            "" if period.channel is None else str(period.channel),
            period.value or "",
            *[str(period.extra.get(key, "")) for key in extra_keys],
        ])
    return columns, rows

