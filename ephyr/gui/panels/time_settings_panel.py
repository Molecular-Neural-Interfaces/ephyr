# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from ephyr import settings
from ephyr.gui._utils import milliseconds_to_readable, sample_rate_to_readable
from ephyr.gui.dialogs.overlay_sweeps_dialog import OverlaySweepsDialog
from ephyr.gui.qt_ephyr_session_manager_wrapper import QtEphyrSessionManagerWrapper
from ephyr.gui.widgets import FocusWheelSpinBox as QSpinBox


class TimeSettingsPanel(QWidget):
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

        title = QLabel("Time Settings")
        title.setStyleSheet("font-weight: bold;")
        layout.addWidget(title)

        self.start_point_spinbox = QSpinBox()
        self.start_point_spinbox.setRange(0, settings.MAX_START_POINT)
        self.start_point_spinbox.setSingleStep(1)
        self.start_point_spinbox.setSuffix(" ms")

        self.current_sweep_spinbox = QSpinBox()
        self.current_sweep_spinbox.setRange(1, 1)
        self.current_sweep_spinbox.setSingleStep(1)
        self.current_sweep_spinbox.setSuffix(" sweep")

        self.setup_overlay_button = QPushButton("Setup overlay")

        self.duration_spinbox = QSpinBox()
        self.duration_spinbox.setRange(settings.MIN_DURATION, settings.MAX_DURATION)
        self.duration_spinbox.setSingleStep(100)
        self.duration_spinbox.setSuffix(" ms")

        self.time_step_spinbox = QSpinBox()
        self.time_step_spinbox.setRange(settings.MIN_TIME_STEP, settings.MAX_TIME_STEP)
        self.time_step_spinbox.setSingleStep(100)
        self.time_step_spinbox.setSuffix(" ms")

        self.autoscroll_step_interval_spinbox = QSpinBox()
        self.autoscroll_step_interval_spinbox.setRange(10, settings.MAX_TIME_STEP)
        self.autoscroll_step_interval_spinbox.setSingleStep(50)
        self.autoscroll_step_interval_spinbox.setSuffix(" ms")

        self.start_point_label = QLabel("Start point:")
        self.duration_label = QLabel("Duration to show:")
        self.time_step_label = QLabel("Auto-scroll time step:")
        self.sweep_info_label = QLabel("")
        self.sweep_info_label.setStyleSheet("color: gray; font-size: 9pt;")
        self.sweep_info_label.setWordWrap(True)

        layout.addWidget(self.sweep_info_label)

        rows = [
            ("Current sweep:", self.current_sweep_spinbox),
            (self.start_point_label, self.start_point_spinbox),
            (self.duration_label, self.duration_spinbox),
            (self.time_step_label, self.time_step_spinbox),
            ("Auto-scroll interval:", self.autoscroll_step_interval_spinbox),
        ]
        for label, widget in rows:
            row = QHBoxLayout()
            row.addWidget(QLabel(label) if isinstance(label, str) else label)
            row.addWidget(widget)
            if widget is self.current_sweep_spinbox:
                row.addWidget(self.setup_overlay_button)
            row.addStretch(1)
            layout.addLayout(row)

    def connect_signals(self):
        self.current_sweep_spinbox.valueChanged.connect(
            lambda value: self._session_manager.set_current_sweep_idx(value - 1)
        )
        self.setup_overlay_button.clicked.connect(self._on_setup_overlay_clicked)
        self.start_point_spinbox.valueChanged.connect(self._on_start_point_ms_changed)
        self.duration_spinbox.valueChanged.connect(self._on_duration_changed)
        self.time_step_spinbox.valueChanged.connect(self._session_manager.set_time_step_ms)
        self.autoscroll_step_interval_spinbox.valueChanged.connect(
            self._session_manager.set_autoscroll_step_interval_ms
        )

        self._session_manager.session_loaded.connect(self._sync_time_controls)
        self._session_manager.start_point_changed.connect(self._sync_time_controls)
        self._session_manager.duration_ms_changed.connect(self._sync_time_controls)
        self._session_manager.current_sweep_idx_changed.connect(self._sync_time_controls)
        self._session_manager.time_step_ms_changed.connect(self._sync_time_controls)
        self._session_manager.autoscroll_step_interval_ms_changed.connect(self._sync_time_controls)
        self._session_manager.overlay_sweep_idxs_changed.connect(self._sync_overlay_button)

    def _on_setup_overlay_clicked(self):
        if not self._session_manager.gui_setup:
            return
        OverlaySweepsDialog(self._session_manager, self).exec()

    def _sample_rate(self) -> float:
        header = self._session_manager.header
        if not header:
            return 0.0
        return float(header.sample_rate)

    def _start_ms_from_idx(self, start_point: int) -> int:
        sample_rate = self._sample_rate()
        if sample_rate <= 0:
            return 0
        return int(int(start_point) * 1000.0 / sample_rate)

    def _start_idx_from_ms(self, start_ms: int) -> int:
        sample_rate = self._sample_rate()
        if sample_rate <= 0:
            return 0
        return int(int(start_ms) * sample_rate / 1000.0)

    def _max_start_point_ms(self) -> int:
        gui_setup = self._session_manager.gui_setup
        header = self._session_manager.header
        sample_rate = self._sample_rate()
        if not gui_setup or not header or sample_rate <= 0:
            return settings.MAX_START_POINT
        visible_points = int((int(gui_setup.duration_ms) / 1000.0) * sample_rate)
        points_per_sweep = list(header.number_of_points_per_sweep)
        if not points_per_sweep:
            return 0
        sweep_idx = max(0, min(int(gui_setup.current_sweep_idx), len(points_per_sweep) - 1))
        max_start_idx = max(0, int(points_per_sweep[sweep_idx]) - max(0, visible_points))
        return self._start_ms_from_idx(max_start_idx)

    def _on_start_point_ms_changed(self, start_ms: int):
        if self._updating:
            return
        self._session_manager.set_start_point(self._start_idx_from_ms(start_ms))

    def _on_duration_changed(self, duration_ms: int):
        """Keep the time-window center fixed when duration changes."""
        if self._updating:
            return
        gui_setup = self._session_manager.gui_setup
        header = self._session_manager.header
        if not gui_setup or not header or float(header.sample_rate) <= 0:
            self._session_manager.set_duration_ms(duration_ms)
            return

        old_duration_ms = int(gui_setup.duration_ms)
        old_start = int(gui_setup.start_point)
        sample_rate = float(header.sample_rate)
        center_sample = old_start + int((old_duration_ms / 2000.0) * sample_rate)

        self._session_manager.set_duration_ms(duration_ms)
        new_duration_ms = int(self._session_manager.gui_setup.duration_ms)
        half_visible = int((new_duration_ms / 2000.0) * sample_rate)
        self._session_manager.set_start_point(center_sample - half_visible)

    def _sync_time_controls(self, *_args):
        gui_setup = self._session_manager.gui_setup
        if not gui_setup:
            return

        self._updating = True
        controls = (
            self.current_sweep_spinbox,
            self.start_point_spinbox,
            self.duration_spinbox,
            self.time_step_spinbox,
            self.autoscroll_step_interval_spinbox,
        )
        for control in controls:
            control.blockSignals(True)

        current_sweep_idx = int(gui_setup.current_sweep_idx)
        sweeps_num = int(self._session_manager.header.number_of_sweeps) if self._session_manager.header else 1
        sweeps_are_switchable = sweeps_num > 1
        self.current_sweep_spinbox.setEnabled(sweeps_are_switchable)
        self.setup_overlay_button.setEnabled(sweeps_are_switchable)
        self.current_sweep_spinbox.setRange(1, max(1, sweeps_num))
        self.current_sweep_spinbox.setValue(min(max(1, current_sweep_idx + 1), max(1, sweeps_num)))
        self.start_point_spinbox.setRange(0, self._max_start_point_ms())
        self.start_point_spinbox.setValue(self._start_ms_from_idx(gui_setup.start_point))
        self.duration_spinbox.setValue(gui_setup.duration_ms)
        self.time_step_spinbox.setValue(gui_setup.time_step_ms)
        self.autoscroll_step_interval_spinbox.setValue(gui_setup.autoscroll_step_interval_ms)

        for control in controls:
            control.blockSignals(False)
        self._updating = False

        start_ms = self._start_ms_from_idx(gui_setup.start_point)
        self.start_point_label.setText(f"Start point {milliseconds_to_readable(start_ms)}")
        self.duration_label.setText(f"Duration window {milliseconds_to_readable(gui_setup.duration_ms)}")
        self.time_step_label.setText(
            f"Auto-scroll time step {milliseconds_to_readable(gui_setup.time_step_ms)}"
        )
        self._update_sweep_info_label(current_sweep_idx)
        self._sync_overlay_button()

    def _sync_overlay_button(self, *_args):
        overlay_sweep_idxs = self._session_manager.overlay_sweep_idxs
        self.setup_overlay_button.setText(
            f"Setup overlay ({len(overlay_sweep_idxs)})" if overlay_sweep_idxs else "Setup overlay"
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
