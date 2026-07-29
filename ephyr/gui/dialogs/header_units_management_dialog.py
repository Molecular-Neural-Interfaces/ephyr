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

from ephyr.core.header import VoltageUnitEnum
from ephyr.gui.qt_ephyr_session_manager_wrapper import QtEphyrSessionManagerWrapper


class HeaderUnitsManagementDialog(QDialog):
    def __init__(self, session_manager: QtEphyrSessionManagerWrapper, parent=None):
        super().__init__(parent)
        self._session_manager = session_manager
        self._row_combos: Dict[int, QComboBox] = {}
        self._units_values = VoltageUnitEnum.values()
        self.setWindowTitle("Header units management")
        self.resize(760, 520)
        self._build_ui()
        self._populate_rows()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        info = QLabel("Set units for channels. Select rows to apply one unit to many channels at once.")
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
        self.bulk_units_combo = QComboBox()
        self.bulk_units_combo.addItems(self._units_values)
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
        units = list(header.channel_info.units or [])
        if len(units) < header.number_of_channels:
            units.extend([VoltageUnitEnum.MICROVOLT.value] * (header.number_of_channels - len(units)))

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

            combo = QComboBox()
            combo.addItems(self._units_values)
            normalized = VoltageUnitEnum.normalize(units[channel_idx]).value
            combo.setCurrentText(normalized)
            self.table.setCellWidget(channel_idx, 2, combo)
            self._row_combos[channel_idx] = combo

    def _on_bulk_set_clicked(self):
        selected_rows = sorted({index.row() for index in self.table.selectedIndexes()})
        if not selected_rows:
            return
        selected_unit = self.bulk_units_combo.currentText()
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
            unit = VoltageUnitEnum.normalize(combo.currentText()).value
            grouped_indexes.setdefault(unit, []).append(row)

        for unit, indexes in grouped_indexes.items():
            self._session_manager.set_header_channel_units(indexes, VoltageUnitEnum.normalize(unit))

        self.accept()
