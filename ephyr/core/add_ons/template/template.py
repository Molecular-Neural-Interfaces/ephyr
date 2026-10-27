# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

"""Example add-on: one class is runnable, viewable, and a transformation.

Run stores an offset and a sine for selected channels of selected groups.
Transform adds that sine to those channels. View draws the same sine on them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, FrozenSet, List, NamedTuple, Optional, Tuple

import numpy as np
from PyQt6.QtCore import Qt, QPointF, QRect
from PyQt6.QtGui import QColor, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import (
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ephyr.core.add_ons.base import BaseAddOn, ViewEntitiesZIndexEnum
from ephyr.core.add_ons.common.mixin import EphyrAddOnMixin
from ephyr.logger import ephyr_logger


_DEFAULT_OFFSET = 0.0
_DEFAULT_AMPLITUDE = 50.0
_DEFAULT_FREQUENCY_HZ = 1.0
_DEFAULT_PHASE_DEG = 0.0
_SINE_COLOR = QColor(0, 110, 220)


class _SineSettings(NamedTuple):
    channels: FrozenSet[int]
    offset: float
    amplitude: float
    frequency_hz: float
    phase_deg: float


class ExampleAddOn(EphyrAddOnMixin, BaseAddOn):
    """Add ``offset + amplitude * sin(2π f t + phase)`` to selected channels.

    ``t`` is seconds from the start of the displayed window. The sine is added
    before channel-group filters. View draws that same curve on each selected
    channel cell, in the channel's own scale.
    """

    Z_INDEX = ViewEntitiesZIndexEnum.TRACES.value + 1
    TRANSFORMATION = True
    VIEWABLE = True
    RUNNABLE = True
    REQUIRED_SAMPLE_RATE = 0.0

    def __init__(self):
        self._data_dir: Optional[Path] = None
        self._cached_dir: Optional[Path] = None
        self._cached_settings: Optional[_SineSettings] = None

    # ---- Saved settings ----
    def _resolve_data_dir(self, add_on_data_dir: Optional[Path] = None) -> Optional[Path]:
        # ``transform`` has no data-dir argument. Run remembers the directory, and
        # the session stamps ``_ephyr_data_dir`` before the display pipeline runs.
        if add_on_data_dir is not None:
            self._data_dir = Path(add_on_data_dir)
            return self._data_dir
        if self._data_dir is not None:
            return Path(self._data_dir)
        stamped = getattr(self, "_ephyr_data_dir", None)
        if stamped is None:
            return None
        return Path(stamped)

    @staticmethod
    def _as_float(value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    def _settings_from_params(self, params: Dict[str, Any]) -> _SineSettings:
        channels = []
        for item in params.get("channel_indexes") or []:
            try:
                channels.append(int(item))
            except (TypeError, ValueError):
                continue
        return _SineSettings(
            channels=frozenset(channels),
            offset=self._as_float(params.get("offset"), _DEFAULT_OFFSET),
            amplitude=self._as_float(params.get("amplitude"), _DEFAULT_AMPLITUDE),
            frequency_hz=max(0.0, self._as_float(params.get("frequency_hz"), _DEFAULT_FREQUENCY_HZ)),
            phase_deg=self._as_float(params.get("phase_deg"), _DEFAULT_PHASE_DEG),
        )

    def _settings(self, add_on_data_dir: Optional[Path] = None) -> _SineSettings:
        data_dir = self._resolve_data_dir(add_on_data_dir)
        if data_dir is None:
            return self._settings_from_params({})
        if self._cached_dir == data_dir and self._cached_settings is not None:
            return self._cached_settings
        try:
            params = self.load_params(data_dir)
        except Exception as exc:
            ephyr_logger().debug(str(exc))
            params = {}
        settings = self._settings_from_params(params if isinstance(params, dict) else {})
        self._cached_dir = data_dir
        self._cached_settings = settings
        return settings

    def _remember(self, add_on_data_dir: Path, params: Dict[str, Any]) -> None:
        data_dir = Path(add_on_data_dir)
        self._data_dir = data_dir
        self.save_params(data_dir, params)
        self._cached_dir = data_dir
        self._cached_settings = self._settings_from_params(params)

    @staticmethod
    def sine_values(
        n: int,
        sample_rate: float,
        offset: float,
        amplitude: float,
        frequency_hz: float,
        phase_deg: float,
    ) -> np.ndarray:
        """Sine samples. ``sample_rate`` is Hz of this array, ``t = 0`` at sample 0."""
        length = max(0, int(n))
        if length == 0:
            return np.zeros(0, dtype=np.float64)
        phase = np.deg2rad(float(phase_deg))
        if sample_rate <= 0.0 or frequency_hz == 0.0:
            value = float(offset) + float(amplitude) * np.sin(phase)
            return np.full(length, value, dtype=np.float64)
        t = np.arange(length, dtype=np.float64) / float(sample_rate)
        return (
            float(offset) + float(amplitude) * np.sin(2.0 * np.pi * float(frequency_hz) * t + phase)
        ).astype(np.float64, copy=False)

    # ---- Run ----
    def _ask_parameters(self, session_manager, add_on_data_dir: Path) -> Optional[Dict[str, Any]]:
        title = "Sine offset"
        if self.ensure_channel_groups(session_manager, title) is None:
            return None
        channel_groups = session_manager.user_session.gui_setup.channels_groups
        source_view = session_manager.source_view
        params = self.load_params(add_on_data_dir)

        dialog = QDialog()
        dialog.setWindowTitle(title)
        dialog.setMinimumSize(560, 640)
        outer = QVBoxLayout(dialog)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        form = QFormLayout(body)

        saved_group_keys = [str(key) for key in (params.get("group_keys") or []) if key]
        groups_list = self.build_groups_multi_selector(
            form,
            channel_groups,
            preferred_keys=saved_group_keys,
            label="Channel groups:",
            non_aux_only=False,
        )
        groups_list.setMinimumHeight(120)
        if saved_group_keys and not self.selected_group_keys(groups_list):
            groups_list.blockSignals(True)
            for row in range(groups_list.count()):
                item = groups_list.item(row)
                if item is not None:
                    item.setSelected(True)
            groups_list.blockSignals(False)

        channels_list = QListWidget()
        channels_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        channels_list.setMinimumHeight(160)
        form.addRow("Channels:", channels_list)

        saved_channels = []
        for item in params.get("channel_indexes") or []:
            try:
                saved_channels.append(int(item))
            except (TypeError, ValueError):
                continue
        fill_state = {"first": True, "preferred": set(saved_channels)}

        def rebuild_channels() -> None:
            previous = set(self.selected_channels(channels_list))
            had_rows = channels_list.count() > 0
            keys = self.selected_group_keys(groups_list)
            selected_groups = self.resolve_groups_by_keys(
                channel_groups,
                keys,
                non_aux_only=False,
                fallback_all=False,
            )
            indexes: List[int] = []
            seen = set()
            for group in selected_groups:
                for channel_idx in getattr(group, "channel_indexes", []) or []:
                    channel_idx = int(channel_idx)
                    if channel_idx in seen:
                        continue
                    seen.add(channel_idx)
                    indexes.append(channel_idx)

            if not had_rows and fill_state["first"]:
                wanted = set(fill_state["preferred"])
                select_all = not wanted
            else:
                wanted = previous
                select_all = not previous
            fill_state["first"] = False

            channels_list.blockSignals(True)
            channels_list.clear()
            matched = False
            for channel_idx in indexes:
                name = self.channel_name(source_view, channel_idx)
                row = QListWidgetItem(f"{channel_idx} [{name}]")
                row.setData(Qt.ItemDataRole.UserRole, channel_idx)
                selected = select_all or channel_idx in wanted
                row.setSelected(selected)
                if selected:
                    matched = True
                channels_list.addItem(row)
            if wanted and not matched:
                for row_idx in range(channels_list.count()):
                    item = channels_list.item(row_idx)
                    if item is not None:
                        item.setSelected(True)
            channels_list.blockSignals(False)

        groups_list.itemSelectionChanged.connect(rebuild_channels)
        rebuild_channels()

        def select_channels(predicate) -> None:
            for row_idx in range(channels_list.count()):
                item = channels_list.item(row_idx)
                if item is None:
                    continue
                item.setSelected(bool(predicate(row_idx)))

        button_row = QHBoxLayout()
        btn_all = QPushButton("Select all")
        btn_odd = QPushButton("Select odd")
        btn_even = QPushButton("Select even")
        btn_all.clicked.connect(lambda: select_channels(lambda _row: True))
        btn_odd.clicked.connect(lambda: select_channels(lambda row: row % 2 == 0))
        btn_even.clicked.connect(lambda: select_channels(lambda row: row % 2 == 1))
        button_row.addWidget(btn_all)
        button_row.addWidget(btn_odd)
        button_row.addWidget(btn_even)
        button_row.addStretch(1)
        form.addRow("", button_row)

        hint = QLabel("Offset and amplitude use the channel unit, the same unit the trace is drawn in.")
        hint.setWordWrap(True)
        form.addRow("", hint)

        offset_spin = QDoubleSpinBox()
        offset_spin.setRange(-1_000_000.0, 1_000_000.0)
        offset_spin.setDecimals(3)
        offset_spin.setSingleStep(1.0)
        offset_spin.setValue(self._as_float(params.get("offset"), _DEFAULT_OFFSET))
        form.addRow("Offset:", offset_spin)

        amplitude_spin = QDoubleSpinBox()
        amplitude_spin.setRange(-1_000_000.0, 1_000_000.0)
        amplitude_spin.setDecimals(3)
        amplitude_spin.setSingleStep(1.0)
        amplitude_spin.setValue(self._as_float(params.get("amplitude"), _DEFAULT_AMPLITUDE))
        form.addRow("Amplitude:", amplitude_spin)

        frequency_spin = QDoubleSpinBox()
        frequency_spin.setRange(0.0, 1_000_000.0)
        frequency_spin.setDecimals(3)
        frequency_spin.setSingleStep(0.1)
        frequency_spin.setValue(max(0.0, self._as_float(params.get("frequency_hz"), _DEFAULT_FREQUENCY_HZ)))
        form.addRow("Frequency (Hz):", frequency_spin)

        phase_spin = QDoubleSpinBox()
        phase_spin.setRange(-360.0, 360.0)
        phase_spin.setDecimals(1)
        phase_spin.setSingleStep(1.0)
        phase_spin.setValue(self._as_float(params.get("phase_deg"), _DEFAULT_PHASE_DEG))
        form.addRow("Phase (deg):", phase_spin)

        scroll.setWidget(body)
        outer.addWidget(scroll)

        actions = QHBoxLayout()
        btn_cancel = QPushButton("Cancel")
        btn_apply = QPushButton("Apply")
        actions.addStretch(1)
        actions.addWidget(btn_cancel)
        actions.addWidget(btn_apply)
        outer.addLayout(actions)
        btn_cancel.clicked.connect(dialog.reject)

        def accept() -> None:
            if not self.selected_group_keys(groups_list):
                QMessageBox.warning(dialog, title, "Select at least one channel group.")
                return
            if not self.selected_channels(channels_list):
                QMessageBox.warning(dialog, title, "Select at least one channel.")
                return
            dialog.accept()

        btn_apply.clicked.connect(accept)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None

        return {
            "group_keys": self.selected_group_keys(groups_list),
            "channel_indexes": self.selected_channels(channels_list),
            "offset": float(offset_spin.value()),
            "amplitude": float(amplitude_spin.value()),
            "frequency_hz": float(frequency_spin.value()),
            "phase_deg": float(phase_spin.value()),
        }

    def run(self, session_manager, add_on_data_dir):
        if not self.RUNNABLE:
            return
        add_on_data_dir = Path(add_on_data_dir)
        add_on_data_dir.mkdir(parents=True, exist_ok=True)
        chosen = self._ask_parameters(session_manager, add_on_data_dir)
        if chosen is None:
            return
        self._remember(add_on_data_dir, chosen)
        yield {
            "progress": 100,
            "message": f"Sine offset set for {len(chosen['channel_indexes'])} channel(s)",
        }

    # ---- Transform ----
    def applicable(self, channel_idx: int) -> bool:
        if not self.TRANSFORMATION:
            return False
        return int(channel_idx) in self._settings().channels

    def transform(self, channel_data: np.ndarray, sample_rate: float):
        if not self.TRANSFORMATION:
            return channel_data
        data = np.asarray(channel_data, dtype=np.float64)
        if data.size == 0:
            return data
        settings = self._settings()
        wave = self.sine_values(
            int(data.size),
            float(sample_rate),
            settings.offset,
            settings.amplitude,
            settings.frequency_hz,
            settings.phase_deg,
        )
        return data + wave.reshape(data.shape)

    # ---- View ----
    def view(
            self,
            add_on_data_dir: Path,
            processed_data: Dict[int, np.ndarray],
            amplitude_scale: float,
            start_point: int,
            duration_ms: float,
            start_time_ms: float,
            end_time_ms: float,
            sample_rate: float,
            axis_duration_ms: float,
            segment_idx: int,
            visible_channel_indexes: List[int],
            channel_names: List[str],
            visible_events: List[Any],
            visible_periods: List[Any],
            channel_groups: List[Any],
            channels_setup: Dict[int, Any],
            channel_units: Dict[int, str],
            painter: QPainter,
            signal_widget: QWidget,
            channel_rects: List[Tuple[int, QRect]],
            signal_width: int,
            draw_area_height: int,
            bg_color: QColor,
            grid_color: QColor,
            signal_color: QColor,
            text_color: QColor,
            axis_color: QColor,
    ):
        if not self.VIEWABLE or painter is None or duration_ms <= 0:
            return
        settings = self._settings(add_on_data_dir)
        if not settings.channels:
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(_SINE_COLOR, 1.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        duration_s = float(duration_ms) / 1000.0
        for channel_idx, rect in channel_rects:
            channel_idx = int(channel_idx)
            if channel_idx not in settings.channels or rect.width() < 2 or rect.height() < 2:
                continue
            n = max(2, min(4000, int(rect.width())))
            # Point 0 is the left edge of the window, matching ``transform``.
            rate = n / duration_s
            wave = self.sine_values(
                n,
                rate,
                settings.offset,
                settings.amplitude,
                settings.frequency_hz,
                settings.phase_deg,
            )
            setup = channels_setup.get(channel_idx) if channels_setup else None
            scale = float(getattr(setup, "scale", 1.0) or 1.0)
            y_offset = float(getattr(setup, "y_offset", 0.0) or 0.0)
            pixel_per_unit = rect.height() / max(scale, 1e-12)
            mid_y = rect.top() + rect.height() / 2.0
            xs = rect.left() + np.linspace(0.0, max(rect.width() - 1, 0), n)
            ys = mid_y - (wave + y_offset) * pixel_per_unit
            polygon = QPolygonF([QPointF(float(xs[i]), float(ys[i])) for i in range(n)])
            painter.save()
            painter.setClipRect(rect)
            painter.drawPolyline(polygon)
            painter.restore()
        painter.restore()
