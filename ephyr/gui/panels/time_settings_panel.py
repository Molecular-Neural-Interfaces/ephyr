# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

from PyQt6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from ephyr import settings
from ephyr.gui._utils import milliseconds_to_readable, sample_rate_to_readable
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
        self.start_point_spinbox.setSingleStep(1000)

        self.current_sweep_spinbox = QSpinBox()
        self.current_sweep_spinbox.setRange(1, 1)
        self.current_sweep_spinbox.setSingleStep(1)
        self.current_sweep_spinbox.setSuffix(" sweep")

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

        self.duration_label = QLabel("Duration to show:")
        self.time_step_label = QLabel("Auto-scroll time step:")
        self.sweep_info_label = QLabel("")
        self.sweep_info_label.setStyleSheet("color: gray; font-size: 9pt;")
        self.sweep_info_label.setWordWrap(True)

        rows = [
            ("Current sweep:", self.current_sweep_spinbox),
            ("Start point index:", self.start_point_spinbox),
            (self.duration_label, self.duration_spinbox),
            (self.time_step_label, self.time_step_spinbox),
            ("Auto-scroll interval:", self.autoscroll_step_interval_spinbox),
        ]
        for label, widget in rows:
            row = QHBoxLayout()
            row.addWidget(QLabel(label) if isinstance(label, str) else label)
            row.addWidget(widget)
            row.addStretch(1)
            layout.addLayout(row)
            if widget is self.current_sweep_spinbox:
                layout.addWidget(self.sweep_info_label)

    def connect_signals(self):
        self.current_sweep_spinbox.valueChanged.connect(
            lambda value: self._session_manager.set_current_sweep_idx(value - 1)
        )
        self.start_point_spinbox.valueChanged.connect(self._session_manager.set_start_point)
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
        self.current_sweep_spinbox.setRange(1, max(1, sweeps_num))
        self.current_sweep_spinbox.setValue(min(max(1, current_sweep_idx + 1), max(1, sweeps_num)))
        self.start_point_spinbox.setValue(gui_setup.start_point)
        self.duration_spinbox.setValue(gui_setup.duration_ms)
        self.time_step_spinbox.setValue(gui_setup.time_step_ms)
        self.autoscroll_step_interval_spinbox.setValue(gui_setup.autoscroll_step_interval_ms)

        for control in controls:
            control.blockSignals(False)
        self._updating = False

        self.duration_label.setText(f"Duration window {milliseconds_to_readable(gui_setup.duration_ms)}")
        self.time_step_label.setText(
            f"Auto-scroll time step {milliseconds_to_readable(gui_setup.time_step_ms)}"
        )
        self._update_sweep_info_label(current_sweep_idx)

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
