# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from typing import Dict, List, Any

import numpy as np
from PyQt6.QtCore import Qt, QRect
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout, QWidget, QHBoxLayout

from ephyr.gui.dialogs.screenshot_export_dialog import ScreenshotExportDialog


class SelectedAreaSignalWidget(QWidget):
    def __init__(
        self,
        channel_indexes: List[int],
        channel_names: List[str],
        channel_data: Dict[int, np.ndarray],
        channels_setup: Dict[int, Any],
        start_time_ms: float,
        end_time_ms: float,
        parent=None,
    ):
        super().__init__(parent)
        self._channel_indexes = channel_indexes
        self._channel_names = channel_names
        self._channel_data = channel_data
        self._channels_setup = channels_setup
        self._start_time_ms = start_time_ms
        self._end_time_ms = end_time_ms

        self._LEFT_MARGIN = 90
        self._RIGHT_MARGIN = 16
        self._TOP_MARGIN = 12
        self._AXIS_HEIGHT = 30
        self._SCALE_PANEL_HEIGHT = 52
        self._BOTTOM_MARGIN = self._AXIS_HEIGHT + self._SCALE_PANEL_HEIGHT
        self._CHANNEL_SPACING = 6
        self._BG_COLOR = QColor(245, 245, 245)
        self._GRID_COLOR = QColor(200, 200, 200)
        self._TEXT_COLOR = QColor(0, 0, 0)

        self.setMinimumSize(800, 400)

    def _target_svg_dots_1khz(self) -> int:
        # 1 kHz => 1 dot per millisecond in selected interval
        duration_ms = max(0.0, self._end_time_ms - self._start_time_ms)
        return max(2, int(round(duration_ms)))

    def _resample_data(self, data: np.ndarray, target_dots: int) -> np.ndarray:
        if data is None or len(data) < 2 or target_dots <= 1:
            return data
        if len(data) == target_dots:
            return data
        old_x = np.linspace(0.0, 1.0, len(data), dtype=np.float64)
        new_x = np.linspace(0.0, 1.0, target_dots, dtype=np.float64)
        return np.interp(new_x, old_x, data).astype(np.float64)

    def draw_to_painter(self, painter: QPainter):
        painter.fillRect(self.rect(), self._BG_COLOR)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        channel_count = len(self._channel_indexes)
        draw_height = max(1, self.height() - self._TOP_MARGIN - self._BOTTOM_MARGIN)
        axis_width = max(1, self.width() - self._LEFT_MARGIN - self._RIGHT_MARGIN)
        if channel_count == 0:
            return
        channel_height = max(1, int((draw_height - (channel_count - 1) * self._CHANNEL_SPACING) / channel_count))

        for row, channel_idx in enumerate(self._channel_indexes):
            top = self._TOP_MARGIN + row * (channel_height + self._CHANNEL_SPACING)
            rect = QRect(self._LEFT_MARGIN, top, axis_width, channel_height)
            self._draw_channel(painter, channel_idx, rect)

        self._draw_time_axis(painter, draw_height)
        self._draw_scale_panel(painter, draw_height, axis_width, channel_height)

    def draw_to_painter_svg(self, painter: QPainter):
        painter.fillRect(self.rect(), self._BG_COLOR)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        channel_count = len(self._channel_indexes)
        draw_height = max(1, self.height() - self._TOP_MARGIN - self._BOTTOM_MARGIN)
        axis_width = max(1, self.width() - self._LEFT_MARGIN - self._RIGHT_MARGIN)
        if channel_count == 0:
            return
        channel_height = max(1, int((draw_height - (channel_count - 1) * self._CHANNEL_SPACING) / channel_count))
        target_dots = self._target_svg_dots_1khz()

        for row, channel_idx in enumerate(self._channel_indexes):
            top = self._TOP_MARGIN + row * (channel_height + self._CHANNEL_SPACING)
            rect = QRect(self._LEFT_MARGIN, top, axis_width, channel_height)
            self._draw_channel(painter, channel_idx, rect, target_dots=target_dots)

        self._draw_time_axis(painter, draw_height)
        self._draw_scale_panel(painter, draw_height, axis_width, channel_height)

    def paintEvent(self, event):
        painter = QPainter(self)
        self.draw_to_painter(painter)

    def _draw_channel(self, painter: QPainter, channel_idx: int, rect: QRect, target_dots: int | None = None):
        setup = self._channels_setup.get(channel_idx)
        color = QColor(str(getattr(setup, "color", "#000000")))
        if not color.isValid():
            color = QColor(0, 0, 0)
        scale_uv = float(getattr(setup, "scale", 1.0) or 1.0)
        y_offset = float(getattr(setup, "y_offset", 0.0))

        painter.setPen(QPen(self._GRID_COLOR, 1, Qt.PenStyle.DotLine))
        mid_y = rect.top() + rect.height() // 2
        painter.drawLine(rect.left(), mid_y, rect.right(), mid_y)

        painter.setPen(self._TEXT_COLOR)
        font = QFont()
        font.setPointSize(10)
        painter.setFont(font)
        ch_name = self._channel_names[channel_idx] if 0 <= channel_idx < len(self._channel_names) else ""
        label = f"{channel_idx} [{ch_name}]" if ch_name else str(channel_idx)
        painter.drawText(QRect(0, rect.top(), self._LEFT_MARGIN - 8, rect.height()),
                         Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, label)

        data = self._channel_data.get(channel_idx)
        if data is None or len(data) < 2:
            return
        if target_dots is not None:
            data = self._resample_data(data, target_dots)
        n = len(data)
        x = np.linspace(rect.left(), rect.right(), n, dtype=np.float32)
        pixel_per_uv = rect.height() / max(scale_uv, 1e-12)
        y = (rect.top() + rect.height() / 2.0) - (data + y_offset) * pixel_per_uv

        painter.setPen(QPen(color, 1.2))
        prev_x = float(x[0])
        prev_y = float(y[0])
        for i in range(1, n):
            cur_x = float(x[i])
            cur_y = float(y[i])
            if rect.top() <= prev_y <= rect.bottom() and rect.top() <= cur_y <= rect.bottom():
                painter.drawLine(int(prev_x), int(prev_y), int(cur_x), int(cur_y))
            prev_x = cur_x
            prev_y = cur_y

    def _draw_time_axis(self, painter: QPainter, draw_height: int):
        axis_y = self._TOP_MARGIN + draw_height + 8
        axis_left = self._LEFT_MARGIN
        axis_right = self.width() - self._RIGHT_MARGIN
        painter.setPen(QPen(QColor(100, 100, 100), 1.5))
        painter.drawLine(axis_left, axis_y, axis_right, axis_y)

        duration_ms = max(0.0, self._end_time_ms - self._start_time_ms)
        labels = [
            (axis_left, self._start_time_ms),
            ((axis_left + axis_right) // 2, self._start_time_ms + duration_ms / 2.0),
            (axis_right, self._end_time_ms),
        ]
        font = QFont()
        font.setPointSize(9)
        painter.setFont(font)
        for x, t_ms in labels:
            painter.drawLine(x, axis_y, x, axis_y + 5)
            painter.drawText(QRect(x - 70, axis_y + 6, 140, 16), Qt.AlignmentFlag.AlignCenter, f"{t_ms:.1f} ms")

    def _draw_scale_panel(self, painter: QPainter, draw_height: int, axis_width: int, channel_height: int):
        panel_top = self._TOP_MARGIN + draw_height + self._AXIS_HEIGHT
        panel_rect = QRect(self._LEFT_MARGIN, panel_top, axis_width, self._SCALE_PANEL_HEIGHT)

        # Scale bars similar to Measure bar:
        # - Voltage bar height: 1/10 of current channel height
        # - Time bar width: 1/10 of selected interval width
        voltage_bar_height = max(6, channel_height // 10)
        time_bar_width = max(20, axis_width // 10)
        duration_ms = max(0.0, self._end_time_ms - self._start_time_ms)

        representative_scale = 1.0
        if self._channel_indexes:
            first_setup = self._channels_setup.get(self._channel_indexes[0])
            representative_scale = float(getattr(first_setup, "scale", 1.0) or 1.0)
        voltage_value = representative_scale / 10.0
        time_value_ms = duration_ms / 10.0

        # Left-bottom corner placement (just above time bar)
        vx = panel_rect.left() + 10
        vy = panel_rect.top() + 8
        painter.fillRect(vx, vy, 4, voltage_bar_height, QColor(255, 0, 0))
        painter.setPen(self._TEXT_COLOR)
        painter.drawText(QRect(vx + 8, vy - 8, 120, 20), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         f"{voltage_value:.2f} uV")

        # Time bar next to voltage bar in left-bottom corner
        tx = min(panel_rect.right() - time_bar_width - 8, vx + 130)
        ty = vy + max(voltage_bar_height // 2, 8)
        painter.fillRect(tx, ty, time_bar_width, 4, QColor(255, 0, 0))
        if time_value_ms < 1000:
            time_text = f"{time_value_ms:.1f} ms"
        else:
            time_text = f"{time_value_ms / 1000.0:.2f} s"
        painter.drawText(QRect(tx, ty + 6, time_bar_width, 18), Qt.AlignmentFlag.AlignCenter, time_text)


class FullViewSelectedAreaDialog(QDialog):
    def __init__(
        self,
        channel_indexes: List[int],
        channel_names: List[str],
        channel_data: Dict[int, np.ndarray],
        channels_setup: Dict[int, Any],
        start_time_ms: float,
        end_time_ms: float,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Full-view selected area")
        self.setModal(False)
        self.resize(1000, 640)

        root = QVBoxLayout(self)
        self.signal_view = SelectedAreaSignalWidget(
            channel_indexes=channel_indexes,
            channel_names=channel_names,
            channel_data=channel_data,
            channels_setup=channels_setup,
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
            parent=self,
        )
        root.addWidget(self.signal_view, 1)

        controls = QHBoxLayout()
        self.btn_screenshot = QPushButton("Screenshot", self)
        self.status_label = QLabel("", self)
        self.status_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        controls.addWidget(self.btn_screenshot)
        controls.addWidget(self.status_label, 1)
        root.addLayout(controls)

        self.btn_screenshot.clicked.connect(self.on_screenshot)

    def on_screenshot(self):
        pixmap: QPixmap = self.signal_view.grab()
        result = ScreenshotExportDialog.run_export_for_pixmap(
            self,
            pixmap,
            default_name_prefix="full_view_selected_area",
            vector_draw_fn=self.signal_view.draw_to_painter_svg,
            vector_size=self.signal_view.size(),
        )
        self.status_label.setText(result.message)
