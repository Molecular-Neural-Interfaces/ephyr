# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from ephyr.gui._utils import milliseconds_to_readable, sample_rate_to_readable
from ephyr.gui.dialogs.overlay_sweeps_dialog import OverlaySweepsDialog
from ephyr.gui.qt_ephyr_session_manager_wrapper import QtEphyrSessionManagerWrapper
from ephyr.gui.widgets import FocusWheelSpinBox as QSpinBox


class RecordingNavigationPanel(QWidget):
    def __init__(self, session_manager: QtEphyrSessionManagerWrapper, parent=None):
        super().__init__(parent)
        self._session_manager = session_manager
        self._updating = False
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setup_ui()
        self.connect_signals()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(8)

        title = QLabel("Recording navigation")
        title.setStyleSheet("font-weight: bold;")
        layout.addWidget(title)

        self.sweep_info_label = QLabel("")
        self.sweep_info_label.setStyleSheet("color: gray; font-size: 9pt;")
        self.sweep_info_label.setWordWrap(True)
        layout.addWidget(self.sweep_info_label)

        self.current_sweep_spinbox = QSpinBox()
        self.current_sweep_spinbox.setRange(1, 1)
        self.current_sweep_spinbox.setSingleStep(1)
        self.current_sweep_spinbox.setSuffix(" sweep")
        self.set_overlay_button = QPushButton("Set overlay")

        row_widget = QWidget()
        row = QHBoxLayout(row_widget)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QLabel("Current sweep:"))
        row.addWidget(self.current_sweep_spinbox)
        row.addWidget(self.set_overlay_button)
        row.addStretch(1)
        layout.addWidget(row_widget)

    def connect_signals(self):
        self.current_sweep_spinbox.valueChanged.connect(
            lambda value: self._session_manager.set_current_sweep_idx(value - 1)
        )
        self.set_overlay_button.clicked.connect(self._on_set_overlay_clicked)

        self._session_manager.session_loaded.connect(self._sync_controls)
        self._session_manager.current_sweep_idx_changed.connect(self._sync_controls)
        self._session_manager.overlay_sweep_idxs_changed.connect(self._sync_overlay_button)

    def _on_set_overlay_clicked(self):
        if not self._session_manager.gui_setup:
            return
        OverlaySweepsDialog(self._session_manager, self).exec()

    def _sync_controls(self, *_args):
        if self._updating:
            return
        gui_setup = self._session_manager.gui_setup
        if not gui_setup:
            return

        self._updating = True
        self.current_sweep_spinbox.blockSignals(True)

        current_sweep_idx = int(gui_setup.current_sweep_idx)
        sweeps_num = int(self._session_manager.header.number_of_sweeps) if self._session_manager.header else 1
        sweeps_are_switchable = sweeps_num > 1
        self.current_sweep_spinbox.setEnabled(sweeps_are_switchable)
        self.set_overlay_button.setEnabled(sweeps_are_switchable)
        self.current_sweep_spinbox.setRange(1, max(1, sweeps_num))
        self.current_sweep_spinbox.setValue(min(max(1, current_sweep_idx + 1), max(1, sweeps_num)))

        self.current_sweep_spinbox.blockSignals(False)
        self._updating = False
        self._update_sweep_info_label(current_sweep_idx)
        self._sync_overlay_button()

    def _sync_overlay_button(self, *_args):
        overlay_sweep_idxs = self._session_manager.overlay_sweep_idxs
        self.set_overlay_button.setText(
            f"Set overlay ({len(overlay_sweep_idxs)})" if overlay_sweep_idxs else "Set overlay"
        )

    def _update_sweep_info_label(self, current_sweep_idx: int):
        header = self._session_manager.header
        if not header or float(header.sample_rate) <= 0:
            self.sweep_info_label.setText("")
            return
        points_per_sweep = list(header.number_of_points_per_sweep)
        if not points_per_sweep:
            self.sweep_info_label.setText("")
            return
        sweep_idx = max(0, min(current_sweep_idx, len(points_per_sweep) - 1))
        sweep_duration_ms = (header.sample_interval_microseconds / 10 ** 3) * points_per_sweep[sweep_idx]
        sample_rate_text = sample_rate_to_readable(float(header.sample_rate))
        duration_text = milliseconds_to_readable(int(round(sweep_duration_ms)))
        self.sweep_info_label.setText(
            f"Sample rate {sample_rate_text}  Sweep duration {duration_text}"
        )
