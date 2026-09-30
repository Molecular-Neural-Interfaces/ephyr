# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from typing import List

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from ephyr import settings
from ephyr.gui._utils import milliseconds_to_readable
from ephyr.gui.qt_ephyr_session_manager_wrapper import QtEphyrSessionManagerWrapper


class OverlaySweepsDialog(QDialog):
    """Pick the sweeps drawn in gray behind the current (black) sweep."""

    def __init__(self, session_manager: QtEphyrSessionManagerWrapper, parent=None):
        super().__init__(parent)
        self._session_manager = session_manager
        self.setWindowTitle("Setup overlay")
        self.resize(360, 520)
        self._build_ui()
        self._populate_rows()
        self._update_state()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        info = QLabel(
            "Selected sweeps are drawn in gray behind the current sweep, "
            "with the same filters and transformations."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self.sweeps_list = QListWidget()
        self.sweeps_list.itemChanged.connect(lambda _item: self._update_state())
        layout.addWidget(self.sweeps_list)

        select_layout = QHBoxLayout()
        self.select_all_btn = QPushButton("Select all")
        self.select_all_btn.clicked.connect(self._on_select_all_clicked)
        select_layout.addWidget(self.select_all_btn)
        self.selection_label = QLabel("")
        select_layout.addWidget(self.selection_label)
        select_layout.addStretch(1)
        layout.addLayout(select_layout)

        self.hint_label = QLabel(
            "Sweeps shorter than the current time window are not drawn."
        )
        self.hint_label.setStyleSheet("color: gray; font-size: 9pt;")
        self.hint_label.setWordWrap(True)
        layout.addWidget(self.hint_label)

        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch(1)
        self.cancel_btn = QPushButton("Cancel")
        self.disable_btn = QPushButton("Disable")
        self.enable_btn = QPushButton("Enable")
        self.cancel_btn.clicked.connect(self.reject)
        self.disable_btn.clicked.connect(self._on_disable_clicked)
        self.enable_btn.clicked.connect(self._on_enable_clicked)
        buttons_layout.addWidget(self.cancel_btn)
        buttons_layout.addWidget(self.disable_btn)
        buttons_layout.addWidget(self.enable_btn)
        layout.addLayout(buttons_layout)

    def _populate_rows(self):
        header = self._session_manager.header
        gui_setup = self._session_manager.gui_setup
        if not header or not gui_setup:
            return

        points_per_sweep = list(header.number_of_points_per_sweep)
        selected = set(gui_setup.overlay_sweep_idxs)
        current_sweep_idx = int(gui_setup.current_sweep_idx)

        self.sweeps_list.blockSignals(True)
        for sweep_idx in range(header.number_of_sweeps):
            label = f"Sweep {sweep_idx + 1}"
            if sweep_idx < len(points_per_sweep):
                sweep_duration_ms = (header.sample_interval_microseconds / 10 ** 3) * points_per_sweep[sweep_idx]
                label += f"  {milliseconds_to_readable(int(round(sweep_duration_ms)))}"
            if sweep_idx == current_sweep_idx:
                label += "  (current)"
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if sweep_idx in selected else Qt.CheckState.Unchecked
            )
            item.setData(Qt.ItemDataRole.UserRole, sweep_idx)
            self.sweeps_list.addItem(item)
        self.sweeps_list.blockSignals(False)

    def _selected_sweep_idxs(self) -> List[int]:
        selected = []
        for row in range(self.sweeps_list.count()):
            item = self.sweeps_list.item(row)
            if item.checkState() == Qt.CheckState.Checked:
                selected.append(int(item.data(Qt.ItemDataRole.UserRole)))
        return selected

    def _update_state(self):
        selected_num = len(self._selected_sweep_idxs())
        all_checked = selected_num == self.sweeps_list.count() and selected_num > 0
        self.select_all_btn.setText("Deselect all" if all_checked else "Select all")
        if selected_num > settings.MAX_OVERLAY_SWEEPS:
            self.selection_label.setText(
                f"{selected_num} selected, only the first {settings.MAX_OVERLAY_SWEEPS} will be used"
            )
            self.selection_label.setStyleSheet("color: #B00020;")
        else:
            self.selection_label.setText(f"{selected_num} selected")
            self.selection_label.setStyleSheet("")
        self.enable_btn.setEnabled(selected_num > 0)

    def _on_select_all_clicked(self):
        check_state = (
            Qt.CheckState.Unchecked
            if self.select_all_btn.text() == "Deselect all"
            else Qt.CheckState.Checked
        )
        self.sweeps_list.blockSignals(True)
        for row in range(self.sweeps_list.count()):
            self.sweeps_list.item(row).setCheckState(check_state)
        self.sweeps_list.blockSignals(False)
        self._update_state()

    def _on_disable_clicked(self):
        self._session_manager.set_overlay_sweep_idxs([])
        self.accept()

    def _on_enable_clicked(self):
        self._session_manager.set_overlay_sweep_idxs(self._selected_sweep_idxs())
        self.accept()
