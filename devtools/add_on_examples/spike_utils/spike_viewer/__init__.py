"""Spike viewer add-on.

Runnable + Viewable. ``run()`` selects a detection result set (and optionally a
channel subset); ``view()`` overlays red markers at the vertical center of each
channel cell (amplitude ignored) for spikes inside the visible time window.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from weegit.core.add_ons.base import BaseAddOn
from weegit.logger import weegit_logger

from weegit_add_ons.spike_utils._common import SpikesPayload, SpikeUtilsBase


class SpikeViewerAddOn(SpikeUtilsBase, BaseAddOn):
    TRANSFORMATION = False
    VIEWABLE = True
    RUNNABLE = True
    Z_INDEX = 250

    def __init__(self):
        self._cached_path: Optional[Path] = None
        self._cached_mtime: Optional[float] = None
        self._cached_payload: Optional[SpikesPayload] = None

    def run(self, session_manager, add_on_data_dir):
        add_on_data_dir = Path(add_on_data_dir)
        params = self.load_params(add_on_data_dir)
        selected = self.choose_result_dir_dialog(
            "Spike viewer", add_on_data_dir, selected_dir=str(params.get("selected_dir", ""))
        )
        if selected is None:
            return

        sweep_idx = int(session_manager.gui_setup.current_sweep_idx)
        payload = self.read_spikes_payload(selected, sweep_idx)
        channel_choice = self._ask_channels(payload)
        if channel_choice is None:
            return

        self.save_params(
            add_on_data_dir,
            {"selected_dir": str(selected), "channels": channel_choice},
        )
        self._cached_path = None
        n = 0 if payload is None else sum(len(v) for v in payload.spikes_by_channel.values())
        yield {"progress": 100, "message": f"Viewing {selected.name} ({n} spikes)"}

    def _ask_channels(self, payload: Optional[SpikesPayload]) -> Optional[List[int]]:
        available = sorted(payload.spikes_by_channel.keys()) if payload is not None else []
        if not available:
            # Nothing detected for this sweep yet; view all by default.
            return []
        dialog = QDialog()
        dialog.setWindowTitle("Spike viewer channels")
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        channels_list = QListWidget()
        channels_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        for ch in available:
            item = QListWidgetItem(str(ch))
            item.setData(Qt.ItemDataRole.UserRole, int(ch))
            item.setSelected(True)
            channels_list.addItem(item)
        form.addRow("Channels (none = all):", channels_list)
        layout.addLayout(form)
        actions = QHBoxLayout()
        btn_cancel = QPushButton("Cancel")
        btn_ok = QPushButton("Show")
        actions.addStretch(1)
        actions.addWidget(btn_cancel)
        actions.addWidget(btn_ok)
        layout.addLayout(actions)
        btn_cancel.clicked.connect(dialog.reject)
        btn_ok.clicked.connect(dialog.accept)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return [
            channels_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(channels_list.count())
            if channels_list.item(i).isSelected()
        ]

    def _load_payload(self, add_on_data_dir: Path, sweep_idx: int) -> Optional[SpikesPayload]:
        params = self.load_params(add_on_data_dir)
        selected_dir = str(params.get("selected_dir", ""))
        if not selected_dir:
            return None
        path = Path(selected_dir) / f"{int(sweep_idx)}.spikes.json"
        if not path.exists():
            return None
        try:
            mtime = path.stat().st_mtime
        except Exception as e:
            weegit_logger().debug(str(e))
            return None
        if self._cached_path == path and self._cached_mtime == mtime and self._cached_payload is not None:
            return self._cached_payload
        payload = self.read_spikes_payload(Path(selected_dir), int(sweep_idx))
        self._cached_path = path
        self._cached_mtime = mtime
        self._cached_payload = payload
        return payload

    def view(
        self,
        add_on_data_dir: Path,
        processed_data: Dict[int, np.ndarray],
        voltage_scale: float,
        start_point: int,
        duration_ms: float,
        start_time_ms: float,
        end_time_ms: float,
        sample_rate: float,
        axis_duration_ms: float,
        sweep_idx: int,
        visible_channel_indexes: List[int],
        channel_names: List[str],
        visible_events: List[Any],
        visible_periods: List[Any],
        channel_groups: List[Any],
        channels_setup: Dict[int, Any],
        painter: QPainter,
        signal_widget: QWidget,
        channel_rects: List[Tuple[int, "Any"]],
        signal_width: int,
        draw_area_height: int,
        bg_color: QColor,
        grid_color: QColor,
        signal_color: QColor,
        text_color: QColor,
        axis_color: QColor,
        **kwargs,
    ):
        if painter is None or signal_widget is None or duration_ms <= 0 or axis_duration_ms <= 0:
            return
        add_on_data_dir = Path(add_on_data_dir) if add_on_data_dir is not None else None
        if add_on_data_dir is None:
            return
        payload = self._load_payload(add_on_data_dir, int(sweep_idx))
        if payload is None:
            return

        params = self.load_params(add_on_data_dir)
        selected_channels = set(int(c) for c in (params.get("channels", []) or []))

        painter.setPen(QPen(QColor(255, 0, 0)))
        painter.setBrush(QColor(255, 0, 0))
        marker_size = 4
        half = marker_size // 2
        for channel_idx, rect in channel_rects:
            if selected_channels and int(channel_idx) not in selected_channels:
                continue
            spikes = payload.spikes_by_channel.get(int(channel_idx))
            if not spikes:
                continue
            y = rect.center().y()
            for spike in spikes:
                if not (start_time_ms <= spike.time_ms <= end_time_ms):
                    continue
                rel = (spike.time_ms - start_time_ms) / axis_duration_ms
                x = int(rect.left() + rel * rect.width())
                painter.drawRect(x - half, y - half, marker_size, marker_size)
