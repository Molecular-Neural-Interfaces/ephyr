# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

from enum import Enum
from typing import Optional

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ephyr.core.source_view import NavigationModeEnum
from ephyr.core.workspace import Workspace
from ephyr.gui._utils import milliseconds_to_readable, sample_rate_to_readable
from ephyr.gui.dialogs.overlay_segments_dialog import OverlaySegmentsDialog
from ephyr.gui.qt_ephyr_session_manager_wrapper import QtEphyrSessionManagerWrapper
from ephyr.gui.widgets import FocusWheelComboBox as QComboBox
from ephyr.gui.widgets import FocusWheelDoubleSpinBox as QDoubleSpinBox
from ephyr.gui.widgets import FocusWheelSpinBox as QSpinBox


class WorkspaceLevelEnum(str, Enum):
    CONFIG = "config"
    RECORD = "record"
    SOURCE = "source"


_MODE_LABELS = {
    NavigationModeEnum.CONTINUOUS: "Continuous",
    NavigationModeEnum.SEGMENT: "By segment",
    # NavigationModeEnum.PERIOD_LABEL: "By period label",
}


class RecordingNavigationPanel(QWidget):
    """Config / Record / Source of the workspace and the way the active source is split into segments."""

    config_selected = pyqtSignal(str)
    record_selected = pyqtSignal(str)
    add_requested = pyqtSignal(str)
    remove_requested = pyqtSignal(str)
    rename_requested = pyqtSignal(str)

    def __init__(self, session_manager: QtEphyrSessionManagerWrapper, parent=None):
        super().__init__(parent)
        self._session_manager = session_manager
        self._workspace: Optional[Workspace] = None
        self._config_id: Optional[str] = None
        self._record_id: Optional[str] = None
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

        self.workspace_label = QLabel("")
        self.workspace_label.setStyleSheet("color: gray; font-size: 9pt;")
        self.workspace_label.setWordWrap(True)
        layout.addWidget(self.workspace_label)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(4)
        self.level_combos = {}
        self.level_buttons = {}
        for row, (level, label) in enumerate(((WorkspaceLevelEnum.CONFIG, "Config:"),
                                              (WorkspaceLevelEnum.RECORD, "Record:"),
                                              (WorkspaceLevelEnum.SOURCE, "Source:"),
                                              )):
            combo = QComboBox()
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(12)
            grid.addWidget(QLabel(label), row, 0)
            grid.addWidget(combo, row, 1)
            buttons = {}
            for column, (action, text, tooltip) in enumerate((
                    ("add", "+", f"Add {level.value}"),
                    ("remove", "−", f"Remove {level.value}"),
                    ("rename", "✎", f"Rename {level.value}"))):
                button = QToolButton()
                button.setText(text)
                button.setToolTip(tooltip)
                grid.addWidget(button, row, 2 + column)
                buttons[action] = button
            grid.setColumnStretch(1, 1)
            self.level_combos[level] = combo
            self.level_buttons[level] = buttons
        layout.addLayout(grid)

        self.source_info_label = QLabel("")
        self.source_info_label.setStyleSheet("color: gray; font-size: 9pt;")
        self.source_info_label.setWordWrap(True)
        layout.addWidget(self.source_info_label)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Navigation:"))
        self.mode_combo = QComboBox()
        for mode, label in _MODE_LABELS.items():
            self.mode_combo.addItem(label, mode)
        mode_row.addWidget(self.mode_combo, 1)
        layout.addLayout(mode_row)

        self.period_box = QWidget()
        period_layout = QGridLayout(self.period_box)
        period_layout.setContentsMargins(0, 0, 0, 0)
        self.period_label_combo = QComboBox()
        self.pre_spinbox = QDoubleSpinBox()
        self.post_spinbox = QDoubleSpinBox()
        for spinbox in (self.pre_spinbox, self.post_spinbox):
            spinbox.setRange(0.0, 10 ** 7)
            spinbox.setDecimals(1)
            spinbox.setSuffix(" ms")
            spinbox.setKeyboardTracking(False)
        period_layout.addWidget(QLabel("Period label:"), 0, 0)
        period_layout.addWidget(self.period_label_combo, 0, 1, 1, 3)
        period_layout.addWidget(QLabel("Before:"), 1, 0)
        period_layout.addWidget(self.pre_spinbox, 1, 1)
        period_layout.addWidget(QLabel("After:"), 1, 2)
        period_layout.addWidget(self.post_spinbox, 1, 3)
        layout.addWidget(self.period_box)

        self.segment_box = QWidget()
        row = QHBoxLayout(self.segment_box)
        row.setContentsMargins(0, 0, 0, 0)
        self.segment_caption = QLabel("Segment:")
        self.current_segment_spinbox = QSpinBox()
        self.current_segment_spinbox.setRange(1, 1)
        self.current_segment_spinbox.setSingleStep(1)
        self.segments_count_label = QLabel("")
        self.set_overlay_button = QPushButton("Set overlay")
        row.addWidget(self.segment_caption)
        row.addWidget(self.current_segment_spinbox)
        row.addWidget(self.segments_count_label)
        row.addWidget(self.set_overlay_button)
        row.addStretch(1)
        layout.addWidget(self.segment_box)

        self.segment_info_label = QLabel("")
        self.segment_info_label.setStyleSheet("color: gray; font-size: 9pt;")
        self.segment_info_label.setWordWrap(True)
        layout.addWidget(self.segment_info_label)

    def connect_signals(self):
        self.level_combos[WorkspaceLevelEnum.CONFIG].activated.connect(self._on_config_activated)
        self.level_combos[WorkspaceLevelEnum.RECORD].activated.connect(self._on_record_activated)
        self.level_combos[WorkspaceLevelEnum.SOURCE].activated.connect(self._on_source_activated)
        for level, buttons in self.level_buttons.items():
            buttons["add"].clicked.connect(lambda _=False, lv=level: self.add_requested.emit(lv.value))
            buttons["remove"].clicked.connect(lambda _=False, lv=level: self.remove_requested.emit(lv.value))
            buttons["rename"].clicked.connect(lambda _=False, lv=level: self.rename_requested.emit(lv.value))

        self.mode_combo.activated.connect(self._on_navigation_edited)
        self.period_label_combo.activated.connect(self._on_navigation_edited)
        self.pre_spinbox.valueChanged.connect(self._on_navigation_edited)
        self.post_spinbox.valueChanged.connect(self._on_navigation_edited)
        self.current_segment_spinbox.valueChanged.connect(self._on_segment_edited)
        self.set_overlay_button.clicked.connect(self._on_set_overlay_clicked)

        manager = self._session_manager
        manager.session_loaded.connect(self._sync_controls)
        manager.display_segments_changed.connect(self._sync_controls)
        manager.current_segment_idx_changed.connect(self._sync_controls)
        manager.overlay_segment_idxs_changed.connect(self._sync_overlay_button)
        manager.periods_vocabulary_changed.connect(self._sync_controls)
        manager.active_source_changed.connect(self._sync_controls)

    # ----- workspace levels -----

    def set_workspace(self, workspace: Optional[Workspace], config_id: Optional[str], record_id: Optional[str]):
        self._workspace = workspace
        self._config_id = config_id
        self._record_id = record_id
        self._sync_controls()

    def _fill_combo(self, combo, items, current):
        combo.blockSignals(True)
        combo.clear()
        for item_id, name in items:
            combo.addItem(name, item_id)
        idx = combo.findData(current)
        combo.setCurrentIndex(idx if idx >= 0 else (0 if items and current is None else -1))
        combo.blockSignals(False)

    def _sync_levels(self):
        workspace = self._workspace
        self.workspace_label.setText(f"Workspace: {workspace.name}" if workspace else "No workspace")
        configs = [(config.config_id, config.name) for config in workspace.configs()] if workspace else []
        records = ([(record.record_id, record.name) for record in workspace.records(self._config_id)]
                   if workspace and self._config_id else [])
        config = workspace.config(self._config_id) if workspace and self._config_id else None
        sources = []
        if config is not None and self._record_id:
            record = workspace.record(self._config_id, self._record_id)
            for source in (record.sources if record else []):
                spec = config.source(source.source_id)
                name = spec.name if spec else source.source_id
                if source.source_id == config.main_source_id:
                    name += " (main)"
                sources.append((source.source_id, name))
        self._fill_combo(self.level_combos[WorkspaceLevelEnum.CONFIG], configs, self._config_id)
        self._fill_combo(self.level_combos[WorkspaceLevelEnum.RECORD], records, self._record_id)
        self._fill_combo(self.level_combos[WorkspaceLevelEnum.SOURCE], sources,
                         self._session_manager.active_source_id)

        has_workspace = workspace is not None
        session_active = self._session_manager.session_is_active
        enabled = {
            WorkspaceLevelEnum.CONFIG: (has_workspace, bool(configs)),
            WorkspaceLevelEnum.RECORD: (config is not None, bool(records)),
            WorkspaceLevelEnum.SOURCE: (session_active, bool(sources)),
        }
        for level, (can_add, has_items) in enabled.items():
            self.level_combos[level].setEnabled(has_items)
            self.level_buttons[level]["add"].setEnabled(can_add)
            self.level_buttons[level]["remove"].setEnabled(has_items)
            self.level_buttons[level]["rename"].setEnabled(has_items)
        if config is not None and self._session_manager.active_source_id == config.main_source_id:
            self.level_buttons[WorkspaceLevelEnum.SOURCE]["remove"].setEnabled(False)

    def _on_config_activated(self, index: int):
        config_id = self.level_combos[WorkspaceLevelEnum.CONFIG].itemData(index)
        if config_id and config_id != self._config_id:
            self.config_selected.emit(config_id)
            self._sync_levels()

    def _on_record_activated(self, index: int):
        record_id = self.level_combos[WorkspaceLevelEnum.RECORD].itemData(index)
        if record_id and record_id != self._record_id:
            self.record_selected.emit(record_id)
            self._sync_levels()

    def _on_source_activated(self, index: int):
        source_id = self.level_combos[WorkspaceLevelEnum.SOURCE].itemData(index)
        if source_id and self._session_manager.session_is_active:
            self._session_manager.set_active_source(source_id)

    # ----- segments -----

    def _on_navigation_edited(self, *_args):
        if self._updating or not self._session_manager.session_is_active:
            return
        mode = self.mode_combo.currentData()
        label_id = self.period_label_combo.currentData()
        if mode is NavigationModeEnum.PERIOD_LABEL and label_id is None:
            self._sync_controls()
            return
        self._session_manager.set_navigation(
            mode,
            period_label_id=label_id,
            pre_ms=self.pre_spinbox.value(),
            post_ms=self.post_spinbox.value(),
        )
        self._sync_controls()

    def _on_segment_edited(self, value: int):
        if self._updating:
            return
        self._session_manager.set_current_segment_idx(value - 1)

    def _on_set_overlay_clicked(self):
        if not self._session_manager.gui_setup:
            return
        OverlaySegmentsDialog(self._session_manager, self).exec()

    def _sync_controls(self, *_args):
        if self._updating:
            return
        self._updating = True
        try:
            self._sync_levels()
            self._sync_segments()
        finally:
            self._updating = False
        self._sync_overlay_button()

    def _sync_segments(self):
        gui_setup = self._session_manager.gui_setup
        view = self._session_manager.source_view
        active = gui_setup is not None and view is not None
        for widget in (self.mode_combo, self.period_box, self.segment_box):
            widget.setEnabled(active)
        if not active:
            self.source_info_label.setText("")
            self.segment_info_label.setText("")
            self.period_box.setVisible(False)
            return

        duration_ms = view.total_samples * 1000.0 / view.sample_rate
        self.source_info_label.setText(
            f"{sample_rate_to_readable(view.sample_rate)}  ·  {view.number_of_channels} channels  ·  "
            f"{len(view.physical_segments)} {view.segment_kind.label.lower()}(s)  ·  "
            f"{milliseconds_to_readable(int(round(duration_ms)))}"
        )

        mode = gui_setup.navigation_mode
        self.mode_combo.setCurrentIndex(max(0, self.mode_combo.findData(mode)))
        self.period_label_combo.clear()
        for vocabulary_id, entry in self._session_manager.periods_vocabulary.items():
            self.period_label_combo.addItem(entry.name, vocabulary_id)
        label_idx = self.period_label_combo.findData(gui_setup.period_label_id)
        self.period_label_combo.setCurrentIndex(max(0, label_idx) if self.period_label_combo.count() else -1)
        self.pre_spinbox.setValue(float(gui_setup.pre_ms))
        self.post_spinbox.setValue(float(gui_setup.post_ms))
        self.period_box.setVisible(mode is NavigationModeEnum.PERIOD_LABEL
                                   or self.mode_combo.currentData() is NavigationModeEnum.PERIOD_LABEL)

        count = view.number_of_segments
        self.segment_box.setVisible(mode is not NavigationModeEnum.CONTINUOUS)
        self.segment_caption.setText("Period:" if mode is NavigationModeEnum.PERIOD_LABEL
                                     else f"{view.segment_kind.label}:")
        self.current_segment_spinbox.setEnabled(count > 1)
        self.set_overlay_button.setEnabled(count > 1)
        self.current_segment_spinbox.setRange(1, max(1, count))
        current = int(gui_setup.current_segment_idx)
        self.current_segment_spinbox.setValue(min(max(1, current + 1), max(1, count)))
        self.segments_count_label.setText(f"of {count}")

        if count == 0:
            self.segment_info_label.setText("No periods with this label." if mode is NavigationModeEnum.PERIOD_LABEL
                                            else "")
            return
        segment = view.display_segments[min(current, count - 1)]
        segment_ms = segment.number_of_samples * 1000.0 / view.sample_rate
        start_ms = view.time_mapper.time_of_sample(segment.start_sample)
        self.segment_info_label.setText(
            f"{segment.label}  ·  starts at {milliseconds_to_readable(int(round(start_ms))) or '[0ms]'}  ·  "
            f"duration {milliseconds_to_readable(int(round(segment_ms)))}"
        )

    def _sync_overlay_button(self, *_args):
        overlay_segment_idxs = self._session_manager.overlay_segment_idxs
        self.set_overlay_button.setText(
            f"Set overlay ({len(overlay_segment_idxs)})" if overlay_segment_idxs else "Set overlay"
        )
