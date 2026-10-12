# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from typing import List, Dict

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QComboBox,
    QLabel,
)

from ephyr.core.header import PhysicalQuantityEnum, SignalUnitEnum, canonical_unit_label
from ephyr.gui.qt_ephyr_session_manager_wrapper import QtEphyrSessionManagerWrapper


def _make_units_combo(current_unit: str = "") -> QComboBox:
    """Editable combo with known units grouped by quantity; arbitrary labels can be typed in."""
    combo = QComboBox()
    combo.setEditable(True)
    combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
    for quantity in (PhysicalQuantityEnum.VOLTAGE, PhysicalQuantityEnum.CURRENT):
        if combo.count():
            combo.insertSeparator(combo.count())
        for unit in SignalUnitEnum.of_quantity(quantity):
            combo.addItem(unit.value)
    current = canonical_unit_label(current_unit)
    if current and combo.findText(current) < 0:
        combo.insertSeparator(combo.count())
        combo.addItem(current)
    combo.setCurrentText(current)
    return combo


class HeaderUnitsManagementDialog(QDialog):
    def __init__(self, session_manager: QtEphyrSessionManagerWrapper, parent=None):
        super().__init__(parent)
        self._session_manager = session_manager
        self._row_combos: Dict[int, QComboBox] = {}
        self.setWindowTitle("Header units management")
        self.resize(760, 520)
        self._build_ui()
        self._populate_rows()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        info = QLabel(
            "Set units for channels. Select rows to apply one unit to many channels at once. "
            "Changing a unit only relabels the channel: signal values are not rescaled."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Index", "Channel", "Units"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)

        bulk_layout = QHBoxLayout()
        bulk_layout.addWidget(QLabel("Selected rows unit:"))
        self.bulk_units_combo = _make_units_combo(SignalUnitEnum.MICROVOLT.value)
        bulk_layout.addWidget(self.bulk_units_combo)
        self.bulk_set_btn = QPushButton("Set")
        self.bulk_set_btn.clicked.connect(self._on_bulk_set_clicked)
        bulk_layout.addWidget(self.bulk_set_btn)
        bulk_layout.addStretch(1)
        layout.addLayout(bulk_layout)

        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch(1)
        self.cancel_btn = QPushButton("Cancel")
        self.save_btn = QPushButton("Save changes")
        self.cancel_btn.clicked.connect(self.reject)
        self.save_btn.clicked.connect(self._on_save_clicked)
        buttons_layout.addWidget(self.cancel_btn)
        buttons_layout.addWidget(self.save_btn)
        layout.addLayout(buttons_layout)

    def _populate_rows(self):
        header = self._session_manager.header
        if not header:
            return
        channel_names = list(header.channel_info.name or [])

        self.table.setRowCount(0)
        self._row_combos.clear()
        for channel_idx in range(header.number_of_channels):
            self.table.insertRow(channel_idx)

            index_item = QTableWidgetItem(str(channel_idx))
            index_item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(channel_idx, 0, index_item)

            channel_name = channel_names[channel_idx] if channel_idx < len(channel_names) else f"Channel {channel_idx}"
            name_item = QTableWidgetItem(channel_name)
            name_item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(channel_idx, 1, name_item)

            combo = _make_units_combo(header.channel_unit_label(channel_idx))
            self.table.setCellWidget(channel_idx, 2, combo)
            self._row_combos[channel_idx] = combo

    def _on_bulk_set_clicked(self):
        selected_rows = sorted({index.row() for index in self.table.selectedIndexes()})
        if not selected_rows:
            return
        selected_unit = canonical_unit_label(self.bulk_units_combo.currentText())
        for row in selected_rows:
            combo = self._row_combos.get(row)
            if combo is None:
                continue
            combo.setCurrentText(selected_unit)

    def _on_save_clicked(self):
        grouped_indexes: Dict[str, List[int]] = {}
        for row in range(self.table.rowCount()):
            combo = self._row_combos.get(row)
            if combo is None:
                continue
            unit = canonical_unit_label(combo.currentText())
            grouped_indexes.setdefault(unit, []).append(row)

        for unit, indexes in grouped_indexes.items():
            self._session_manager.set_header_channel_units(indexes, unit)

        self.accept()
