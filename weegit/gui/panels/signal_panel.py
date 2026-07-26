from enum import Enum

import numpy as np
from PyQt6.QtCore import Qt, QRect, pyqtSignal, QPoint, QLineF, QEvent, QSize, QTimer
from PyQt6.QtGui import QPainter, QColor, QFont, QPen, QWheelEvent, QMouseEvent, QKeyEvent, QPixmap, QFontMetrics, \
    QImage, QCursor
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QScrollBar, QHBoxLayout, QPushButton, QDialog
from typing import Optional, List, Dict, Tuple
import math
from pathlib import Path

from weegit import settings
from weegit.core.weegit_session import ChannelSetup, EventVocabularyEntry, PeriodVocabularyEntry, ChannelGroup
from weegit.core.add_ons.base import BaseAddOn, ViewEntitiesZIndexEnum
from weegit.gui.dialogs.full_view_selected_area_dialog import FullViewSelectedAreaDialog
from weegit.gui._utils import milliseconds_to_readable
from weegit.gui.qt_weegit_session_manager_wrapper import QtWeegitSessionManagerWrapper
from weegit.logger import weegit_logger


class TopNavigatorWidget(QWidget):
    """Widget for displaying event names with navigation arrows"""

    event_navigation_requested = pyqtSignal(int)  # Emits new start_point

    def __init__(self, left_margin, right_margin, parent=None):
        super().__init__(parent)
        self._BG_COLOR = QColor(240, 240, 240)  # Same as SignalWidget
        self._TEXT_COLOR = QColor(0, 0, 255)
        self._TEXT_BAD_COLOR = QColor(255, 0, 0)
        self._ARROW_COLOR = QColor(100, 100, 100)
        self._ARROW_HOVER_COLOR = QColor(0, 0, 200)
        self._left_margin = left_margin
        self._right_margin = right_margin

        self._all_events = []
        self._visible_events = []
        self._events_vocabulary: Dict[int, EventVocabularyEntry] = {}
        self._all_periods = []
        self._visible_periods = []
        self._periods_vocabulary: Dict[int, PeriodVocabularyEntry] = {}
        self._current_sweep_idx: int = 0
        self._start_point = 0
        self._duration_ms = 0.0
        self._sample_rate = 1.0
        self._header_points_per_sweep = 0
        self._start_time_ms = 0.0
        self._axis_offset_px = 0

        # For hover tracking
        self._hovered_arrow: Optional[Tuple[int, str]] = None  # (event_index, 'left'/'right')
        self.setMouseTracking(True)

        self._font = QFont()
        self._font.setPointSize(12)
        self._font_metrics = QFontMetrics(self._font)

    def update_events(
            self,
            all_events: List,
            visible_events: List,
            events_vocabulary: Dict[int, EventVocabularyEntry],
            all_periods: List,
            visible_periods: List,
            periods_vocabulary: Dict[int, PeriodVocabularyEntry],
            sweep_idx: int,
            start_point: int,
            duration_ms: float,
            sample_rate: float,
            start_time_ms: float,
            header_points_per_sweep: int,
            axis_offset_px: int = 0,
    ):
        """Update event data for display"""
        self._all_events = all_events or []
        self._visible_events = visible_events or []
        self._events_vocabulary = events_vocabulary or {}
        self._all_periods = all_periods or []
        self._visible_periods = visible_periods or []
        self._periods_vocabulary = periods_vocabulary or {}
        self._current_sweep_idx = sweep_idx
        self._start_point = start_point
        self._duration_ms = duration_ms
        self._sample_rate = sample_rate
        self._start_time_ms = start_time_ms
        self._header_points_per_sweep = header_points_per_sweep
        self._axis_offset_px = max(0, int(axis_offset_px))
        self._update_hover_from_cursor()
        self.update()

    def _event_display_name(self, event) -> str:
        base_name = self._events_vocabulary.get(
            event.event_name_id,
            EventVocabularyEntry(name=f"Event {event.event_name_id}"),
        ).name
        same_name_events = [
            ev for ev in self._all_events
            if ev.event_name_id == event.event_name_id and ev.sweep_idx == event.sweep_idx
        ]
        try:
            idx_in_sweep = same_name_events.index(event) + 1
        except ValueError:
            idx_in_sweep = 1
        if getattr(event, "is_bad", False):
            return f"{base_name} ({idx_in_sweep}, bad)"
        return f"{base_name} ({idx_in_sweep})"

    def _event_color(self, event) -> QColor:
        if getattr(event, "is_bad", False):
            return QColor(255, 0, 0)
        entry = self._events_vocabulary.get(event.event_name_id)
        color_str = entry.color if entry else "#0066FF"
        color = QColor(color_str)
        if not color.isValid():
            color = QColor("#0066FF")
        return color

    def _period_color(self, period) -> QColor:
        entry = self._periods_vocabulary.get(period.period_name_id)
        color = QColor(entry.color if entry and entry.color else "#00AA55")
        if not color.isValid():
            color = QColor("#00AA55")
        return color

    def _hover_for_position(self, pos: QPoint) -> Optional[Tuple[int, str]]:
        axis_start_x = self._left_margin + self._axis_offset_px
        start_time_ms = self._start_time_ms
        axis_width = self.width() - self._right_margin - axis_start_x
        if axis_width <= 0 or self._duration_ms <= 0:
            return None

        for event in self._visible_events:
            name = self._event_display_name(event)
            text_width = self._font_metrics.horizontalAdvance(name)
            x = axis_start_x + ((event.time_ms - start_time_ms) / self._duration_ms) * axis_width
            x_pos = int(x)
            arrow_size = 10

            left_arrow_rect = QRect(
                int(x_pos - text_width // 2 - arrow_size - 5),
                15 - arrow_size // 2,
                arrow_size,
                arrow_size,
            )
            if left_arrow_rect.contains(pos):
                return self._all_events.index(event), 'left'

            right_arrow_rect = QRect(
                int(x_pos + text_width // 2 + 5),
                15 - arrow_size // 2,
                arrow_size,
                arrow_size,
            )
            if right_arrow_rect.contains(pos):
                return self._all_events.index(event), 'right'

        return None

    def _update_hover_from_cursor(self):
        old_hover = self._hovered_arrow
        local_pos = self.mapFromGlobal(QCursor.pos())
        if self.rect().contains(local_pos):
            self._hovered_arrow = self._hover_for_position(local_pos)
        else:
            self._hovered_arrow = None
        if old_hover != self._hovered_arrow:
            self.update()

    def paintEvent(self, event):
        if self._duration_ms <= 0:
            return

        painter = QPainter(self)
        painter.fillRect(self.rect(), self._BG_COLOR)
        if not self._visible_events and not self._visible_periods:
            return

        painter.setFont(self._font)

        # Draw events with arrows
        axis_start_x = self._left_margin + self._axis_offset_px
        start_time_ms = self._start_time_ms
        axis_width = self.width() - self._right_margin - axis_start_x
        if axis_width <= 0:
            return

        # Draw arrows
        arrow_size = 10
        arrow_y = 15

        for event in self._visible_events:
            # Draw event name
            name = self._event_display_name(event)
            painter.setPen(self._event_color(event))
            text_width = self._font_metrics.horizontalAdvance(name)
            x = axis_start_x + ((event.time_ms - start_time_ms) / self._duration_ms) * axis_width
            x_pos = int(x)
            text_rect = QRect(int(x_pos - text_width // 2), 5, text_width, 20)
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, name)

            event_idx = self._all_events.index(event)
            # Left arrow
            left_arrow_rect = QRect(int(x_pos - text_width // 2 - arrow_size - 5), arrow_y - arrow_size // 2,
                                    arrow_size, arrow_size)
            self._draw_arrow(painter, left_arrow_rect, 'left',
                             (event_idx, 'left') == self._hovered_arrow)

            # Right arrow
            right_arrow_rect = QRect(int(x_pos + text_width // 2 + 5), arrow_y - arrow_size // 2,
                                     arrow_size, arrow_size)
            self._draw_arrow(painter, right_arrow_rect, 'right',
                             (event_idx, 'right') == self._hovered_arrow)

        # Draw period labels (start/end)
        if self._visible_periods:
            for period in self._visible_periods:
                entry = self._periods_vocabulary.get(period.period_name_id)
                name = entry.name if entry else ""
                if not name:
                    continue

                painter.setPen(self._period_color(period))
                for time_ms, suffix in (
                        (period.start_time_ms, "(s)"),
                        (period.end_time_ms, "(e)"),
                ):
                    if not (start_time_ms <= time_ms <= start_time_ms + self._duration_ms):
                        continue

                    label = f"{name}{suffix}"
                    text_width = self._font_metrics.horizontalAdvance(label)
                    x = axis_start_x + ((time_ms - start_time_ms) / self._duration_ms) * axis_width
                    x_pos = int(x)
                    text_rect = QRect(int(x_pos - text_width // 2), 5, text_width, 20)
                    painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, label)

    def _draw_arrow(self, painter: QPainter, rect: QRect, direction: str, hovered: bool):
        """Draw an arrow in the given rectangle"""
        color = self._ARROW_HOVER_COLOR if hovered else self._ARROW_COLOR
        painter.setPen(QPen(color, 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)

        # Draw arrow as triangle
        points = []
        if direction == 'left':
            points = [
                QPoint(rect.right(), rect.top()),
                QPoint(rect.left(), rect.center().y()),
                QPoint(rect.right(), rect.bottom())
            ]
        else:  # 'right'
            points = [
                QPoint(rect.left(), rect.top()),
                QPoint(rect.right(), rect.center().y()),
                QPoint(rect.left(), rect.bottom())
            ]

        painter.drawPolygon(points)

    def mouseMoveEvent(self, event):
        """Track mouse movement for arrow hover effects"""
        pos = event.position().toPoint()
        old_hover = self._hovered_arrow
        self._hovered_arrow = self._hover_for_position(pos)

        if old_hover != self._hovered_arrow:
            self.update()

    def mousePressEvent(self, event):
        """Handle arrow clicks for navigation"""
        if event.button() == Qt.MouseButton.LeftButton and self._hovered_arrow:
            event_idx, direction = self._hovered_arrow
            self._navigate_to_neighbor_event(event_idx, direction)

    def _navigate_to_neighbor_event(self, current_event_idx: int, direction: str):
        """Calculate and emit new start_point to center neighbor event"""
        if not self._all_events:
            return

        current_event = self._all_events[current_event_idx]
        event_name_id = current_event.event_name_id
        sweep_idx = current_event.sweep_idx

        # Find all events with same name in current sweep
        same_name_events = [
            event for event in self._all_events
            if event.event_name_id == event_name_id and event.sweep_idx == sweep_idx
        ]

        if not same_name_events:
            return

        # Find current event in the list
        current_in_list_idx = same_name_events.index(current_event)
        if current_in_list_idx == -1:
            return

        # Get neighbor event
        if direction == 'left':
            neighbor_idx = current_in_list_idx - 1
        else:  # 'right'
            neighbor_idx = current_in_list_idx + 1

        if 0 <= neighbor_idx < len(same_name_events):
            neighbor_event = same_name_events[neighbor_idx]
            # Calculate new start_point to center this event
            new_start_point = self._calculate_start_point_to_center(neighbor_event.time_ms)
            self.event_navigation_requested.emit(new_start_point)

    def _calculate_start_point_to_center(self, target_time_ms: float) -> int:
        """Calculate start_point that centers the target event"""
        # Convert time to samples
        target_samples = int((target_time_ms / 1000.0) * self._sample_rate)

        # Calculate samples for half duration
        half_duration_samples = int((self._duration_ms / 2000.0) * self._sample_rate)

        # Calculate start_point to center the event
        new_start_point = target_samples - half_duration_samples

        # Ensure we don't go out of bounds
        new_start_point = max(0, new_start_point)
        max_start = max(0, self._header_points_per_sweep -
                        int((self._duration_ms / 1000.0) * self._sample_rate))
        new_start_point = min(new_start_point, max_start)

        return new_start_point


class SignalWidget(QWidget):
    """Custom widget for signal display that handles its own paint events"""

    def __init__(self, left_margin, right_margin, bottom_margin, parent=None):
        super().__init__(parent)
        self.pixmap_cache = QPixmap()
        self._BG_COLOR = QColor(240, 240, 240)
        self._GRID_COLOR = QColor(200, 200, 200)
        self._SIGNAL_COLOR = QColor(0, 0, 0)
        self._TEXT_COLOR = QColor(0, 0, 0)
        self._AXIS_COLOR = QColor(100, 100, 100)
        self._DISABLED_TEXT_COLOR = QColor(150, 150, 150)
        self._CHANNEL_SPACING = 5
        self._GROUP_GAP = 16
        self._left_margin = left_margin
        self._right_margin = right_margin
        self._bottom_margin = bottom_margin

        self._font = QFont()
        self._font.setPointSize(12)
        self._font_metrics = QFontMetrics(self._font)

        self._processed_data = {}
        self._visible_channel_indexes = []
        self._channel_names = []
        self._voltage_scale = 0.0
        self._channel_height = 0
        self._x_coords_cache: Dict[Tuple[int, int], np.ndarray] = {}
        self._lines_cache: Dict[Tuple[int, int], List[QLineF]] = {}
        self._axis_start_point = 0  # in samples within sweep
        self._axis_duration_ms = 0.0
        self._sample_rate = 1.0
        self._start_time_ms = 0.0
        self._end_time_ms = 0.0
        self._axis_start_x = 0
        self._axis_width = 0
        self._visible_events = []
        self._visible_periods = []
        self._events_vocabulary: Dict[int, EventVocabularyEntry] = {}
        self._periods_vocabulary: Dict[int, PeriodVocabularyEntry] = {}
        self._current_sweep_idx: int = 0
        self._traces_are_visible = True
        self._events_are_visible = True
        self._periods_are_visible = True
        self._viewable_add_ons: List[BaseAddOn] = []
        self._add_ons_data_dir: Optional[Path] = None
        self._cut_traces = False
        self._overlay_widget: Optional['OverlayWidget'] = None
        self._digital_channel_rects: List[Tuple[int, QRect]] = []
        self._channel_names: List[str] = []
        self._group_layouts: List[ChannelGroup] = []
        self._channels_setup: Dict[int, ChannelSetup] = {}
        self._auxiliary_group_rects: List[Tuple[int, QRect]] = []
        self._non_aux_group_rects: List[Tuple[int, QRect]] = []
        self._channel_group_rects: Dict[int, QRect] = {}
        # (channel_idx, cell_rect, enabled, group_visible_cell_count)
        self._cell_rects: List[Tuple[int, QRect, bool, int]] = []
        self._cell_border_rects: List[QRect] = []
        # group_rect per shown-group index (aligned to self._group_layouts)
        self._group_layout_rects: List[QRect] = []
        self._group_titles: List[Tuple[str, QRect]] = []
        self._font_by_pt: Dict[int, QFont] = {}
        self._fm_by_pt: Dict[int, QFontMetrics] = {}
        self._geometry_signature: Optional[Tuple] = None
        self._first_non_aux_cell_h = 0
        self._signal_pixmap_offset = QPoint(self._left_margin, 0)
        self._draw_area_height = 0

    def set_overlay_widget(self, overlay_widget: Optional['OverlayWidget']):
        """Attach an overlay widget that mirrors the signal widget geometry."""
        self._overlay_widget = overlay_widget
        if self._overlay_widget:
            self._overlay_widget.setParent(self)
            self._overlay_widget.setGeometry(self.rect())
            self._overlay_widget.raise_()

    def reset_data_and_redraw(
            self,
            processed_data,
            visible_channel_indexes,
            channel_names,
            voltage_scale,
            *,
            group_layouts: Optional[List[ChannelGroup]] = None,
            channels_setup: Optional[Dict[int, ChannelSetup]] = None,
            start_point: int,
            duration_ms: float,
            start_time_ms: float,
            sample_rate: float,
            visible_events=None,
            visible_periods=None,
            events_vocabulary: Optional[Dict[int, EventVocabularyEntry]] = None,
            periods_vocabulary: Optional[Dict[int, PeriodVocabularyEntry]] = None,
            sweep_idx: int = 0,
            events_are_visible: bool = True,
            periods_are_visible: bool = True,
            traces_are_visible: bool = True,
            cut_traces: bool = False,
            viewable_add_ons: Optional[List[BaseAddOn]] = None,
            add_ons_data_dir: Optional[Path] = None,
    ):
        # SETUP VARIABLES
        self._processed_data = processed_data
        self._visible_channel_indexes = visible_channel_indexes
        self._voltage_scale = voltage_scale
        self._axis_start_point = max(0, start_point)
        self._axis_duration_ms = max(0.0, duration_ms)
        self._sample_rate = sample_rate if sample_rate > 0 else 1.0
        self._start_time_ms = start_time_ms
        self._end_time_ms = self._start_time_ms + self._axis_duration_ms
        self._visible_events = visible_events
        self._visible_periods = visible_periods
        self._events_vocabulary = dict(events_vocabulary or {})
        self._periods_vocabulary = dict(periods_vocabulary or {})
        self._current_sweep_idx = sweep_idx
        self._events_are_visible = events_are_visible
        self._periods_are_visible = periods_are_visible
        self._traces_are_visible = traces_are_visible
        self._cut_traces = bool(cut_traces)
        self._viewable_add_ons = list(viewable_add_ons or [])
        self._add_ons_data_dir = add_ons_data_dir
        self._channel_names = channel_names or []
        self._group_layouts = list(group_layouts or [])
        self._channels_setup = dict(channels_setup or {})

        self._draw_area_height = max(0, self.height() - self._bottom_margin)
        self._signal_pixmap_offset = QPoint(self._left_margin, 0)
        self._axis_start_x = 0
        self._axis_width = max(0, self.width() - self._left_margin - self._right_margin)
        if self._axis_width == 0 or self._draw_area_height == 0:
            self._reset_geometry()
            self._geometry_signature = None
            self.pixmap_cache = QPixmap()
            self.update()
            return

        self._compute_geometry()

        # DRAW
        self.pixmap_cache = QPixmap(self._axis_width, self._draw_area_height)
        painter = QPainter(self.pixmap_cache)
        painter.fillRect(0, 0, self._axis_width, self._draw_area_height, self._BG_COLOR)

        self._draw_add_ons(0, ViewEntitiesZIndexEnum.MIDDLE_LINE.value, painter)
        self._draw_group_titles(painter)
        if self._traces_are_visible:
            for channel_idx, cell_rect, enabled, _count in self._cell_rects:
                if enabled:
                    self._draw_middle_line(painter, cell_rect)

        self._draw_add_ons(ViewEntitiesZIndexEnum.MIDDLE_LINE.value, ViewEntitiesZIndexEnum.TRACES.value, painter)
        if self._traces_are_visible:
            cur_draw_idx = 0
            for channel_idx, cell_rect, enabled, _count in self._cell_rects:
                if not enabled:
                    continue
                channel_data = processed_data.get(channel_idx)
                if channel_data is None:
                    continue
                self._draw_trace(
                    painter,
                    channel_data,
                    cell_rect,
                    voltage_scale,
                    channel_idx,
                    cur_draw_idx,
                )
                cur_draw_idx += 1

            self._draw_auxiliary_groups(painter, processed_data)

        self._draw_add_ons(ViewEntitiesZIndexEnum.TRACES.value, ViewEntitiesZIndexEnum.PERIODS.value, painter)
        if self._periods_are_visible:
            self._draw_periods(painter)

        self._draw_add_ons(ViewEntitiesZIndexEnum.PERIODS.value, ViewEntitiesZIndexEnum.EVENTS.value, painter)
        if self._events_are_visible:
            self._draw_events(painter)

        self._draw_channel_names(painter)
        self._draw_cell_borders(painter)
        painter.end()
        self.update()  # Trigger paint event

    def _draw_cell_borders(self, painter: QPainter):
        if not self._cell_border_rects:
            return
        painter.setPen(QPen(self._GRID_COLOR, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for rect in self._cell_border_rects:
            # Adjacent cells share an edge, so a 1px rect keeps a single-pixel border.
            painter.drawRect(rect.adjusted(0, 0, -1, -1))

    def _reset_geometry(self):
        self._digital_channel_rects = []
        self._auxiliary_group_rects = []
        self._non_aux_group_rects = []
        self._channel_group_rects = {}
        self._cell_rects = []
        self._cell_border_rects = []
        self._group_layout_rects = []
        self._group_titles = []
        self._first_non_aux_cell_h = 0

    def _geometry_sig(self) -> Tuple:
        def group_sig(group: ChannelGroup) -> Tuple:
            layout = group.channels_layout
            table = layout.layout_table if (layout.enable_custom_layout and layout.layout_table) else None
            table_sig = tuple(tuple(row) for row in table) if table else None
            gl = group.group_layout
            return (
                group.name,
                group.is_auxiliary,
                gl.layout_row_idx,
                gl.layout_column_idx,
                round(float(gl.height_ratio), 4),
                round(float(gl.width_ratio), 4),
                tuple(group.channel_indexes),
                tuple(sorted(group.enabled_indexes)),
                layout.enable_custom_layout,
                layout.draw_borders,
                layout.columns_num_to_show,
                layout.cur_column_idx,
                layout.rows_num_to_show,
                layout.cur_row_idx,
                table_sig,
            )

        return (
            self._axis_width,
            self._draw_area_height,
            tuple(group_sig(g) for g in self._group_layouts),
        )

    def _arrange_group_rows(self) -> List[List[Tuple[int, ChannelGroup]]]:
        """Group shown groups into horizontal rows.

        Falls back to the classic one-group-per-row stacking when every group
        shares the same (layout_row_idx, layout_column_idx) (i.e. defaults).
        """
        groups = list(enumerate(self._group_layouts))
        if not groups:
            return []
        all_same = (
            len({g.group_layout.layout_row_idx for _i, g in groups}) == 1
            and len({g.group_layout.layout_column_idx for _i, g in groups}) == 1
        )
        if all_same:
            return [[(i, g)] for i, g in groups]

        rows_map: Dict[int, List[Tuple[int, ChannelGroup]]] = {}
        for i, g in groups:
            rows_map.setdefault(g.group_layout.layout_row_idx, []).append((i, g))
        arranged: List[List[Tuple[int, ChannelGroup]]] = []
        for row_key in sorted(rows_map):
            row = sorted(rows_map[row_key], key=lambda pair: (pair[1].group_layout.layout_column_idx, pair[0]))
            arranged.append(row)
        return arranged

    def _compute_geometry(self):
        sig = self._geometry_sig()
        if sig == self._geometry_signature and self._group_layout_rects:
            return
        self._reset_geometry()
        self._geometry_signature = sig
        self._group_layout_rects = [QRect() for _ in self._group_layouts]
        if not self._group_layouts:
            self._channel_height = 0
            return

        rows = self._arrange_group_rows()
        gap = self._GROUP_GAP
        num_rows = len(rows)
        available_height = max(0, self._draw_area_height - gap * num_rows)
        row_ratios = [max(1e-6, max(float(g.group_layout.height_ratio) for _i, g in row)) for row in rows]
        total_ratio = sum(row_ratios) or 1.0

        y_cursor = 0
        for ri, row in enumerate(rows):
            y_cursor += gap
            row_h = int(available_height * row_ratios[ri] / total_ratio)
            if ri == num_rows - 1:
                row_h = max(0, self._draw_area_height - y_cursor)
            total_w_ratio = sum(max(1e-6, float(g.group_layout.width_ratio)) for _i, g in row) or 1.0
            num_cols = len(row)
            available_width = max(0, self._axis_width - gap * (num_cols - 1))
            x_cursor = 0
            for ci, (list_idx, group) in enumerate(row):
                w = int(available_width * max(1e-6, float(group.group_layout.width_ratio)) / total_w_ratio)
                if ci == num_cols - 1:
                    w = max(0, self._axis_width - x_cursor)
                group_rect = QRect(x_cursor, y_cursor, max(0, w), max(0, row_h))
                self._group_layout_rects[list_idx] = group_rect
                self._place_group(list_idx, group, group_rect)
                x_cursor += w + gap
            y_cursor += row_h

        self._channel_height = self._first_non_aux_cell_h

    def _place_group(self, list_idx: int, group: ChannelGroup, group_rect: QRect):
        if group_rect.width() <= 0 or group_rect.height() <= 0:
            return
        self._group_titles.append((str(group.name or ""), group_rect))
        if group.is_auxiliary:
            self._auxiliary_group_rects.append((list_idx, group_rect))
            return

        rows_to_show, cols_to_show, _cur_row, _cur_col, _rows_num, _cols_num = group.visible_window()
        if rows_to_show <= 0 or cols_to_show <= 0:
            return
        self._non_aux_group_rects.append((list_idx, group_rect))
        # Channels tile the group with no spacing; cumulative rounding avoids gaps.
        col_w = group_rect.width() / cols_to_show
        row_h = group_rect.height() / rows_to_show
        if self._first_non_aux_cell_h == 0:
            self._first_non_aux_cell_h = max(1, int(row_h))
        cell_count = rows_to_show * cols_to_show
        draw_borders = bool(group.channels_layout.draw_borders)
        clip_rect = QRect(group_rect)
        for r_off, c_off, channel_idx in group.visible_cells():
            x = group_rect.left() + int(round(c_off * col_w))
            x_next = group_rect.left() + int(round((c_off + 1) * col_w))
            y = group_rect.top() + int(round(r_off * row_h))
            y_next = group_rect.top() + int(round((r_off + 1) * row_h))
            cell_rect = QRect(x, y, max(1, x_next - x), max(1, y_next - y))
            enabled = channel_idx in group.enabled_indexes
            self._cell_rects.append((channel_idx, cell_rect, enabled, cell_count))
            self._channel_group_rects[channel_idx] = clip_rect
            if enabled:
                self._digital_channel_rects.append((channel_idx, cell_rect))
            if draw_borders:
                self._cell_border_rects.append(cell_rect)

    def _font_size_for_count(self, count: int) -> int:
        if count <= 6:
            return 12
        if count <= 12:
            return 10
        if count <= 24:
            return 9
        if count <= 48:
            return 8
        if count <= 96:
            return 7
        return 6

    def _font_for_count(self, count: int) -> Tuple[QFont, QFontMetrics]:
        pt = self._font_size_for_count(count)
        font = self._font_by_pt.get(pt)
        if font is None:
            font = QFont()
            font.setPointSize(pt)
            self._font_by_pt[pt] = font
            self._fm_by_pt[pt] = QFontMetrics(font)
        return font, self._fm_by_pt[pt]

    def _channel_display_name(self, channel_idx: int) -> str:
        if 0 <= channel_idx < len(self._channel_names) and self._channel_names[channel_idx]:
            base = str(self._channel_names[channel_idx])
        else:
            base = str(channel_idx)
        return base[:10]

    def _draw_channel_names(self, painter: QPainter):
        for channel_idx, cell_rect, enabled, count in self._cell_rects:
            if cell_rect.height() < 8:
                continue
            font, fm = self._font_for_count(count)
            painter.setFont(font)
            painter.setPen(self._TEXT_COLOR if enabled else self._DISABLED_TEXT_COLOR)
            text_rect = QRect(
                cell_rect.left() + 2,
                cell_rect.top() + 1,
                max(1, cell_rect.width() - 4),
                min(cell_rect.height(), fm.height() + 2),
            )
            painter.drawText(
                text_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                self._channel_display_name(channel_idx),
            )

    def _draw_group_titles(self, painter: QPainter):
        if not self._group_titles:
            return
        painter.setFont(self._font)
        for group_name, rect in self._group_titles:
            if not group_name:
                continue
            painter.setPen(self._TEXT_COLOR)
            title_rect = QRect(rect.left(), max(0, rect.top() - self._GROUP_GAP), rect.width(), self._GROUP_GAP)
            painter.drawText(title_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, group_name)
            text_width_pixels = self._font_metrics.horizontalAdvance(group_name)
            painter.setPen(QPen(self._GRID_COLOR, 1))
            line_y = max(0, rect.top() - 1)
            painter.drawLine(rect.left(), line_y, max(rect.left(), rect.right() - text_width_pixels - 10), line_y)

    def _draw_add_ons(self, z_index_from: int, z_index_to: int, painter: QPainter):
        cur_add_ons = []
        for add_on in self._viewable_add_ons:
            if not (z_index_from <= getattr(add_on, "Z_INDEX", -1) <= z_index_to):
                continue
            cur_add_ons.append(add_on)

        if cur_add_ons:
            cur_pen, cur_brush, cur_font = painter.pen(), painter.brush(), painter.font()
            for add_on in cur_add_ons:
                try:
                    add_on_data_dir = self._add_ons_data_dir
                    add_on_module_name = getattr(add_on, "_weegit_module_name", None)
                    if add_on_data_dir is not None and add_on_module_name:
                        add_on_data_dir = add_on_data_dir / str(add_on_module_name)

                    add_on.view(
                        add_on_data_dir=add_on_data_dir,

                        processed_data=self._processed_data,
                        voltage_scale=self._voltage_scale,
                        start_point=self._axis_start_point,
                        duration_ms=self._axis_duration_ms,
                        start_time_ms=self._start_time_ms,
                        end_time_ms=self._end_time_ms,
                        sample_rate=self._sample_rate,
                        axis_duration_ms=self._axis_duration_ms,
                        sweep_idx=self._current_sweep_idx,

                        visible_channel_indexes=self._visible_channel_indexes,
                        channel_names=self._channel_names,
                        visible_events=self._visible_events,
                        visible_periods=self._visible_periods,
                        channel_groups=self._group_layouts,
                        channels_setup=self._channels_setup,

                        painter=painter,
                        signal_widget=self,
                        channel_rects=self._digital_channel_rects,
                        signal_width=self._axis_width,
                        draw_area_height=self._draw_area_height,
                        bg_color=self._BG_COLOR,
                        grid_color=self._GRID_COLOR,
                        signal_color=self._SIGNAL_COLOR,
                        text_color=self._TEXT_COLOR,
                        axis_color=self._AXIS_COLOR,
                    )
                except Exception as e:
                    weegit_logger().debug(str(e))
                    continue

            painter.setPen(cur_pen)
            painter.setBrush(cur_brush)
            painter.setFont(cur_font)

    def _draw_time_axis(self, painter: QPainter, width: int, height: int):
        if self._axis_duration_ms <= 0:
            return

        axis_rect_top = max(0, height - self._bottom_margin)
        axis_y = axis_rect_top + min(5, self._bottom_margin // 6)
        axis_start_x = self._left_margin
        axis_end_x = max(axis_start_x, width - self._right_margin)
        axis_width = axis_end_x - axis_start_x
        if axis_width <= 0:
            return

        painter.fillRect(0, axis_rect_top, width, height - axis_rect_top, self._BG_COLOR)

        pen = QPen(self._AXIS_COLOR, 2)
        painter.setPen(pen)
        painter.drawLine(axis_start_x, axis_y, axis_end_x, axis_y)

        visible_points = int((self._axis_duration_ms / 1000.0) * self._sample_rate)
        if visible_points <= 0:
            return

        total_time_ms = self._end_time_ms - self._start_time_ms
        if total_time_ms <= 0:
            return

        target_ticks = 8
        rough_interval = total_time_ms / target_ticks
        if rough_interval <= 0:
            return

        exponent = math.floor(math.log10(rough_interval))
        mantissa = rough_interval / (10 ** exponent)

        if mantissa < 1.5:
            tick_interval = 10 ** exponent
        elif mantissa < 3:
            tick_interval = 2 * 10 ** exponent
        elif mantissa < 7:
            tick_interval = 5 * 10 ** exponent
        else:
            tick_interval = 10 ** (exponent + 1)

        painter.setFont(self._font)
        painter.setPen(self._AXIS_COLOR)

        time_ms = math.ceil(self._start_time_ms / tick_interval) * tick_interval
        label_offset = 8
        while time_ms <= self._end_time_ms:
            x = axis_start_x + ((time_ms - self._start_time_ms) / self._axis_duration_ms) * axis_width
            painter.drawLine(int(x), axis_y, int(x), axis_y + 6)
            label = milliseconds_to_readable(time_ms, wrap=False)
            text_rect = QRect(int(x) - 50, axis_y + label_offset, 100, 15)
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, label)

            time_ms += tick_interval

    def _draw_events(self, painter: QPainter):
        """Draw vertical lines for events inside each enabled channel cell."""
        if not self._visible_events or self._axis_duration_ms <= 0 or self._sample_rate <= 0:
            return

        for event in self._visible_events:
            rel = (event.time_ms - self._start_time_ms) / self._axis_duration_ms
            painter.setPen(QPen(self.top_level_event_color(event), 1.5))
            for rect in self._marker_target_rects():
                x_int = int(rect.left() + rel * rect.width())
                painter.drawLine(x_int, rect.top(), x_int, rect.bottom())

    def _marker_target_rects(self):
        """Rects (enabled channel cells + auxiliary group rects) to draw markers on."""
        for _channel_idx, cell_rect, enabled, _count in self._cell_rects:
            if enabled and cell_rect.width() > 0:
                yield cell_rect
        for _group_idx, group_rect in self._auxiliary_group_rects:
            if group_rect.width() > 0:
                yield group_rect

    def _draw_periods(self, painter: QPainter):
        if not self._visible_periods or self._axis_duration_ms <= 0 or self._sample_rate <= 0:
            return

        for period in self._visible_periods:
            color = self.top_level_period_color(period)
            painter.setPen(QPen(color, 1.5))
            for time_ms in (period.start_time_ms, period.end_time_ms):
                if not (self._start_time_ms <= time_ms <= self._end_time_ms):
                    continue
                rel = (time_ms - self._start_time_ms) / self._axis_duration_ms
                for rect in self._marker_target_rects():
                    x_int = int(rect.left() + rel * rect.width())
                    painter.drawLine(x_int, rect.top(), x_int, rect.bottom())

    def top_level_event_color(self, event) -> QColor:
        if getattr(event, "is_bad", False):
            return QColor(255, 0, 0)
        entry = self._events_vocabulary.get(event.event_name_id)
        color = QColor(entry.color if entry else "#0066FF")
        if color.isValid():
            return color
        return QColor("#0066FF")

    def top_level_period_color(self, period) -> QColor:
        entry = self._periods_vocabulary.get(period.period_name_id)
        color = QColor(entry.color if entry and entry.color else "#00AA55")
        if color.isValid():
            return color
        return QColor("#00AA55")

    def _draw_auxiliary_groups(self, painter: QPainter, processed_data):
        for group_idx, group_rect in self._auxiliary_group_rects:
            if group_rect.height() <= 0:
                continue
            center_y = group_rect.top() + group_rect.height() / 2.0
            painter.setPen(QPen(self._GRID_COLOR, 1, Qt.PenStyle.DotLine))
            painter.drawLine(group_rect.left(), int(center_y), group_rect.right(), int(center_y))

            channels = self._group_layouts[group_idx].visible_channels()
            for channel_idx in channels:
                channel_data = processed_data.get(channel_idx)
                if channel_data is None or len(channel_data) < 2:
                    continue
                setup = self._channels_setup.get(channel_idx)
                scale = float(getattr(setup, "scale", 1.0))
                y_offset = float(getattr(setup, "y_offset", 0.0))
                color_str = str(getattr(setup, "color", "#000000"))
                self._draw_auxiliary_trace(
                    painter=painter,
                    channel_data=channel_data,
                    channel_idx=channel_idx,
                    group_rect=group_rect,
                    center_y=center_y,
                    scale=scale,
                    y_offset=y_offset,
                    color_str=color_str,
                )

    def _draw_auxiliary_trace(
        self,
        painter: QPainter,
        channel_data: np.ndarray,
        channel_idx: int,
        group_rect: QRect,
        center_y: float,
        scale: float,
        y_offset: float,
        color_str: str,
    ):
        color = QColor(color_str)
        if not color.isValid():
            color = self._SIGNAL_COLOR
        painter.setPen(QPen(color, 1.2))

        n_points = len(channel_data)
        left = group_rect.left()
        x_coords = self._get_cached_x_coords(group_rect.width(), n_points)
        safe_scale = scale if scale > 0 else 1.0
        pixel_per_uv = group_rect.height() / safe_scale
        y_offsets = (channel_data + y_offset) * pixel_per_uv
        y_coords = center_y - y_offsets

        line_buffer = self._get_line_buffer((1, channel_idx), n_points - 1)
        draw_count = 0
        for i in range(n_points - 1):
            y0 = float(y_coords[i])
            y1 = float(y_coords[i + 1])
            if y0 < group_rect.top() or y1 < group_rect.top() or y0 > group_rect.bottom() or y1 > group_rect.bottom():
                continue
            line_buffer[draw_count].setLine(left + float(x_coords[i]), y0, left + float(x_coords[i + 1]), y1)
            draw_count += 1
        if draw_count:
            painter.drawLines(line_buffer[:draw_count])

    def _draw_middle_line(self, painter, channel_rect):
        zero_y = channel_rect.top() + channel_rect.height() // 2
        pen = QPen(self._GRID_COLOR, 2, Qt.PenStyle.DotLine)
        painter.setPen(pen)
        painter.drawLine(channel_rect.left(), zero_y, channel_rect.right(), zero_y)

    def _draw_trace(self, painter: QPainter, channel_data: np.ndarray, channel_rect: QRect,
                    voltage_scale, channel_idx: int, cur_draw_idx: int):
        if channel_data is None or len(channel_data) < 2:
            return

        setup = self._channels_setup.get(channel_idx)
        color = QColor(str(getattr(setup, "color", "#000000")))
        if not color.isValid():
            color = self._SIGNAL_COLOR
        y_offset = float(getattr(setup, "y_offset", 0.0))
        pen = QPen(color, 1.5)
        painter.setPen(pen)

        n_points = len(channel_data)
        left = channel_rect.left()
        x_coords = self._get_cached_x_coords(channel_rect.width(), n_points)

        scale_factor = self.get_channel_scale(channel_idx)
        # Per-channel scale defines full µV amplitude in the channel height.
        full_uv_scale = max(scale_factor, 1e-12)
        pixel_per_uv = channel_rect.height() / full_uv_scale
        channel_mid_y = channel_rect.top() + channel_rect.height() / 2.0
        y_offsets = (channel_data + y_offset) * pixel_per_uv
        y_coords = channel_mid_y - y_offsets
        if self._cut_traces:
            clip_rect = channel_rect
        else:
            clip_rect = self._channel_group_rects.get(channel_idx, channel_rect)
        clip_top = clip_rect.top()
        clip_bottom = clip_rect.bottom()

        line_buffer = self._get_line_buffer((0, cur_draw_idx), n_points - 1)
        draw_count = 0
        for i in range(n_points - 1):
            y0 = float(y_coords[i])
            y1 = float(y_coords[i + 1])
            if y0 < clip_top or y1 < clip_top or y0 > clip_bottom or y1 > clip_bottom:
                continue
            line_buffer[draw_count].setLine(
                left + float(x_coords[i]),
                y0,
                left + float(x_coords[i + 1]),
                y1
            )
            draw_count += 1

        if draw_count:
            painter.drawLines(line_buffer[:draw_count])

    def get_channel_scale(self, channel_idx: int) -> float:
        setup = self._channels_setup.get(channel_idx)
        if setup is None:
            return 1.0
        return float(getattr(setup, "scale", 1.0) or 1.0)

    def get_channels_in_y_range(self, y_min: int, y_max: int) -> List[int]:
        y1, y2 = sorted((int(y_min), int(y_max)))
        selected: List[int] = []
        for channel_idx, rect in self._digital_channel_rects:
            if rect.bottom() < y1 or rect.top() > y2:
                continue
            selected.append(channel_idx)
        return selected

    def get_channels_in_rect(self, rect: QRect) -> List[int]:
        """Channels whose cell (or aux group) intersects the selection rectangle."""
        selected: List[int] = []
        seen = set()
        for channel_idx, cell_rect, enabled, _count in self._cell_rects:
            if not enabled or channel_idx in seen:
                continue
            if cell_rect.intersects(rect):
                selected.append(channel_idx)
                seen.add(channel_idx)
        for group_idx, group_rect in self._auxiliary_group_rects:
            if not group_rect.intersects(rect):
                continue
            for channel_idx in self._group_layouts[group_idx].visible_channels():
                if channel_idx not in seen:
                    selected.append(channel_idx)
                    seen.add(channel_idx)
        return selected

    def is_auxiliary_y(self, y: int) -> bool:
        for _idx, rect in self._auxiliary_group_rects:
            if rect.top() <= y <= rect.bottom():
                return True
        return False

    def get_scale_for_non_aux_y(self, y: int) -> Optional[float]:
        """Return group scale for non-aux area at Y, if available."""
        for group_idx, rect in self._non_aux_group_rects:
            if not (rect.top() <= y <= rect.bottom()):
                continue
            channels = self._group_layouts[group_idx].visible_channels()
            if not channels:
                return None
            return self.get_channel_scale(channels[0])
        return None

    def _value_to_pixel_voltage(self, value, voltage_scale, channel_idx: Optional[int] = None):
        """Convert µV value to normalized channel-height pixels (0..1 height basis)."""
        if channel_idx is not None:
            scale_factor = self.get_channel_scale(channel_idx)
        else:
            scale_factor = max(voltage_scale, 1.0)

        full_uv_scale = max(scale_factor, 1e-12)
        return value / full_uv_scale

    def _get_cached_x_coords(self, signal_width: int, n_points: int) -> np.ndarray:
        """Cache evenly-spaced X coordinates keyed by (width, data length).

        Multiple distinct widths coexist (cells of different columns/groups), so
        a dict cache avoids thrashing when redrawing across columns.
        """
        cache_key = (int(signal_width), int(n_points))
        cached = self._x_coords_cache.get(cache_key)
        if cached is not None:
            return cached

        if n_points < 2 or signal_width <= 0:
            coords = np.array([0.0], dtype=np.float32)
        else:
            coords = np.linspace(0.0, signal_width - 1, n_points, dtype=np.float32)

        if len(self._x_coords_cache) > 64:
            self._x_coords_cache.clear()
        self._x_coords_cache[cache_key] = coords
        return coords

    def _get_line_buffer(self, cache_key: Tuple[int, int], required: int) -> List[QLineF]:
        """Ensure a reusable QLineF buffer exists for the channel."""
        buffer = self._lines_cache.setdefault(cache_key, [])
        missing = required - len(buffer)
        if missing > 0:
            buffer.extend(QLineF() for _ in range(missing))
        return buffer

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._overlay_widget:
            self._overlay_widget.setGeometry(self.rect())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), self._BG_COLOR)
        if not self.pixmap_cache.isNull():
            painter.drawPixmap(self._signal_pixmap_offset, self.pixmap_cache)

        self._draw_time_axis(painter, self.width(), self.height())

    def group_render_rects(self) -> List[QRect]:
        """Group rects aligned to the shown-group order (see get_visible_groups_layout)."""
        return [QRect(rect) for rect in self._group_layout_rects]

    def cell_time_ms(self, pos: QPoint) -> Optional[float]:
        """Absolute time (ms) for a point inside the channel cell/aux group under the cursor."""
        if self._axis_duration_ms <= 0:
            return None
        for _channel_idx, cell_rect, _enabled, _count in self._cell_rects:
            if cell_rect.contains(pos) and cell_rect.width() > 0:
                rel = (pos.x() - cell_rect.left()) / cell_rect.width()
                rel = max(0.0, min(1.0, rel))
                return self._start_time_ms + rel * self._axis_duration_ms
        for _group_idx, group_rect in self._auxiliary_group_rects:
            if group_rect.contains(pos) and group_rect.width() > 0:
                rel = (pos.x() - group_rect.left()) / group_rect.width()
                rel = max(0.0, min(1.0, rel))
                return self._start_time_ms + rel * self._axis_duration_ms
        return None

    def time_ms_at_x(self, x: int) -> Optional[float]:
        """Absolute time (ms) for a given X, using any cell column spanning that X."""
        if self._axis_duration_ms <= 0:
            return None
        for _channel_idx, cell_rect, _enabled, _count in self._cell_rects:
            if cell_rect.left() <= x <= cell_rect.right() and cell_rect.width() > 0:
                rel = (x - cell_rect.left()) / cell_rect.width()
                rel = max(0.0, min(1.0, rel))
                return self._start_time_ms + rel * self._axis_duration_ms
        return None

    def measure_rect_at(self, pos: QPoint) -> Optional[QRect]:
        """Cell rect (or group rect) under a point, used to scale the measure bar.

        The measure bar's time/voltage span must reflect the cell/group where the
        cursor is, since each cell maps the full time window across its own width.
        """
        for _channel_idx, cell_rect, _enabled, _count in self._cell_rects:
            if cell_rect.contains(pos):
                return QRect(cell_rect)
        for _group_idx, group_rect in self._non_aux_group_rects:
            if group_rect.contains(pos):
                return QRect(group_rect)
        for _group_idx, group_rect in self._auxiliary_group_rects:
            if group_rect.contains(pos):
                return QRect(group_rect)
        return None


class OverlayModeEnum(Enum):
    NONE = 0
    TIME_VOLTAGE_BAR = 1
    EVENT_ADD = 2
    EVENT_BAD_SET = 3
    EVENT_BAD_UNSET = 4
    EVENT_REMOVE = 5
    PERIOD_ADD = 6
    FULL_VIEW_SELECT = 7


class MeasureBarStateEnum(Enum):
    HIDDEN = 0
    FOLLOW_CURSOR = 1
    FROZEN = 2


class OverlayWidget(QWidget):
    """Transparent overlay that draws time/voltage scale bars at the cursor."""

    def __init__(self, left_margin, right_margin, bottom_margin, bar_width, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self._left_margin = left_margin
        self._right_margin = right_margin
        self._bottom_margin = bottom_margin
        self._bar_width = bar_width

        self._cursor_pos: Optional[QPoint] = None
        self._overlay_mode = OverlayModeEnum.NONE
        self._channel_height = 0
        self._duration_ms = 0.0
        self._time_axis_width = 0
        self._start_time_ms = 0.0
        self._current_sweep_idx = 0
        self._selection_start_time_ms: Optional[float] = None
        self._selection_start_pos: Optional[Tuple[int, float]] = None
        self._selection_start_pixel_pos: Optional[QPoint] = None
        self._scale_value = 1.0
        self._font = QFont()
        self._font.setPointSize(16)
        self._font_metrics = QFontMetrics(self._font)

    def update_state(self, *, cursor_pos: Optional[QPoint], overlay_mode: OverlayModeEnum,
                     channel_height: int, duration_ms: float, scale_value: float,
                     start_time_ms: float, current_sweep_idx: int,
                     selection_start_time_ms: Optional[float],
                     selection_start_pos: Optional[Tuple[int, float]],
                     selection_start_pixel_pos: Optional[QPoint],
                     time_axis_width: int = 0):
        self._cursor_pos = cursor_pos
        self._overlay_mode = overlay_mode
        self._channel_height = max(0, channel_height)
        self._duration_ms = max(0.0, duration_ms)
        self._time_axis_width = max(0, int(time_axis_width))
        self._scale_value = scale_value if scale_value > 0 else 1.0
        self._start_time_ms = start_time_ms
        self._current_sweep_idx = int(current_sweep_idx)
        self._selection_start_time_ms = selection_start_time_ms
        self._selection_start_pos = selection_start_pos
        self._selection_start_pixel_pos = selection_start_pixel_pos
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if not self._cursor_pos:
            return

        # Crosshair for interactive modes
        if self._overlay_mode in (
                OverlayModeEnum.EVENT_ADD,
                OverlayModeEnum.EVENT_BAD_SET,
                OverlayModeEnum.EVENT_BAD_UNSET,
                OverlayModeEnum.EVENT_REMOVE,
                OverlayModeEnum.PERIOD_ADD,
                OverlayModeEnum.FULL_VIEW_SELECT,
        ):
            pen = QPen(Qt.GlobalColor.green, 1, Qt.PenStyle.SolidLine)
            painter.setPen(pen)
            painter.drawLine(0, self._cursor_pos.y(), self.width(), self._cursor_pos.y())
            painter.drawLine(self._cursor_pos.x(), 0, self._cursor_pos.x(), self.height())
            self._draw_mode_label(painter)

            if self._overlay_mode == OverlayModeEnum.FULL_VIEW_SELECT and self._selection_start_pixel_pos is not None:
                self._draw_rectangle_selection_area(painter)

        elif self._overlay_mode == OverlayModeEnum.TIME_VOLTAGE_BAR:
            painter.setPen(QPen(QColor(255, 0, 0)))
            painter.setFont(self._font)
            self._draw_voltage_scale_bar(painter)
            self._draw_time_scale_bar(painter)

    def _signal_width(self) -> int:
        return max(0, self.width() - self._left_margin - self._right_margin)

    def _axis_start_x(self) -> int:
        return self._left_margin

    def _axis_end_x(self) -> int:
        return self._axis_start_x() + self._signal_width()

    def _time_to_x(self, time_ms: float) -> Optional[float]:
        """Map absolute time in ms to X coordinate within the signal area."""
        signal_width = self._signal_width()
        if signal_width <= 0 or self._duration_ms <= 0:
            return None

        axis_start_x = self._axis_start_x()
        rel = (time_ms - self._start_time_ms) / self._duration_ms
        return axis_start_x + rel * signal_width

    def _draw_mode_label(self, painter: QPainter):
        """Draw mode name slightly to the bottom-right of the crosshair."""
        painter.setFont(self._font)
        mode_labels = {
            OverlayModeEnum.EVENT_ADD: "Add event",
            OverlayModeEnum.EVENT_BAD_SET: "Set bad event",
            OverlayModeEnum.EVENT_BAD_UNSET: "Unset bad event",
            OverlayModeEnum.EVENT_REMOVE: "Remove",
            OverlayModeEnum.PERIOD_ADD: "Add period",
            OverlayModeEnum.FULL_VIEW_SELECT: "Full view area",
        }
        label = mode_labels.get(self._overlay_mode)
        if not label:
            return

        # Two-point modes annotate the current step: (from) then (to).
        two_point_modes = (
            OverlayModeEnum.EVENT_BAD_SET,
            OverlayModeEnum.EVENT_BAD_UNSET,
            OverlayModeEnum.EVENT_REMOVE,
            OverlayModeEnum.PERIOD_ADD,
        )
        if self._overlay_mode in two_point_modes:
            has_first_point = self._selection_start_time_ms is not None
            label = f"{label} (to)" if has_first_point else f"{label} (from)"

        text_width = self._font_metrics.horizontalAdvance(label) + 8
        text_height = self._font_metrics.height() + 4

        x = self._cursor_pos.x() + 6
        y = self._cursor_pos.y() + 6

        # Ensure label stays within widget bounds
        if x + text_width > self.width():
            x = self.width() - text_width - 2
        if y + text_height > self.height():
            y = self.height() - text_height - 2

        rect = QRect(int(x), int(y), int(text_width), int(text_height))
        # Background
        bg_color = QColor(255, 255, 255, 220)
        painter.fillRect(rect, bg_color)
        # Text
        painter.setPen(QColor(0, 0, 0))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)

    def _draw_rectangle_selection_area(self, painter: QPainter):
        if self._selection_start_pixel_pos is None:
            return
        signal_left = self._left_margin
        signal_right = max(signal_left, self.width() - self._right_margin)
        signal_top = 0
        signal_bottom = max(0, self.height() - self._bottom_margin)

        x1 = max(signal_left, min(signal_right, self._selection_start_pixel_pos.x()))
        y1 = max(signal_top, min(signal_bottom, self._selection_start_pixel_pos.y()))
        x2 = max(signal_left, min(signal_right, self._cursor_pos.x()))
        y2 = max(signal_top, min(signal_bottom, self._cursor_pos.y()))
        left, right = sorted((x1, x2))
        top, bottom = sorted((y1, y2))
        if right <= left or bottom <= top:
            return

        painter.fillRect(QRect(left, top, right - left, bottom - top), QColor(0, 120, 255, 35))
        painter.setPen(QPen(QColor(0, 120, 255), 1, Qt.PenStyle.DashLine))
        painter.drawRect(QRect(left, top, right - left, bottom - top))

    def _draw_voltage_scale_bar(self, painter: QPainter):
        bar_height = self._channel_height // settings.MEASURE_BAR_DIVIDER
        if bar_height <= 0:
            return

        x = self._cursor_pos.x() - self._bar_width // 2
        y = self._cursor_pos.y() - bar_height

        painter.fillRect(int(x), int(y), self._bar_width, bar_height, QColor(255, 0, 0))

        value = self._scale_value / settings.MEASURE_BAR_DIVIDER
        label_text = f"{value:.1f} µV"
        x_size = self._font_metrics.horizontalAdvance(label_text) + 10
        label_rect = QRect(int(x) - x_size, int(y + bar_height // 2), x_size, 16)
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, label_text)

    def _draw_time_scale_bar(self, painter: QPainter):
        # Use the width of the cell/group under the cursor: each cell maps the full
        # time window across its own width, so time-per-pixel is duration / cell width.
        axis_width = self._time_axis_width if self._time_axis_width > 0 else self._signal_width()
        if axis_width <= 0 or self._duration_ms <= 0:
            return

        time_bar_pixels = max(10, min(axis_width // 10, 120))
        y = self._cursor_pos.y() - self._bar_width
        x = self._cursor_pos.x()
        x = max(0, min(x, self.width() - self._right_margin - time_bar_pixels))

        painter.fillRect(int(x), int(y), time_bar_pixels, self._bar_width, QColor(255, 0, 0))

        time_value_ms = (time_bar_pixels / axis_width) * self._duration_ms
        if time_value_ms < 1000:
            label_text = f"{time_value_ms:.1f} ms"
        else:
            label_text = f"{time_value_ms / 1000:.2f} s"

        # Draw the full label (don't clip to the tick width); clamp inside widget.
        text_width = self._font_metrics.horizontalAdvance(label_text) + 10
        label_x = int(x)
        if label_x + text_width > self.width():
            label_x = self.width() - text_width
        label_x = max(0, label_x)
        label_rect = QRect(label_x, int(y) + self._bar_width + 2, text_width, 16)
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label_text)


class GroupNavigatorWidget(QWidget):
    """Small clickable minimap placed at the bottom-right of a channel group.

    Shows four navigation arrows and a map where the outer rectangle is the full
    channel grid (rows_num x columns_num) and the inner rectangle is the visible
    window (rows_num_to_show x columns_num_to_show) offset by (cur_row, cur_col).
    """

    position_changed = pyqtSignal(int, int, int)  # group_idx, cur_row_idx, cur_column_idx

    _ARROW_SIZE = 12
    _MAP_MARGIN = 4

    def __init__(self, parent=None):
        super().__init__(parent)
        self._group_idx = -1
        self._rows_num = 1
        self._cols_num = 1
        self._rows_to_show = 1
        self._cols_to_show = 1
        self._cur_row = 0
        self._cur_col = 0
        self._bg = QColor(255, 255, 255, 210)
        self._border = QColor(120, 120, 120)
        self._arrow = QColor(80, 80, 80)
        self._window = QColor(0, 120, 255, 90)
        self._map_rect = QRect()
        self._arrow_rects: Dict[str, QRect] = {}
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_state(self, group_idx: int, rows_num: int, cols_num: int,
                  rows_to_show: int, cols_to_show: int, cur_row: int, cur_col: int):
        self._group_idx = group_idx
        self._rows_num = max(1, int(rows_num))
        self._cols_num = max(1, int(cols_num))
        self._rows_to_show = max(1, min(int(rows_to_show), self._rows_num))
        self._cols_to_show = max(1, min(int(cols_to_show), self._cols_num))
        self._cur_row = max(0, min(int(cur_row), self._rows_num - self._rows_to_show))
        self._cur_col = max(0, min(int(cur_col), self._cols_num - self._cols_to_show))
        self.update()

    def needs_navigation(self) -> bool:
        return self._rows_num > self._rows_to_show or self._cols_num > self._cols_to_show

    def _compute_layout(self):
        arrow = self._ARROW_SIZE
        margin = self._MAP_MARGIN
        # Cross of arrows occupies the left square area, map on the right.
        cross_w = arrow * 3
        self._arrow_rects = {
            "up": QRect(margin + arrow, margin, arrow, arrow),
            "left": QRect(margin, margin + arrow, arrow, arrow),
            "right": QRect(margin + arrow * 2, margin + arrow, arrow, arrow),
            "down": QRect(margin + arrow, margin + arrow * 2, arrow, arrow),
        }
        map_left = margin + cross_w + margin
        map_w = max(10, self.width() - map_left - margin)
        map_h = max(10, self.height() - 2 * margin)
        self._map_rect = QRect(map_left, margin, map_w, map_h)

    def paintEvent(self, event):
        self._compute_layout()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), self._bg)
        painter.setPen(QPen(self._border, 1))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))

        painter.setPen(QPen(self._arrow, 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for direction, rect in self._arrow_rects.items():
            self._draw_arrow(painter, rect, direction)

        # Outer full-grid rectangle
        painter.setPen(QPen(self._border, 1))
        painter.drawRect(self._map_rect)
        cell_w = self._map_rect.width() / self._cols_num
        cell_h = self._map_rect.height() / self._rows_num
        inner = QRect(
            int(self._map_rect.left() + self._cur_col * cell_w),
            int(self._map_rect.top() + self._cur_row * cell_h),
            max(2, int(self._cols_to_show * cell_w)),
            max(2, int(self._rows_to_show * cell_h)),
        )
        painter.fillRect(inner, self._window)
        painter.setPen(QPen(QColor(0, 90, 200), 1))
        painter.drawRect(inner)

    def _draw_arrow(self, painter: QPainter, rect: QRect, direction: str):
        if direction == "up":
            pts = [QPoint(rect.center().x(), rect.top()), QPoint(rect.left(), rect.bottom()),
                   QPoint(rect.right(), rect.bottom())]
        elif direction == "down":
            pts = [QPoint(rect.left(), rect.top()), QPoint(rect.right(), rect.top()),
                   QPoint(rect.center().x(), rect.bottom())]
        elif direction == "left":
            pts = [QPoint(rect.right(), rect.top()), QPoint(rect.right(), rect.bottom()),
                   QPoint(rect.left(), rect.center().y())]
        else:  # right
            pts = [QPoint(rect.left(), rect.top()), QPoint(rect.left(), rect.bottom()),
                   QPoint(rect.right(), rect.center().y())]
        painter.drawPolygon(*pts)

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position().toPoint()
        new_row, new_col = self._cur_row, self._cur_col
        max_row = self._rows_num - self._rows_to_show
        max_col = self._cols_num - self._cols_to_show
        handled = False
        for direction, rect in self._arrow_rects.items():
            if rect.contains(pos):
                if direction == "up":
                    new_row -= 1
                elif direction == "down":
                    new_row += 1
                elif direction == "left":
                    new_col -= 1
                elif direction == "right":
                    new_col += 1
                handled = True
                break
        if not handled and self._map_rect.contains(pos):
            cell_w = self._map_rect.width() / self._cols_num
            cell_h = self._map_rect.height() / self._rows_num
            target_col = int((pos.x() - self._map_rect.left()) / max(1e-6, cell_w)) - self._cols_to_show // 2
            target_row = int((pos.y() - self._map_rect.top()) / max(1e-6, cell_h)) - self._rows_to_show // 2
            new_row, new_col = target_row, target_col
            handled = True
        if not handled:
            return
        new_row = max(0, min(new_row, max(0, max_row)))
        new_col = max(0, min(new_col, max(0, max_col)))
        if new_row == self._cur_row and new_col == self._cur_col:
            return
        self._cur_row, self._cur_col = new_row, new_col
        self.update()
        self.position_changed.emit(self._group_idx, new_row, new_col)


class SignalPanel(QWidget):
    """High-performance EEG signal visualization panel with scrolling and optimization"""
    channel_scroll_changed = pyqtSignal()

    def __init__(self, session_manager, parent=None):
        super().__init__(parent)

        self._session_manager: QtWeegitSessionManagerWrapper = session_manager
        self._cached_processed_data: Dict[int, np.ndarray[np.float64]] = {}

        # Scale bar
        self._current_overlay_mode = OverlayModeEnum.NONE
        self._current_mouse_pos = None
        self._measure_bar_state = MeasureBarStateEnum.HIDDEN
        self._frozen_measure_pos: Optional[QPoint] = None
        self._BAR_WIDTH = 3
        self._current_event_add_id: Optional[int] = None
        self._current_event_edit_mode: Optional[OverlayModeEnum] = None
        self._current_event_edit_first_sweep_idx: Optional[int] = None
        self._current_event_edit_first_time_ms: Optional[float] = None
        self._current_period_add_id: Optional[int] = None
        self._current_period_add_first_point: Optional[Tuple[int, float]] = None  # (sweep_idx, time_ms)
        self._full_view_first_point: Optional[QPoint] = None
        self._full_view_windows: List[QDialog] = []

        # UI constants
        self._TOP_MARGIN = 30  # Space for the event navigator (now at the bottom)
        self._BOTTOM_MARGIN = 30  # Space for time axis
        self._LEFT_MARGIN = 0  # Names are drawn inside channel cells now
        self._RIGHT_MARGIN = 20
        self._CHANNEL_SPACING = 5
        self._NAV_WIDTH = 96
        self._NAV_HEIGHT = 60
        self._NAV_MARGIN = 6

        self._channel_height = 60

        # Per-group navigation minimaps
        self._group_navigators: Dict[int, GroupNavigatorWidget] = {}
        self._cached_group_layouts_override: Optional[List[ChannelGroup]] = None
        self._cached_visible_channels_override: Optional[List[int]] = None
        self._last_top_navigator_key: Optional[Tuple] = None

        # Colors and styles
        self._bg_color = QColor(240, 240, 240)
        self._grid_color = QColor(200, 200, 200)
        self._SIGNAL_COLOR = QColor(0, 0, 0)
        self._text_color = QColor(0, 0, 0)
        self._axis_color = QColor(100, 100, 100)

        self.setup_ui()
        self.connect_signals()
        self._start_time_ms = 0.0
        self._end_time_ms = 0.0
        self._auto_scroll_timer = QTimer(self)
        self._auto_scroll_timer.setInterval(settings.AUTO_SCROLL_STEP_INTERVAL_MS)
        self._auto_scroll_timer.timeout.connect(self._on_auto_scroll_tick)
        self._auto_scroll_direction = 0
        self._is_signal_drag_active = False
        self._signal_drag_last_x: Optional[int] = None
        self._signal_drag_samples_residual = 0.0

    def setup_ui(self):
        """Setup the UI: signal area, bottom event navigator and time controls."""
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(600, 400)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Signal display area (fills the whole content area now)
        self.signal_widget = SignalWidget(self._LEFT_MARGIN, self._RIGHT_MARGIN, self._BOTTOM_MARGIN)
        self.signal_widget.setMouseTracking(True)
        self.signal_widget.installEventFilter(self)
        self.overlay_widget = OverlayWidget(self._LEFT_MARGIN, self._RIGHT_MARGIN,
                                            self._BOTTOM_MARGIN, self._BAR_WIDTH, self.signal_widget, )
        self.signal_widget.set_overlay_widget(self.overlay_widget)
        main_layout.addWidget(self.signal_widget, 4)

        # Event navigator (names + arrows), moved below the signal area
        self.top_navigator_widget = TopNavigatorWidget(self._LEFT_MARGIN, self._RIGHT_MARGIN)
        self.top_navigator_widget.setFixedHeight(self._TOP_MARGIN)
        main_layout.addWidget(self.top_navigator_widget)
        self.top_navigator_widget.event_navigation_requested.connect(
            self._session_manager.set_start_point
        )

        # Bottom time axis and horizontal scrollbar
        bottom_layout = QHBoxLayout()

        # Double left arrow
        self.btn_double_left = QPushButton("<<")
        self.btn_double_left.setFixedWidth(40)
        bottom_layout.addWidget(self.btn_double_left)

        # Single left arrow
        self.btn_single_left = QPushButton("<")
        self.btn_single_left.setFixedWidth(30)
        bottom_layout.addWidget(self.btn_single_left)

        # Horizontal scrollbar
        self.time_scrollbar = QScrollBar(Qt.Orientation.Horizontal)
        self._apply_scrollbar_style(self.time_scrollbar)
        bottom_layout.addWidget(self.time_scrollbar, 1)

        # Single right arrow
        self.btn_single_right = QPushButton(">")
        self.btn_single_right.setFixedWidth(30)
        bottom_layout.addWidget(self.btn_single_right)

        # Double right arrow
        self.btn_double_right = QPushButton(">>")
        self.btn_double_right.setFixedWidth(40)
        bottom_layout.addWidget(self.btn_double_right)

        main_layout.addLayout(bottom_layout)

    def connect_signals(self):
        """Connect all signals to their handlers"""
        # Time parameter changes
        self.btn_double_left.clicked.connect(self.on_double_left_click)
        self.btn_single_left.clicked.connect(self.on_single_left_click)
        self.time_scrollbar.valueChanged.connect(self.on_time_scroll)
        self.btn_single_right.clicked.connect(self.on_single_right_click)
        self.btn_double_right.clicked.connect(self.on_double_right_click)

        self._session_manager.session_loaded.connect(self.on_session_loaded)
        self._session_manager.start_point_changed.connect(self.on_start_point_changed)
        self._session_manager.duration_ms_changed.connect(lambda _duration: self._update_time_scrollbar())
        self._session_manager.current_sweep_idx_changed.connect(lambda _idx: self.on_session_loaded())
        self._session_manager.channels_groups_changed.connect(self._on_channels_groups_changed)
        self._session_manager.channel_setup_changed.connect(self._redraw_data)

    @staticmethod
    def _apply_scrollbar_style(scrollbar: QScrollBar):
        """Hide native arrow buttons to keep custom controls only."""
        scrollbar.setStyleSheet("""
            QScrollBar:horizontal, QScrollBar:vertical {
                background: rgb(230, 230, 230);
                margin: 0px;
                border: none;
            }
            QScrollBar::handle:horizontal, QScrollBar::handle:vertical {
                background: rgb(170, 170, 170);
                border-radius: 3px;
            }
            QScrollBar::handle:horizontal {
                min-width: 20px;
            }
            QScrollBar::handle:vertical {
                min-height: 20px;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0px;
                border: none;
                background: transparent;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
                border: none;
                background: transparent;
            }
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal,
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: rgb(230, 230, 230);
            }
        """)

    def _can_drag_signal_x(self) -> bool:
        return self._current_overlay_mode in (OverlayModeEnum.NONE, OverlayModeEnum.TIME_VOLTAGE_BAR)

    def _start_signal_drag(self, x_pos: int):
        if not self._can_drag_signal_x():
            return
        if not self._session_manager.gui_setup or not self._session_manager.header:
            return
        self._is_signal_drag_active = True
        self._signal_drag_last_x = int(x_pos)
        self._signal_drag_samples_residual = 0.0
        if self._auto_scroll_timer.isActive():
            self._auto_scroll_timer.stop()
            self._auto_scroll_direction = 0
        self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def _stop_signal_drag(self):
        if not self._is_signal_drag_active:
            return
        self._is_signal_drag_active = False
        self._signal_drag_last_x = None
        self._signal_drag_samples_residual = 0.0
        if self._current_overlay_mode == OverlayModeEnum.FULL_VIEW_SELECT:
            self.setCursor(Qt.CursorShape.BlankCursor)
        elif self._should_hide_cursor():
            self.setCursor(Qt.CursorShape.BlankCursor)
        else:
            self.unsetCursor()

    def _drag_signal_to_x(self, x_pos: int):
        if (not self._is_signal_drag_active or self._signal_drag_last_x is None
                or not self._session_manager.gui_setup or not self._session_manager.header):
            return

        current_x = int(x_pos)
        dx = current_x - self._signal_drag_last_x
        if dx == 0:
            return
        self._signal_drag_last_x = current_x

        signal_width = self.signal_widget.width() - self._LEFT_MARGIN - self._RIGHT_MARGIN
        if signal_width <= 0:
            return

        gui_setup = self._session_manager.gui_setup
        sample_rate = self._session_manager.header.sample_rate
        visible_points = (gui_setup.duration_ms / 1000.0) * sample_rate
        if visible_points <= 0:
            return

        samples_per_pixel = visible_points / signal_width
        self._signal_drag_samples_residual += -dx * samples_per_pixel
        delta_samples = int(self._signal_drag_samples_residual)
        if delta_samples == 0:
            return
        self._signal_drag_samples_residual -= delta_samples
        self._session_manager.set_start_point(gui_setup.start_point + delta_samples)

    def eventFilter(self, watched, event):
        if watched is self.signal_widget:
            if event.type() == QEvent.Type.MouseMove and isinstance(event, QMouseEvent):
                pos = event.position().toPoint()
                if self._is_signal_drag_active:
                    if event.buttons() & Qt.MouseButton.LeftButton:
                        self._drag_signal_to_x(pos.x())
                    else:
                        self._stop_signal_drag()
                if self.signal_widget.rect().contains(pos):
                    self._current_mouse_pos = pos
                    if self._is_signal_drag_active:
                        self.setCursor(Qt.CursorShape.ClosedHandCursor)
                    elif self._current_overlay_mode == OverlayModeEnum.FULL_VIEW_SELECT:
                        self.setCursor(Qt.CursorShape.BlankCursor)
                    elif self._should_hide_cursor():
                        self.setCursor(Qt.CursorShape.BlankCursor)
                    else:
                        self.unsetCursor()
                else:
                    self._current_mouse_pos = None
                    if self._is_signal_drag_active:
                        self._stop_signal_drag()
                    else:
                        # Always restore system cursor outside signal area
                        self.unsetCursor()

                self._update_overlay_widget()
            elif event.type() == QEvent.Type.Leave:
                self._current_mouse_pos = None
                self._stop_signal_drag()
                # Always restore system cursor when leaving signal widget
                self.unsetCursor()
                self._update_overlay_widget()
            elif event.type() == QEvent.Type.MouseButtonPress and isinstance(event, QMouseEvent):
                pos = event.position().toPoint()
                button = event.button()
                if self._current_overlay_mode == OverlayModeEnum.EVENT_ADD:
                    if button == Qt.MouseButton.LeftButton:
                        self._handle_event_add_click(event)
                        return True
                    if button == Qt.MouseButton.RightButton:
                        self._stop_event_add_mode()
                        return True
                elif self._current_overlay_mode in (
                        OverlayModeEnum.EVENT_BAD_SET,
                        OverlayModeEnum.EVENT_BAD_UNSET,
                        OverlayModeEnum.EVENT_REMOVE,
                ):
                    if button == Qt.MouseButton.LeftButton:
                        self._handle_event_edit_click(event)
                        return True
                    if button == Qt.MouseButton.RightButton:
                        self._stop_event_edit_mode()
                        return True
                elif self._current_overlay_mode == OverlayModeEnum.PERIOD_ADD:
                    if button == Qt.MouseButton.LeftButton:
                        self._handle_period_add_click(event)
                        return True
                    if button == Qt.MouseButton.RightButton:
                        self._stop_period_add_mode()
                        return True
                elif self._current_overlay_mode == OverlayModeEnum.FULL_VIEW_SELECT:
                    if button == Qt.MouseButton.LeftButton:
                        self._handle_full_view_select_click(event)
                        return True
                    if button == Qt.MouseButton.RightButton:
                        self._stop_full_view_select_mode()
                        return True
                elif (button == Qt.MouseButton.LeftButton
                      and self._can_drag_signal_x()
                      and self._is_point_inside_signal_area(pos)):
                    self._start_signal_drag(pos.x())
                    return True
            elif event.type() == QEvent.Type.MouseButtonRelease and isinstance(event, QMouseEvent):
                if event.button() == Qt.MouseButton.LeftButton and self._is_signal_drag_active:
                    self._stop_signal_drag()
                    return True
        return super().eventFilter(watched, event)

    def reset_data_and_redraw(
            self,
            processed_data,
            *,
            group_layouts: Optional[List[ChannelGroup]] = None,
            visible_channels: Optional[List[int]] = None,
    ):
        self._cached_processed_data = processed_data
        self._cached_group_layouts_override = list(group_layouts) if group_layouts is not None else None
        self._cached_visible_channels_override = list(visible_channels) if visible_channels is not None else None
        self._redraw_data()

    def _on_channels_groups_changed(self, _groups):
        self._cached_group_layouts_override = None
        self._cached_visible_channels_override = None
        self._redraw_data()

    def _redraw_data(self):
        if not self._cached_processed_data:
            return

        gui_setup = self._session_manager.gui_setup
        if not gui_setup:
            return

        sample_rate = self._session_manager.header.sample_rate
        self._start_time_ms = (gui_setup.start_point / sample_rate) * 1000.0
        self._end_time_ms = self._start_time_ms + gui_setup.duration_ms

        all_events = self._session_manager.events if gui_setup.events_are_shown else []
        visible_events = []
        if gui_setup.events_are_shown:
            visible_events = self._get_events_for_current_window(gui_setup)

        all_periods = self._session_manager.periods if gui_setup.periods_are_shown else []
        visible_periods = []
        if gui_setup and gui_setup.periods_are_shown:
            visible_periods = self._get_periods_for_current_window(gui_setup)

        axis_offset_px = 0
        navigator_key = (
            gui_setup.current_sweep_idx,
            gui_setup.start_point,
            gui_setup.duration_ms,
            sample_rate,
            axis_offset_px,
            bool(gui_setup.events_are_shown),
            bool(gui_setup.periods_are_shown),
            tuple(sorted(self._session_manager.events_vocabulary.items())),
            tuple(sorted(self._session_manager.periods_vocabulary.items())),
            tuple((e.event_name_id, e.time_ms, bool(e.is_bad)) for e in visible_events),
            tuple((p.period_name_id, p.start_sweep_idx, p.end_sweep_idx, p.start_time_ms, p.end_time_ms)
                  for p in visible_periods),
        )
        if navigator_key != self._last_top_navigator_key:
            self.top_navigator_widget.update_events(
                all_events=all_events,
                visible_events=visible_events,
                events_vocabulary=self._session_manager.events_vocabulary,
                all_periods=all_periods,
                visible_periods=visible_periods,
                periods_vocabulary=self._session_manager.periods_vocabulary,
                sweep_idx=gui_setup.current_sweep_idx,
                start_point=gui_setup.start_point,
                duration_ms=gui_setup.duration_ms,
                sample_rate=sample_rate,
                start_time_ms=self._start_time_ms,
                header_points_per_sweep=self._sweep_points(gui_setup.current_sweep_idx),
                axis_offset_px=axis_offset_px,
            )
            self._last_top_navigator_key = navigator_key

        # Update signal widget (without event labels)
        group_layouts = self._cached_group_layouts_override
        if group_layouts is None:
            group_layouts = self.get_visible_groups_layout()
        visible_channels = self._cached_visible_channels_override
        if visible_channels is None:
            visible_channels = []
            for group in group_layouts:
                visible_channels.extend(group.visible_channels())
        viewable_add_ons = self._session_manager.get_viewable_add_ons() if self._session_manager else {}
        add_ons_data_dir = None
        if self._session_manager.weegit_experiment_folder:
            add_ons_data_dir = (
                    Path(self._session_manager.weegit_experiment_folder)
                    / settings.ADD_ONS_SUBFOLDER
                    / settings.ADD_ONS_DATA_SUBFOLDER
            )
        self.signal_widget.reset_data_and_redraw(
            self._cached_processed_data,
            visible_channels,
            self._session_manager.header.channel_info.name,
            settings.DEFAULT_SCALE,
            group_layouts=group_layouts,
            channels_setup=gui_setup.channels_setup,
            start_point=gui_setup.start_point,
            duration_ms=gui_setup.duration_ms,
            start_time_ms=self._start_time_ms,
            sample_rate=sample_rate,
            visible_events=visible_events,
            visible_periods=visible_periods,
            events_vocabulary=self._session_manager.events_vocabulary,
            periods_vocabulary=self._session_manager.periods_vocabulary,
            sweep_idx=gui_setup.current_sweep_idx,
            events_are_visible=gui_setup.events_are_shown,
            periods_are_visible=gui_setup.periods_are_shown,
            traces_are_visible=gui_setup.traces_are_shown,
            cut_traces=gui_setup.cut_traces,
            viewable_add_ons=viewable_add_ons,
            add_ons_data_dir=add_ons_data_dir,
        )

        self._update_group_navigators(group_layouts)
        self._update_overlay_widget()

    def _get_events_for_current_window(self, gui_setup):
        """Return events that fall into the current time window and sweep."""
        if not self._session_manager or not self._session_manager.current_user_session:
            return []

        header = self._session_manager.header
        if not header:
            return []

        events = getattr(self._session_manager, "events", [])
        if not events:
            return []

        sweep_idx = gui_setup.current_sweep_idx
        return [
            e
            for e in events
            if e.sweep_idx == sweep_idx and self._start_time_ms <= e.time_ms <= self._end_time_ms
        ]

    def _get_periods_for_current_window(self, gui_setup):
        """Return periods that overlap with the current time window and sweep.
        
        Note: Period start_time_ms and end_time_ms are relative to sweep start (like events).
        """
        if not self._session_manager or not self._session_manager.current_user_session:
            return []

        header = self._session_manager.header
        if not header:
            return []

        periods = getattr(self._session_manager, "periods", [])
        if not periods:
            return []

        sweep_idx = gui_setup.current_sweep_idx
        visible = []
        for period in periods:
            if period.start_sweep_idx > sweep_idx or period.end_sweep_idx < sweep_idx:
                continue
            local_start_ms, local_end_ms = self._period_bounds_for_sweep(period, sweep_idx)
            if local_start_ms is None or local_end_ms is None:
                continue
            if local_end_ms < self._start_time_ms or local_start_ms > self._end_time_ms:
                continue
            visible.append(period.model_copy(update={
                "start_time_ms": local_start_ms,
                "end_time_ms": local_end_ms,
            }))
        return visible

    def _update_overlay_widget(self):
        if (not hasattr(self, 'overlay_widget') or self.overlay_widget is None
                or not self._session_manager.session_is_active):
            return

        gui_setup = self._session_manager.gui_setup if self._session_manager else None
        duration_ms = gui_setup.duration_ms if gui_setup else 0.0
        start_time_ms = self._start_time_ms if gui_setup else 0.0
        measure_cursor_pos = self._resolve_measure_cursor_pos()

        # Adapt the measure bar to the cell/group under the cursor: each cell maps
        # the full time window across its own width, so time/voltage scaling must
        # use that cell's geometry rather than the whole signal area.
        measure_rect = None
        if measure_cursor_pos is not None:
            measure_rect = self.signal_widget.measure_rect_at(measure_cursor_pos)
        if measure_rect is not None:
            channel_height = measure_rect.height()
            time_axis_width = measure_rect.width()
        else:
            channel_height = self.signal_widget._channel_height or self._channel_height
            time_axis_width = 0

        scale_value = self._resolve_measure_scale_value(measure_cursor_pos)
        cursor_is_aux = bool(measure_cursor_pos and self.signal_widget.is_auxiliary_y(measure_cursor_pos.y()))

        # Determine selection_start_time_ms based on current mode
        selection_start_time_ms = None
        selection_start_pos = None
        selection_start_pixel_pos = None
        if self._current_overlay_mode in (
                OverlayModeEnum.EVENT_BAD_SET,
                OverlayModeEnum.EVENT_BAD_UNSET,
                OverlayModeEnum.EVENT_REMOVE,
        ):
            selection_start_time_ms = self._current_event_edit_first_time_ms
            if self._current_event_edit_first_sweep_idx is not None and self._current_event_edit_first_time_ms is not None:
                selection_start_pos = (
                    int(self._current_event_edit_first_sweep_idx),
                    float(self._current_event_edit_first_time_ms),
                )
        elif self._current_overlay_mode == OverlayModeEnum.PERIOD_ADD:
            if self._current_period_add_first_point is not None:
                selection_start_time_ms = self._current_period_add_first_point[1]  # Extract time_ms
                selection_start_pos = self._current_period_add_first_point
        elif self._current_overlay_mode == OverlayModeEnum.FULL_VIEW_SELECT:
            selection_start_pixel_pos = self._full_view_first_point

        self.overlay_widget.update_state(
            cursor_pos=measure_cursor_pos,
            overlay_mode=(
                OverlayModeEnum.NONE
                if (cursor_is_aux and self._current_overlay_mode == OverlayModeEnum.TIME_VOLTAGE_BAR)
                else self._current_overlay_mode
            ),
            channel_height=channel_height,
            duration_ms=duration_ms,
            time_axis_width=time_axis_width,
            scale_value=scale_value,
            start_time_ms=start_time_ms,
            current_sweep_idx=(gui_setup.current_sweep_idx if gui_setup else 0),
            selection_start_time_ms=selection_start_time_ms,
            selection_start_pos=selection_start_pos,
            selection_start_pixel_pos=selection_start_pixel_pos,
        )

    def _resolve_measure_cursor_pos(self) -> Optional[QPoint]:
        if self._current_overlay_mode == OverlayModeEnum.TIME_VOLTAGE_BAR:
            if self._measure_bar_state == MeasureBarStateEnum.FROZEN:
                return self._frozen_measure_pos
            return self._current_mouse_pos
        return self._current_mouse_pos

    def _resolve_measure_scale_value(self, measure_cursor_pos: Optional[QPoint]) -> float:
        if measure_cursor_pos is None:
            return settings.DEFAULT_SCALE
        scale_value = self.signal_widget.get_scale_for_non_aux_y(measure_cursor_pos.y())
        if scale_value is None or scale_value <= 0:
            return settings.DEFAULT_SCALE
        return scale_value

    def _should_hide_cursor(self) -> bool:
        if self._current_overlay_mode in (
                OverlayModeEnum.EVENT_ADD,
                OverlayModeEnum.EVENT_BAD_SET,
                OverlayModeEnum.EVENT_BAD_UNSET,
                OverlayModeEnum.EVENT_REMOVE,
                OverlayModeEnum.PERIOD_ADD,
        ):
            return self._current_mouse_pos is not None
        return (self._current_overlay_mode == OverlayModeEnum.TIME_VOLTAGE_BAR
                and self._measure_bar_state == MeasureBarStateEnum.FOLLOW_CURSOR)

    def _reset_measure_bar_state(self):
        self._measure_bar_state = MeasureBarStateEnum.HIDDEN
        self._frozen_measure_pos = None

    # ---- Events helper API ----
    def start_event_add_mode(self, event_name_id: int):
        """Enable interactive event placement for the given vocabulary id."""
        self._stop_full_view_select_mode()
        self._reset_measure_bar_state()
        self._current_event_add_id = event_name_id
        self._current_overlay_mode = OverlayModeEnum.EVENT_ADD
        if self._should_hide_cursor():
            self.setCursor(Qt.CursorShape.BlankCursor)
        else:
            self.unsetCursor()
        self._update_overlay_widget()

    def _stop_event_add_mode(self):
        self._current_event_add_id = None
        if self._current_overlay_mode == OverlayModeEnum.EVENT_ADD:
            self._current_overlay_mode = OverlayModeEnum.NONE
            if not self._should_hide_cursor():
                self.unsetCursor()
        self._update_overlay_widget()

    def _stop_period_add_mode(self):
        self._current_period_add_id = None
        self._current_period_add_first_point = None
        if self._current_overlay_mode == OverlayModeEnum.PERIOD_ADD:
            self._current_overlay_mode = OverlayModeEnum.NONE
            if not self._should_hide_cursor():
                self.unsetCursor()
        self._update_overlay_widget()

    # ---- Events edit (bad / remove) API ----
    def start_set_bad_event_mode(self):
        """Start interactive mode to mark events as bad inside a selected time window."""
        self._start_event_edit_mode(OverlayModeEnum.EVENT_BAD_SET)

    def start_unset_bad_event_mode(self):
        """Start interactive mode to unset 'bad' flag for events inside a selected time window."""
        self._start_event_edit_mode(OverlayModeEnum.EVENT_BAD_UNSET)

    def start_event_remove_mode(self):
        """Start interactive mode to remove events inside a selected time window."""
        self._start_event_edit_mode(OverlayModeEnum.EVENT_REMOVE)

    def _start_event_edit_mode(self, mode: OverlayModeEnum):
        """Common initializer for all 'edit events in window' modes."""
        self._stop_full_view_select_mode()
        # Cancel any ongoing add modes
        self._stop_event_add_mode()
        self._stop_period_add_mode()
        self._reset_measure_bar_state()

        self._current_event_edit_mode = mode
        self._current_event_edit_first_sweep_idx = None
        self._current_event_edit_first_time_ms = None
        self._current_overlay_mode = mode
        if self._should_hide_cursor():
            self.setCursor(Qt.CursorShape.BlankCursor)
        else:
            self.unsetCursor()
        self._update_overlay_widget()

    # ---- Full-view selected area API ----
    def start_full_view_select_mode(self):
        """Start rectangle selection mode for opening a non-modal full-view window."""
        if self._current_overlay_mode not in (OverlayModeEnum.NONE, OverlayModeEnum.FULL_VIEW_SELECT):
            return
        self._reset_measure_bar_state()
        self._full_view_first_point = None
        self._current_overlay_mode = OverlayModeEnum.FULL_VIEW_SELECT
        self.setCursor(Qt.CursorShape.BlankCursor)
        self._update_overlay_widget()

    def _stop_full_view_select_mode(self):
        self._full_view_first_point = None
        if self._current_overlay_mode == OverlayModeEnum.FULL_VIEW_SELECT:
            self._current_overlay_mode = OverlayModeEnum.NONE
        self.unsetCursor()
        self._update_overlay_widget()

    def _is_point_inside_signal_area(self, pos: QPoint) -> bool:
        left = self._LEFT_MARGIN
        right = self.signal_widget.width() - self._RIGHT_MARGIN
        top = 0
        bottom = self.signal_widget.height() - self._BOTTOM_MARGIN
        return left <= pos.x() <= right and top <= pos.y() <= bottom

    def _x_to_time_ms(self, x_pos: int) -> Optional[float]:
        return self.signal_widget.time_ms_at_x(int(x_pos))

    def _handle_full_view_select_click(self, event: QMouseEvent):
        pos = event.position().toPoint()
        if not self._is_point_inside_signal_area(pos):
            return
        if self._full_view_first_point is None:
            self._full_view_first_point = pos
            self._update_overlay_widget()
            return

        first = QPoint(self._full_view_first_point)
        self._full_view_first_point = None
        self._open_full_view_selected_area_dialog(first, pos)
        self._update_overlay_widget()

    def _open_full_view_selected_area_dialog(self, first_pos: QPoint, second_pos: QPoint):
        if not self._session_manager.gui_setup or not self._session_manager.header:
            return
        x1, x2 = sorted((first_pos.x(), second_pos.x()))
        y1, y2 = sorted((first_pos.y(), second_pos.y()))
        selection_rect = QRect(QPoint(x1, y1), QPoint(x2, y2))
        selected_channels = self.signal_widget.get_channels_in_rect(selection_rect)
        if not selected_channels:
            return

        t1 = self._x_to_time_ms(first_pos.x())
        t2 = self._x_to_time_ms(second_pos.x())
        if t1 is None or t2 is None:
            return
        start_ms, end_ms = sorted((t1, t2))
        if end_ms - start_ms <= 1e-9:
            return

        duration_ms = max(1e-9, self._end_time_ms - self._start_time_ms)
        data_subset: Dict[int, np.ndarray[np.float64]] = {}
        for ch_idx in selected_channels:
            data = self._cached_processed_data.get(ch_idx)
            if data is None or len(data) < 2:
                continue
            n = len(data)
            left_idx = int(((start_ms - self._start_time_ms) / duration_ms) * (n - 1))
            right_idx = int(((end_ms - self._start_time_ms) / duration_ms) * (n - 1))
            left_idx = max(0, min(n - 2, left_idx))
            right_idx = max(left_idx + 1, min(n - 1, right_idx))
            data_subset[ch_idx] = data[left_idx:right_idx + 1]

        selected_channels = [ch for ch in selected_channels if ch in data_subset]
        if not selected_channels:
            return

        gui_setup = self._session_manager.gui_setup
        dialog = FullViewSelectedAreaDialog(
            channel_indexes=selected_channels,
            channel_names=self._session_manager.header.channel_info.name,
            channel_data=data_subset,
            channels_setup=gui_setup.channels_setup,
            start_time_ms=start_ms,
            end_time_ms=end_ms,
            parent=self,
        )
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.destroyed.connect(lambda _obj=None, dlg=dialog: self._remove_full_view_window(dlg))
        self._full_view_windows.append(dialog)
        dialog.show()

    def _remove_full_view_window(self, dialog: QDialog):
        try:
            self._full_view_windows.remove(dialog)
        except ValueError:
            pass

    def _stop_event_edit_mode(self):
        self._current_event_edit_mode = None
        self._current_event_edit_first_sweep_idx = None
        self._current_event_edit_first_time_ms = None
        if self._current_overlay_mode in (
                OverlayModeEnum.EVENT_BAD_SET,
                OverlayModeEnum.EVENT_BAD_UNSET,
                OverlayModeEnum.EVENT_REMOVE,
        ):
            self._current_overlay_mode = OverlayModeEnum.NONE
            if not self._should_hide_cursor():
                self.unsetCursor()
        self._update_overlay_widget()

    # ---- Periods helper API ----
    def start_period_add_mode(self, period_name_id: int):
        """Enable interactive period placement for the given vocabulary id."""
        self._stop_full_view_select_mode()
        # Cancel any ongoing event modes
        self._stop_event_add_mode()
        self._stop_event_edit_mode()
        self._reset_measure_bar_state()

        self._current_period_add_id = period_name_id
        self._current_period_add_first_point = None
        self._current_overlay_mode = OverlayModeEnum.PERIOD_ADD
        if self._should_hide_cursor():
            self.setCursor(Qt.CursorShape.BlankCursor)
        else:
            self.unsetCursor()
        self._update_overlay_widget()

    def _handle_period_add_click(self, event: QMouseEvent):
        """Handle left click when in PERIOD_ADD mode: collect two points and create period."""
        if self._current_period_add_id is None:
            return

        gui_setup = self._session_manager.gui_setup
        if not gui_setup:
            return

        time_ms = self._mouse_event_to_time_ms(event)
        if time_ms is None:
            return

        current_sweep_idx = gui_setup.current_sweep_idx

        if self._current_period_add_first_point is None:
            # First point: store and wait for the second
            self._current_period_add_first_point = (current_sweep_idx, time_ms)
            self._update_overlay_widget()
            return

        # Second point: determine start/end and create period
        first_sweep_idx, first_time_ms = self._current_period_add_first_point
        second_sweep_idx = current_sweep_idx
        second_time_ms = time_ms

        # Determine which point is earlier: compare sweep_idx first, then time_ms
        if first_sweep_idx < second_sweep_idx or (
                first_sweep_idx == second_sweep_idx and first_time_ms <= second_time_ms
        ):
            start_sweep_idx = first_sweep_idx
            start_time_ms = first_time_ms
            end_sweep_idx = second_sweep_idx
            end_time_ms = second_time_ms
        else:
            start_sweep_idx = second_sweep_idx
            start_time_ms = second_time_ms
            end_sweep_idx = first_sweep_idx
            end_time_ms = first_time_ms

        self._session_manager.add_period(
            period_name_id=self._current_period_add_id,
            start_sweep_idx=start_sweep_idx,
            start_time_ms=start_time_ms,
            end_sweep_idx=end_sweep_idx,
            end_time_ms=end_time_ms,
        )

        self._stop_period_add_mode()

    def _handle_event_add_click(self, event: QMouseEvent):
        """Handle left click when in EVENT_ADD mode: compute time_ms and create event."""
        if self._current_event_add_id is None:
            return

        time_ms = self._mouse_event_to_time_ms(event)
        if time_ms is None:
            return

        gui_setup = self._session_manager.gui_setup
        if not gui_setup:
            return

        self._session_manager.add_event(
            event_name_id=self._current_event_add_id,
            sweep_idx=gui_setup.current_sweep_idx,
            time_ms=time_ms,
        )

    def _handle_event_edit_click(self, event: QMouseEvent):
        """Handle left click for EVENT_BAD_SET / EVENT_BAD_UNSET / EVENT_REMOVE modes."""
        if self._current_event_edit_mode is None:
            return

        gui_setup = self._session_manager.gui_setup
        if not gui_setup:
            return
        current_sweep_idx = int(gui_setup.current_sweep_idx)

        time_ms = self._mouse_event_to_time_ms(event)
        if time_ms is None:
            return

        if self._current_event_edit_first_time_ms is None:
            # First point: store and wait for the second
            self._current_event_edit_first_sweep_idx = current_sweep_idx
            self._current_event_edit_first_time_ms = time_ms
            return

        first_sweep_idx = int(self._current_event_edit_first_sweep_idx if self._current_event_edit_first_sweep_idx is not None
                              else current_sweep_idx)
        first_time_ms = float(self._current_event_edit_first_time_ms)
        second_sweep_idx = current_sweep_idx
        second_time_ms = float(time_ms)

        if first_sweep_idx < second_sweep_idx or (
                first_sweep_idx == second_sweep_idx and first_time_ms <= second_time_ms
        ):
            start_sweep_idx = first_sweep_idx
            start_time_ms = first_time_ms
            end_sweep_idx = second_sweep_idx
            end_time_ms = second_time_ms
        else:
            start_sweep_idx = second_sweep_idx
            start_time_ms = second_time_ms
            end_sweep_idx = first_sweep_idx
            end_time_ms = first_time_ms

        self._apply_event_edit_in_window(
            start_sweep_idx=start_sweep_idx,
            start_ms=start_time_ms,
            end_sweep_idx=end_sweep_idx,
            end_ms=end_time_ms,
        )
        self._stop_event_edit_mode()

    def _mouse_event_to_time_ms(self, event: QMouseEvent) -> Optional[float]:
        """Convert a click on a channel cell to absolute time in ms.

        Returns None when the click is not inside any channel cell (e.g. in a
        gap between groups/columns), so events/periods are only placed on cells.
        """
        pos = event.position().toPoint()
        gui_setup = self._session_manager.gui_setup
        if not gui_setup:
            return None
        return self.signal_widget.cell_time_ms(pos)

    def _apply_event_edit_in_window(self, *, start_sweep_idx: int, start_ms: float,
                                    end_sweep_idx: int, end_ms: float):
        """Apply current edit mode to all events inside [start_sweep/start_ms, end_sweep/end_ms]."""
        events = self._session_manager.events
        if not events:
            return

        affected_events = []
        for event in events:
            if event.sweep_idx < start_sweep_idx or event.sweep_idx > end_sweep_idx:
                continue
            if start_sweep_idx == end_sweep_idx:
                in_window = start_ms <= event.time_ms <= end_ms
            elif event.sweep_idx == start_sweep_idx:
                in_window = event.time_ms >= start_ms
            elif event.sweep_idx == end_sweep_idx:
                in_window = event.time_ms <= end_ms
            else:
                in_window = True
            if in_window:
                affected_events.append(event)
        if not affected_events:
            return

        if self._current_event_edit_mode in (OverlayModeEnum.EVENT_BAD_SET, OverlayModeEnum.EVENT_BAD_UNSET):
            is_bad = self._current_event_edit_mode == OverlayModeEnum.EVENT_BAD_SET
            self._session_manager.set_events_bad_flag(affected_events, is_bad)
        elif self._current_event_edit_mode == OverlayModeEnum.EVENT_REMOVE:
            self._session_manager.remove_events(affected_events)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._redraw_data()

    def _visible_group_indexes(self) -> List[int]:
        gui_setup = self._session_manager.gui_setup
        if not gui_setup:
            return []
        return [idx for idx, group in enumerate(gui_setup.channels_groups or []) if group.is_shown]

    def _update_group_navigators(self, group_layouts: List[ChannelGroup]):
        """Create/position per-group navigation minimaps after geometry is known."""
        group_rects = self.signal_widget.group_render_rects()
        visible_indexes = self._visible_group_indexes()
        active_group_idxs = set()

        for list_idx, group in enumerate(group_layouts):
            if list_idx >= len(group_rects) or list_idx >= len(visible_indexes):
                continue
            if group.is_auxiliary:
                continue
            group_idx = visible_indexes[list_idx]
            rows_to_show, cols_to_show, cur_row, cur_col, rows_num, cols_num = group.visible_window()
            group_rect = group_rects[list_idx]
            if group_rect.width() <= 0 or group_rect.height() <= 0:
                continue

            navigator = self._group_navigators.get(group_idx)
            if navigator is None:
                navigator = GroupNavigatorWidget(self.signal_widget)
                navigator.position_changed.connect(self._on_group_navigator_moved)
                self._group_navigators[group_idx] = navigator
            navigator.set_state(group_idx, rows_num, cols_num, rows_to_show, cols_to_show, cur_row, cur_col)

            if not navigator.needs_navigation():
                navigator.hide()
                continue

            active_group_idxs.add(group_idx)
            nav_w = min(self._NAV_WIDTH, max(40, group_rect.width() - 2 * self._NAV_MARGIN))
            nav_h = min(self._NAV_HEIGHT, max(30, group_rect.height() - 2 * self._NAV_MARGIN))
            nav_x = group_rect.right() - nav_w - self._NAV_MARGIN
            nav_y = group_rect.bottom() - nav_h - self._NAV_MARGIN
            navigator.setGeometry(nav_x, nav_y, nav_w, nav_h)
            navigator.show()
            navigator.raise_()

        # Hide navigators for groups that are no longer visible/navigable
        for group_idx, navigator in self._group_navigators.items():
            if group_idx not in active_group_idxs:
                navigator.hide()

    def _on_group_navigator_moved(self, group_idx: int, cur_row_idx: int, cur_column_idx: int):
        self._session_manager.set_group_cur_position(
            group_idx, cur_row_idx=cur_row_idx, cur_column_idx=cur_column_idx
        )

    def get_visible_groups_layout(self) -> List[ChannelGroup]:
        gui_setup = self._session_manager.gui_setup
        if not gui_setup:
            return []
        groups_layout: List[ChannelGroup] = []
        for group in (gui_setup.channels_groups or []):
            if not group.is_shown:
                continue
            groups_layout.append(group)
        return groups_layout

    def get_all_visible_channel_indexes(self) -> List[int]:
        result: List[int] = []
        for group in self.get_visible_groups_layout():
            result.extend(group.visible_channels())

        return result

    def on_time_scroll(self, value):
        """Handle time scrollbar movement"""
        self._session_manager.set_start_point(value)

    def on_start_point_changed(self, value):
        self.time_scrollbar.setValue(value)

    def on_session_loaded(self):
        self._update_time_scrollbar()

    def _update_time_scrollbar(self):
        gui_setup = self._session_manager.gui_setup
        header = self._session_manager.header
        if not gui_setup or not header:
            return
        total_points = self._sweep_points(gui_setup.current_sweep_idx)
        visible_points = int((gui_setup.duration_ms / 1000.0) * header.sample_rate)
        self.time_scrollbar.blockSignals(True)
        self.time_scrollbar.setPageStep(max(1, visible_points))
        self.time_scrollbar.setMaximum(max(0, total_points - visible_points))
        self.time_scrollbar.setValue(gui_setup.start_point)
        self.time_scrollbar.blockSignals(False)

    def _sweep_points(self, sweep_idx: int) -> int:
        if not self._session_manager.header:
            return 0
        points_per_sweep = list(self._session_manager.header.number_of_points_per_sweep)
        sweep_idx = max(0, min(int(sweep_idx), len(points_per_sweep) - 1))
        return int(points_per_sweep[sweep_idx])

    def _sweep_duration_ms(self, sweep_idx: int) -> float:
        header = self._session_manager.header
        if not header:
            return 0.0
        return (self._sweep_points(sweep_idx) / header.sample_rate) * 1000.0

    def _period_bounds_for_sweep(self, period, sweep_idx: int) -> Tuple[Optional[float], Optional[float]]:
        if period.start_sweep_idx == period.end_sweep_idx:
            return period.start_time_ms, period.end_time_ms
        if sweep_idx == period.start_sweep_idx:
            return period.start_time_ms, self._sweep_duration_ms(sweep_idx)
        if sweep_idx == period.end_sweep_idx:
            return 0.0, period.end_time_ms
        if period.start_sweep_idx < sweep_idx < period.end_sweep_idx:
            return 0.0, self._sweep_duration_ms(sweep_idx)
        return None, None

    def on_single_left_click(self):
        """Handle single left arrow click"""
        step = self._time_step_samples()
        if step <= 0:
            return
        self.time_scrollbar.setValue(self._session_manager.gui_setup.start_point - step)

    def on_single_right_click(self):
        step = self._time_step_samples()
        if step <= 0:
            return
        self.time_scrollbar.setValue(self._session_manager.gui_setup.start_point + step)

    def on_double_right_click(self):
        self._toggle_auto_scroll(direction=1)

    def on_double_left_click(self):
        self._toggle_auto_scroll(direction=-1)

    def _time_step_samples(self) -> int:
        if not self._session_manager.gui_setup or not self._session_manager.header:
            return 0
        interval = self._session_manager.header.sample_interval_microseconds
        if interval <= 0:
            return 0
        return int((self._session_manager.gui_setup.time_step_ms * 1000) / interval)

    def _toggle_auto_scroll(self, direction: int):
        if self._auto_scroll_timer.isActive() and self._auto_scroll_direction == direction:
            self._auto_scroll_timer.stop()
            self._auto_scroll_direction = 0
            return
        self._auto_scroll_direction = direction
        if self._session_manager.gui_setup:
            self._auto_scroll_timer.setInterval(
                self._session_manager.gui_setup.autoscroll_step_interval_ms
            )
        self._auto_scroll_timer.start()
        self._on_auto_scroll_tick()

    def _on_auto_scroll_tick(self):
        if not self._session_manager.gui_setup:
            self._auto_scroll_timer.stop()
            self._auto_scroll_direction = 0
            return
        step = self._time_step_samples()
        if step <= 0:
            self._auto_scroll_timer.stop()
            self._auto_scroll_direction = 0
            return
        delta = step if self._auto_scroll_direction > 0 else -step
        self.time_scrollbar.setValue(self._session_manager.gui_setup.start_point + delta)

    # FOR FUN
    def keyPressEvent(self, event):
        """Handle keyboard events"""
        key = event.key()
        if key in {Qt.Key.Key_M, Qt.Key.Key_P, Qt.Key.Key_V, Qt.Key.Key_Escape}:
            if key == Qt.Key.Key_Escape:
                if self._current_overlay_mode == OverlayModeEnum.EVENT_ADD:
                    self._stop_event_add_mode()
                    self._update_overlay_widget()
                    event.accept()
                    return
                elif self._current_overlay_mode == OverlayModeEnum.PERIOD_ADD:
                    self._stop_period_add_mode()
                    self._update_overlay_widget()
                    event.accept()
                    return
                elif self._current_overlay_mode == OverlayModeEnum.FULL_VIEW_SELECT:
                    self._stop_full_view_select_mode()
                    self._update_overlay_widget()
                    event.accept()
                    return
            if key == Qt.Key.Key_M:
                if self._current_overlay_mode not in (OverlayModeEnum.NONE, OverlayModeEnum.TIME_VOLTAGE_BAR):
                    event.accept()
                    return
                if self._measure_bar_state == MeasureBarStateEnum.HIDDEN:
                    self._measure_bar_state = MeasureBarStateEnum.FOLLOW_CURSOR
                    self._current_overlay_mode = OverlayModeEnum.TIME_VOLTAGE_BAR
                    self._frozen_measure_pos = None
                elif self._measure_bar_state == MeasureBarStateEnum.FOLLOW_CURSOR:
                    self._measure_bar_state = MeasureBarStateEnum.FROZEN
                    self._frozen_measure_pos = QPoint(self._current_mouse_pos) if self._current_mouse_pos else None
                else:
                    self._measure_bar_state = MeasureBarStateEnum.HIDDEN
                    self._frozen_measure_pos = None
                    self._current_overlay_mode = OverlayModeEnum.NONE

                if self._should_hide_cursor():
                    self.setCursor(Qt.CursorShape.BlankCursor)
                else:
                    self.unsetCursor()
            elif key == Qt.Key.Key_V:
                if self._current_overlay_mode == OverlayModeEnum.FULL_VIEW_SELECT:
                    self._stop_full_view_select_mode()
                    event.accept()
                    return
                if self._current_overlay_mode != OverlayModeEnum.NONE:
                    event.accept()
                    return
                self.start_full_view_select_mode()

            self._update_overlay_widget()
            event.accept()
        else:
            super().keyPressEvent(event)

    def leaveEvent(self, event):
        """Hide scale when mouse leaves"""
        self._update_overlay_widget()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        """Set focus when clicked"""
        self.setFocus()
        super().mousePressEvent(event)

    def wheelEvent(self, event):
        if self._session_manager.gui_setup:
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self.__zoom(event)
            else:
                pass
                # self.__scroll_horizontally(event)
        else:
            super().wheelEvent(event)

    def __zoom(self, event):
        cursor_x = event.position().x()
        widget_width = self.width()
        if cursor_x < 0 or cursor_x > widget_width:
            return

        rel_pos = cursor_x / widget_width
        current_zoom = 10000 / self._session_manager.gui_setup.duration_ms
        scale_factor = 2.0 + (0.1 / max(1.0, current_zoom ** 0.5))
        delta = event.angleDelta().y()
        if delta > 0:  # zoom in
            new_duration = self._session_manager.gui_setup.duration_ms / scale_factor
            new_start_point = (self._session_manager.gui_setup.start_point
                               + (self._session_manager.gui_setup.duration_ms - new_duration) / 1000.0
                               * self._session_manager.header.sample_rate * rel_pos)
        else:  # zoom out
            new_duration = self._session_manager.gui_setup.duration_ms * scale_factor
            new_start_point = (self._session_manager.gui_setup.start_point
                               - (new_duration - self._session_manager.gui_setup.duration_ms) / 1000.0
                               * self._session_manager.header.sample_rate * rel_pos)

        start_point_changed = self._session_manager.set_start_point(int(new_start_point))
        duration_changed = self._session_manager.set_duration_ms(int(new_duration))
        if start_point_changed or duration_changed:
            self._redraw_data()

        event.accept()

    def __scroll_horizontally(self, event):
        cursor_x = event.position().x()
        widget_width = self.width()
        if cursor_x < 0 or cursor_x > widget_width:
            return

        delta = event.angleDelta().y()
        if delta > 0:  # go right
            self.on_single_right_click()
        else:  # go left
            self.on_single_left_click()
