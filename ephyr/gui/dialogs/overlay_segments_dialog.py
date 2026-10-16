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

from ephyr.gui._utils import milliseconds_to_readable
from ephyr.gui.qt_ephyr_session_manager_wrapper import QtEphyrSessionManagerWrapper


class OverlaySegmentsDialog(QDialog):
    """Pick the display segments drawn in gray behind the current (black) one."""

    def __init__(self, session_manager: QtEphyrSessionManagerWrapper, parent=None):
        super().__init__(parent)
        self._session_manager = session_manager
        self.setWindowTitle("Set overlay")
        self.resize(360, 520)
        self._build_ui()
        self._populate_rows()
        self._update_state()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        info = QLabel(
            "Selected segments are drawn in gray behind the current segment, "
            "with the same filters and transformations."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self.segments_list = QListWidget()
        self.segments_list.itemChanged.connect(lambda _item: self._update_state())
        layout.addWidget(self.segments_list)

        select_layout = QHBoxLayout()
        self.select_all_btn = QPushButton("Select all")
        self.select_all_btn.clicked.connect(self._on_select_all_clicked)
        select_layout.addWidget(self.select_all_btn)
        self.selection_label = QLabel("")
        select_layout.addWidget(self.selection_label)
        select_layout.addStretch(1)
        layout.addLayout(select_layout)

        self.hint_label = QLabel(
            "Segments shorter than the current time window are not drawn."
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
        view = self._session_manager.source_view
        gui_setup = self._session_manager.gui_setup
        if not view or not gui_setup:
            return

        selected = set(gui_setup.overlay_segment_idxs)
        current_segment_idx = int(gui_setup.current_segment_idx)

        self.segments_list.blockSignals(True)
        for segment_idx, segment in enumerate(view.display_segments):
            duration_ms = segment.number_of_samples * 1000.0 / view.sample_rate
            label = f"{segment.label}  {milliseconds_to_readable(int(round(duration_ms)))}"
            if segment_idx == current_segment_idx:
                label += "  (current)"
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if segment_idx in selected else Qt.CheckState.Unchecked
            )
            item.setData(Qt.ItemDataRole.UserRole, segment_idx)
            self.segments_list.addItem(item)
        self.segments_list.blockSignals(False)

    def _selected_segment_idxs(self) -> List[int]:
        selected = []
        for row in range(self.segments_list.count()):
            item = self.segments_list.item(row)
            if item.checkState() == Qt.CheckState.Checked:
                selected.append(int(item.data(Qt.ItemDataRole.UserRole)))
        return selected

    def _update_state(self):
        selected_num = len(self._selected_segment_idxs())
        all_checked = selected_num == self.segments_list.count() and selected_num > 0
        self.select_all_btn.setText("Deselect all" if all_checked else "Select all")
        self.selection_label.setText(f"{selected_num} selected")
        self.enable_btn.setEnabled(selected_num > 0)

    def _on_select_all_clicked(self):
        check_state = (
            Qt.CheckState.Unchecked
            if self.select_all_btn.text() == "Deselect all"
            else Qt.CheckState.Checked
        )
        self.segments_list.blockSignals(True)
        for row in range(self.segments_list.count()):
            self.segments_list.item(row).setCheckState(check_state)
        self.segments_list.blockSignals(False)
        self._update_state()

    def _on_disable_clicked(self):
        self._session_manager.set_overlay_segment_idxs([])
        self.accept()

    def _on_enable_clicked(self):
        self._session_manager.set_overlay_segment_idxs(self._selected_segment_idxs())
        self.accept()
