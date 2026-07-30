# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

import base64
import mimetypes
import urllib.request

from PyQt6.QtCore import Qt, QUrl, QTimer
from PyQt6.QtGui import QColor, QPixmap, QDesktopServices
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QDoubleSpinBox,
    QListWidget,
    QListWidgetItem,
    QCheckBox,
    QGroupBox,
    QPushButton,
    QComboBox,
    QFormLayout,
    QMessageBox,
    QColorDialog,
    QToolButton,
    QFrame,
    QAbstractItemView, QLineEdit,
    QDialog,
    QFileDialog,
    QScrollArea,
    QScrollBar,
    QInputDialog,
    QTabWidget,
    QGridLayout,
    QSizePolicy,
)
from typing import Dict, List, Optional, Tuple

from ephyr import settings
from ephyr.converter.channel_order import (
    import_channel_order,
    resolve_source_path,
    source_file_dialog_filter,
)
from ephyr.converter.source_reader.nwb import (
    layout_table_from_nwb,
    resolve_nwb_source_path,
)
from ephyr.core.global_storage import GuiMode
from ephyr.core.ephyr_session import ChannelsLayout, GroupLayout, ChannelGroup
from ephyr.core.header import Header
from ephyr.gui.dialogs.header_units_management_dialog import HeaderUnitsManagementDialog
from ephyr.gui._utils import milliseconds_to_readable, sample_rate_to_readable
from ephyr.gui.qt_ephyr_session_manager_wrapper import QtEphyrSessionManagerWrapper
from ephyr.core.conversions.filters import (
    ensure_filters_list,
    ButterworthLowPassFilter,
    ButterworthHighPassFilter,
    ButterworthBandPassFilter,
    ChebyshevBandPassFilter,
    NotchFilter,
)


class ChannelLayoutDialog(QDialog):
    def __init__(
        self,
        channels: List[int],
        channels_layout: ChannelsLayout,
        channel_name_getter,
        parent=None,
        *,
        header: Optional[Header] = None,
        ephyr_folder: Optional[Path] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Channels layout")
        self.resize(480, 560)
        self._channel_name_getter = channel_name_getter
        self._channels_layout = channels_layout
        self._header = header
        self._ephyr_folder = ephyr_folder

        layout = QVBoxLayout(self)
        info = QLabel("Order channels (drag&drop, arrows, or format 1,10,12,14-18,20). "
                      "Use Layout settings to arrange channels into a custom grid.")
        info.setWordWrap(True)
        layout.addWidget(info)

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list_widget.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.list_widget.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.list_widget.setDragEnabled(True)
        self.list_widget.setAcceptDrops(True)
        layout.addWidget(self.list_widget, 1)

        arrows = QHBoxLayout()
        self.up_btn = QPushButton("↑")
        self.down_btn = QPushButton("↓")
        arrows.addWidget(self.up_btn)
        arrows.addWidget(self.down_btn)
        arrows.addStretch(1)
        layout.addLayout(arrows)

        manual_row = QHBoxLayout()
        manual_row.addWidget(QLabel("Manual order:"))
        self.manual_edit = QLineEdit()
        self.apply_manual_btn = QPushButton("Apply")
        manual_row.addWidget(self.manual_edit, 1)
        manual_row.addWidget(self.apply_manual_btn)
        layout.addLayout(manual_row)

        settings_row = QHBoxLayout()
        self.layout_settings_btn = QPushButton("Layout settings")
        self.import_order_btn = QPushButton("Import from source")
        settings_row.addWidget(self.layout_settings_btn)
        settings_row.addWidget(self.import_order_btn)
        settings_row.addStretch(1)
        layout.addLayout(settings_row)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.cancel_btn = QPushButton("Cancel")
        self.ok_btn = QPushButton("Save")
        actions.addWidget(self.cancel_btn)
        actions.addWidget(self.ok_btn)
        layout.addLayout(actions)

        self._set_order(channels)
        self.up_btn.clicked.connect(lambda: self._move_selected(-1))
        self.down_btn.clicked.connect(lambda: self._move_selected(1))
        self.apply_manual_btn.clicked.connect(self._apply_manual)
        self.layout_settings_btn.clicked.connect(self._open_layout_settings)
        self.import_order_btn.clicked.connect(self._import_order_from_source)
        self.cancel_btn.clicked.connect(self.reject)
        self.ok_btn.clicked.connect(self.accept)

    def _pick_source_path(self) -> Optional[Path]:
        header = self._header
        if header is None:
            return None
        name_filter, prefer_directory = source_file_dialog_filter(header.type_before_conversion)
        start = str(self._ephyr_folder or Path.home())
        if prefer_directory:
            chosen = QFileDialog.getExistingDirectory(self, "Select source folder", start)
            return Path(chosen) if chosen else None
        chosen, _ = QFileDialog.getOpenFileName(
            self,
            "Select source file",
            start,
            name_filter or "All files (*)",
        )
        return Path(chosen) if chosen else None

    def _import_order_from_source(self) -> None:
        header = self._header
        if header is None:
            QMessageBox.warning(self, "Import from source", "No experiment header is loaded.")
            return

        src_type = str(header.type_before_conversion or "").lower()
        source_path = resolve_source_path(self._ephyr_folder, header)
        if source_path is None and src_type in {"nwb", "rhs", "rhd"}:
            source_path = self._pick_source_path()
            if source_path is None:
                return

        try:
            new_order, method = import_channel_order(
                header,
                self.get_order(),
                source_path=source_path,
            )
        except Exception as exc:
            if source_path is None:
                source_path = self._pick_source_path()
                if source_path is None:
                    QMessageBox.warning(self, "Import from source", str(exc))
                    return
                try:
                    new_order, method = import_channel_order(
                        header,
                        self.get_order(),
                        source_path=source_path,
                    )
                except Exception as retry_exc:
                    QMessageBox.warning(self, "Import from source", str(retry_exc))
                    return
            else:
                QMessageBox.warning(self, "Import from source", str(exc))
                return

        self._set_order(new_order)
        QMessageBox.information(
            self,
            "Import from source",
            f"Channel order updated using {method}.",
        )

    def _open_layout_settings(self):
        dialog = LayoutSettingsDialog(
            self._channels_layout,
            self.get_order(),
            self._channel_name_getter,
            self,
            header=self._header,
            ephyr_folder=self._ephyr_folder,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._channels_layout = dialog.get_channels_layout()
            self._set_order(dialog.get_order())

    def get_channels_layout(self) -> ChannelsLayout:
        layout = self._channels_layout
        if layout.enable_custom_layout and layout.layout_table:
            rows = len(layout.layout_table)
            cols = len(layout.layout_table[0]) if layout.layout_table[0] else 0
            mask = [[cell != -1 for cell in row] for row in layout.layout_table]
            layout.layout_table = self._fill_layout_table(rows, cols, mask, self.get_order())
        return layout

    @staticmethod
    def _fill_layout_table(rows: int, cols: int, mask: List[List[bool]],
                           order: List[int]) -> List[List[int]]:
        table = [[-1] * cols for _ in range(rows)]
        seq = iter(order)
        for r in range(rows):
            for c in range(cols):
                if r < len(mask) and c < len(mask[r]) and mask[r][c]:
                    try:
                        table[r][c] = next(seq)
                    except StopIteration:
                        table[r][c] = -1
        return table

    def _set_order(self, channels: List[int]):
        self.list_widget.clear()
        for ch in channels:
            label = self._channel_name_getter(ch)
            item = QListWidgetItem(f"{ch} [{label}]")
            item.setData(Qt.ItemDataRole.UserRole, ch)
            self.list_widget.addItem(item)

    def _current_order(self) -> List[int]:
        result: List[int] = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            result.append(int(item.data(Qt.ItemDataRole.UserRole)))
        return result

    def _move_selected(self, delta: int):
        row = self.list_widget.currentRow()
        if row < 0:
            return
        new_row = row + delta
        if new_row < 0 or new_row >= self.list_widget.count():
            return
        item = self.list_widget.takeItem(row)
        self.list_widget.insertItem(new_row, item)
        self.list_widget.setCurrentRow(new_row)

    def _apply_manual(self):
        text = self.manual_edit.text().strip()
        if not text:
            return
        current = self._current_order()
        allowed = set(current)
        parsed: List[int] = []
        try:
            for token in text.split(","):
                token = token.strip()
                if not token:
                    continue
                if "-" in token:
                    start_s, end_s = token.split("-", 1)
                    start = int(start_s.strip())
                    end = int(end_s.strip())
                    step = 1 if end >= start else -1
                    for v in range(start, end + step, step):
                        parsed.append(v)
                else:
                    parsed.append(int(token))
        except Exception:
            QMessageBox.warning(self, "Reorder", "Failed to parse manual order.")
            return

        if set(parsed) != allowed or len(parsed) != len(current):
            QMessageBox.warning(self, "Reorder", "Manual order must contain all channels exactly once.")
            return
        self._set_order(parsed)

    def get_order(self) -> List[int]:
        return self._current_order()


class LayoutSettingsDialog(QDialog):
    _VIEW_ROWS = 10
    _VIEW_COLS = 10

    def __init__(
        self,
        channels_layout: ChannelsLayout,
        channel_order: List[int],
        channel_name_getter,
        parent=None,
        *,
        header: Optional[Header] = None,
        ephyr_folder: Optional[Path] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Layout settings")
        self.resize(640, 680)
        self._channel_order = list(channel_order)
        self._channel_count = len(self._channel_order)
        self._channel_name_getter = channel_name_getter
        self._header = header
        self._ephyr_folder = Path(ephyr_folder) if ephyr_folder is not None else None
        self._mask: List[List[bool]] = []
        self._view_row = 0
        self._view_col = 0
        self._check_boxes: List[List[QCheckBox]] = []
        self._name_labels: List[List[QLabel]] = []
        self._updating_view = False

        root = QVBoxLayout(self)
        caption = QLabel(
            "Electrodes are placed into the checked cells in order, from the "
            "top-left to the bottom-right corner. Checked cells show the "
            "electrode that will appear there. The editor shows at most a "
            f"{self._VIEW_ROWS}×{self._VIEW_COLS} window; use scrollbars to move."
        )
        caption.setWordWrap(True)
        root.addWidget(caption)

        existing_table = channels_layout.layout_table
        if existing_table:
            rows0 = len(existing_table)
            cols0 = len(existing_table[0]) if existing_table[0] else 1
        else:
            rows0 = max(1, self._channel_count)
            cols0 = max(1, int(channels_layout.columns_num))

        form = QFormLayout()
        self.rows_spin = QSpinBox(); self.rows_spin.setRange(1, 4096); self.rows_spin.setValue(rows0)
        self.rows_show_spin = QSpinBox(); self.rows_show_spin.setRange(1, 4096)
        self.rows_show_spin.setValue(max(1, int(channels_layout.rows_num_to_show)))
        self.cols_spin = QSpinBox(); self.cols_spin.setRange(1, 4096); self.cols_spin.setValue(cols0)
        self.cols_show_spin = QSpinBox(); self.cols_show_spin.setRange(1, 4096)
        self.cols_show_spin.setValue(max(1, int(channels_layout.columns_num_to_show)))
        self.enable_cb = QCheckBox(); self.enable_cb.setChecked(bool(channels_layout.enable_custom_layout))
        self.draw_borders_cb = QCheckBox(); self.draw_borders_cb.setChecked(bool(channels_layout.draw_borders))
        form.addRow("Rows:", self.rows_spin)
        form.addRow("Rows to show:", self.rows_show_spin)
        form.addRow("Columns:", self.cols_spin)
        form.addRow("Columns to show:", self.cols_show_spin)
        enable_row = QHBoxLayout()
        enable_row.addWidget(self.enable_cb)
        enable_row.addWidget(QLabel("Enable custom layout"))
        enable_row.addSpacing(16)
        enable_row.addWidget(self.draw_borders_cb)
        enable_row.addWidget(QLabel("Draw borders"))
        enable_row.addStretch(1)
        form.addRow("", enable_row)
        root.addLayout(form)

        self.count_label = QLabel("")
        root.addWidget(self.count_label)
        self.view_label = QLabel("")
        self.view_label.setStyleSheet("color: gray;")
        root.addWidget(self.view_label)

        grid_wrap = QWidget()
        grid_wrap_layout = QGridLayout(grid_wrap)
        grid_wrap_layout.setContentsMargins(0, 0, 0, 0)
        grid_wrap_layout.setSpacing(2)
        self.table_container = QWidget()
        self.table_grid = QGridLayout(self.table_container)
        self.table_grid.setSpacing(4)
        self.table_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.v_scroll = QScrollBar(Qt.Orientation.Vertical)
        self.h_scroll = QScrollBar(Qt.Orientation.Horizontal)
        grid_wrap_layout.addWidget(self.table_container, 0, 0)
        grid_wrap_layout.addWidget(self.v_scroll, 0, 1)
        grid_wrap_layout.addWidget(self.h_scroll, 1, 0)
        root.addWidget(grid_wrap, 1)

        select_row = QHBoxLayout()
        self.select_all_btn = QPushButton("Select all")
        self.unselect_all_btn = QPushButton("Unselect all")
        self.import_source_btn = QPushButton("Import from source")
        select_row.addWidget(self.select_all_btn)
        select_row.addWidget(self.unselect_all_btn)
        select_row.addWidget(self.import_source_btn)
        select_row.addStretch(1)
        root.addLayout(select_row)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.cancel_btn = QPushButton("Cancel")
        self.save_btn = QPushButton("Save")
        actions.addWidget(self.cancel_btn)
        actions.addWidget(self.save_btn)
        root.addLayout(actions)

        self._init_mask_from_table(existing_table, rows0, cols0)
        self._build_viewport_widgets()
        self._refresh_scrollbars()
        self._render_viewport()

        self.rows_spin.valueChanged.connect(self._on_dims_changed)
        self.cols_spin.valueChanged.connect(self._on_dims_changed)
        self.v_scroll.valueChanged.connect(self._on_scroll_changed)
        self.h_scroll.valueChanged.connect(self._on_scroll_changed)
        self.select_all_btn.clicked.connect(lambda: self._set_all(True))
        self.unselect_all_btn.clicked.connect(lambda: self._set_all(False))
        self.import_source_btn.clicked.connect(self._import_from_source)
        self.cancel_btn.clicked.connect(self.reject)
        self.save_btn.clicked.connect(self._on_save)

    def _init_mask_from_table(
        self,
        table: Optional[List[List[int]]],
        rows: int,
        cols: int,
    ) -> None:
        self._mask = [[False] * cols for _ in range(rows)]
        if not table:
            return
        for r in range(min(rows, len(table))):
            row = table[r]
            for c in range(min(cols, len(row))):
                self._mask[r][c] = row[c] != -1

    def _flush_viewport_to_mask(self) -> None:
        if not self._check_boxes:
            return
        rows = len(self._mask)
        cols = len(self._mask[0]) if self._mask else 0
        for vr, row_boxes in enumerate(self._check_boxes):
            r = self._view_row + vr
            if r >= rows:
                break
            for vc, checkbox in enumerate(row_boxes):
                c = self._view_col + vc
                if c >= cols:
                    break
                self._mask[r][c] = checkbox.isChecked()

    def _on_dims_changed(self, _value: int = 0) -> None:
        if self._updating_view:
            return
        self._flush_viewport_to_mask()
        new_rows = self.rows_spin.value()
        new_cols = self.cols_spin.value()
        old = self._mask
        new_mask = [[False] * new_cols for _ in range(new_rows)]
        for r in range(min(new_rows, len(old))):
            for c in range(min(new_cols, len(old[r]) if old else 0)):
                new_mask[r][c] = old[r][c]
        self._mask = new_mask
        self._view_row = min(self._view_row, max(0, new_rows - 1))
        self._view_col = min(self._view_col, max(0, new_cols - 1))
        self._refresh_scrollbars()
        self._render_viewport()

    def _on_scroll_changed(self, _value: int = 0) -> None:
        if self._updating_view:
            return
        self._flush_viewport_to_mask()
        self._view_row = int(self.v_scroll.value())
        self._view_col = int(self.h_scroll.value())
        self._render_viewport()

    def _refresh_scrollbars(self) -> None:
        rows = len(self._mask)
        cols = len(self._mask[0]) if self._mask else 0
        max_row = max(0, rows - self._VIEW_ROWS)
        max_col = max(0, cols - self._VIEW_COLS)
        self._updating_view = True
        self.v_scroll.setRange(0, max_row)
        self.h_scroll.setRange(0, max_col)
        self.v_scroll.setPageStep(self._VIEW_ROWS)
        self.h_scroll.setPageStep(self._VIEW_COLS)
        self.v_scroll.setVisible(max_row > 0)
        self.h_scroll.setVisible(max_col > 0)
        self._view_row = min(self._view_row, max_row)
        self._view_col = min(self._view_col, max_col)
        self.v_scroll.setValue(self._view_row)
        self.h_scroll.setValue(self._view_col)
        self._updating_view = False

    def _clear_grid_widgets(self) -> None:
        while self.table_grid.count():
            item = self.table_grid.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self._check_boxes = []
        self._name_labels = []

    def _build_viewport_widgets(self) -> None:
        self._clear_grid_widgets()
        for r in range(self._VIEW_ROWS):
            row_boxes: List[QCheckBox] = []
            row_labels: List[QLabel] = []
            for c in range(self._VIEW_COLS):
                cell = QWidget()
                cell_layout = QHBoxLayout(cell)
                cell_layout.setContentsMargins(0, 0, 4, 0)
                cell_layout.setSpacing(10)
                checkbox = QCheckBox()
                name_label = QLabel("")
                name_label.setStyleSheet("font-size: 9pt;")
                checkbox.stateChanged.connect(self._on_checkbox_changed)
                cell_layout.addWidget(checkbox)
                cell_layout.addWidget(name_label)
                cell_layout.addStretch(1)
                self.table_grid.addWidget(cell, r, c)
                row_boxes.append(checkbox)
                row_labels.append(name_label)
            self._check_boxes.append(row_boxes)
            self._name_labels.append(row_labels)

    def _on_checkbox_changed(self, _state: int = 0) -> None:
        if self._updating_view:
            return
        self._flush_viewport_to_mask()
        self._refresh_assignment_labels()

    def _render_viewport(self) -> None:
        rows = len(self._mask)
        cols = len(self._mask[0]) if self._mask else 0
        self._updating_view = True
        for vr in range(self._VIEW_ROWS):
            for vc in range(self._VIEW_COLS):
                checkbox = self._check_boxes[vr][vc]
                name_label = self._name_labels[vr][vc]
                cell_widget = checkbox.parentWidget()
                r = self._view_row + vr
                c = self._view_col + vc
                in_bounds = r < rows and c < cols
                if cell_widget is not None:
                    cell_widget.setVisible(in_bounds)
                if not in_bounds:
                    continue
                checkbox.blockSignals(True)
                checkbox.setChecked(self._mask[r][c])
                checkbox.blockSignals(False)
        self._updating_view = False
        visible_rows = min(self._VIEW_ROWS, max(0, rows - self._view_row))
        visible_cols = min(self._VIEW_COLS, max(0, cols - self._view_col))
        self.view_label.setText(
            f"View rows {self._view_row + 1}–{self._view_row + visible_rows} / {rows}, "
            f"cols {self._view_col + 1}–{self._view_col + visible_cols} / {cols}"
        )
        self._refresh_assignment_labels()

    def _set_all(self, checked: bool):
        self._flush_viewport_to_mask()
        count = 0
        for r, row in enumerate(self._mask):
            for c, _ in enumerate(row):
                if checked and count < self._channel_count:
                    self._mask[r][c] = True
                    count += 1
                else:
                    self._mask[r][c] = False
        self._render_viewport()

    def _checked_count(self) -> int:
        return sum(1 for row in self._mask for value in row if value)

    def _electrode_tooltip(self, channel_idx: int) -> str:
        name = self._channel_name_getter(channel_idx)
        return f"{channel_idx} [{name}]" if name else str(channel_idx)

    def _refresh_assignment_labels(self):
        n = self._checked_count()
        self.count_label.setText(f"Selected {n} / {self._channel_count} channels (hover to see a full name)")
        self.count_label.setStyleSheet(
            "color: red;" if n > self._channel_count else "color: gray;"
        )

        seq = iter(self._channel_order)
        assigned: dict[Tuple[int, int], int] = {}
        for r, row in enumerate(self._mask):
            for c, is_checked in enumerate(row):
                if not is_checked:
                    continue
                try:
                    assigned[(r, c)] = next(seq)
                except StopIteration:
                    assigned[(r, c)] = -2

        for vr, row_labels in enumerate(self._name_labels):
            for vc, name_label in enumerate(row_labels):
                r = self._view_row + vr
                c = self._view_col + vc
                if r >= len(self._mask) or c >= len(self._mask[0]):
                    name_label.clear()
                    name_label.setToolTip("")
                    continue
                if not self._mask[r][c]:
                    name_label.clear()
                    name_label.setToolTip("")
                    continue
                channel_idx = assigned.get((r, c), -2)
                if channel_idx < 0:
                    name_label.setText("—")
                    name_label.setToolTip("")
                    name_label.setStyleSheet("color: red; font-size: 9pt;")
                    continue
                name_label.setText(str(channel_idx))
                name_label.setToolTip(self._electrode_tooltip(channel_idx))
                name_label.setStyleSheet("color: #336699; font-size: 9pt;")

    def _import_from_source(self) -> None:
        header = self._header
        if header is not None and header.type_before_conversion != "nwb":
            QMessageBox.information(
                self,
                "Import from source",
                "Import from source currently supports only NWB files.",
            )
            return

        path = resolve_nwb_source_path(self._ephyr_folder, header)
        if path is None:
            start = str(self._ephyr_folder or Path.home())
            chosen, _ = QFileDialog.getOpenFileName(
                self,
                "Select NWB source",
                start,
                "NWB files (*.nwb);;All files (*)",
            )
            if not chosen:
                return
            path = Path(chosen)

        try:
            table, order = layout_table_from_nwb(path, allowed_channels=self._channel_order)
        except Exception as exc:
            QMessageBox.warning(self, "Import from source", str(exc))
            return

        rows = len(table)
        cols = len(table[0]) if table else 0
        if rows <= 0 or cols <= 0:
            QMessageBox.warning(self, "Import from source", "Imported layout is empty.")
            return

        self._flush_viewport_to_mask()
        self._channel_order = list(order)
        self._channel_count = len(self._channel_order)
        self._mask = [[cell != -1 for cell in row] for row in table]
        self._updating_view = True
        self.rows_spin.setValue(rows)
        self.cols_spin.setValue(cols)
        self.rows_show_spin.setValue(min(max(1, self.rows_show_spin.value()), rows))
        self.cols_show_spin.setValue(min(max(1, self.cols_show_spin.value()), cols))
        self.enable_cb.setChecked(True)
        self._updating_view = False
        self._view_row = 0
        self._view_col = 0
        self._refresh_scrollbars()
        self._render_viewport()
        QMessageBox.information(
            self,
            "Import from source",
            f"Loaded layout {rows}×{cols} with {self._checked_count()} electrodes from\n{path.name}",
        )

    def _on_save(self):
        self._flush_viewport_to_mask()
        n = self._checked_count()
        if n > self._channel_count:
            QMessageBox.warning(
                self,
                "Layout settings",
                f"Selected cells ({n}) exceed the number of channels ({self._channel_count}).",
            )
            return
        self.accept()

    def get_order(self) -> List[int]:
        return list(self._channel_order)

    def get_channels_layout(self) -> ChannelsLayout:
        self._flush_viewport_to_mask()
        rows = len(self._mask)
        cols = len(self._mask[0]) if self._mask else 0
        table = ChannelLayoutDialog._fill_layout_table(rows, cols, self._mask, self._channel_order)
        return ChannelsLayout(
            columns_num=cols,
            columns_num_to_show=min(max(1, self.cols_show_spin.value()), max(1, cols)),
            cur_column_idx=0,
            rows_num=rows,
            rows_num_to_show=min(max(1, self.rows_show_spin.value()), max(1, rows)),
            cur_row_idx=0,
            enable_custom_layout=self.enable_cb.isChecked(),
            draw_borders=self.draw_borders_cb.isChecked(),
            layout_table=table,
        )


class GroupsLayoutDialog(QDialog):
    def __init__(self, groups: List[ChannelGroup], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Groups layout")
        self.resize(560, 420)
        self._rows: List[Tuple[QSpinBox, QDoubleSpinBox, QSpinBox, QDoubleSpinBox]] = []

        root = QVBoxLayout(self)
        caption = QLabel(
            "Arrange groups relative to each other. Groups sharing the same Row "
            "are placed side by side; each Row's height uses the maximum Height "
            "ratio among its groups, and Width ratio splits the horizontal space."
        )
        caption.setWordWrap(True)
        root.addWidget(caption)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        grid = QGridLayout(container)
        grid.setSpacing(4)
        for col, header in enumerate(["Group", "Row", "Height ratio", "Column", "Width ratio"]):
            label = QLabel(header)
            label.setStyleSheet("font-weight: bold;")
            grid.addWidget(label, 0, col)

        for row_idx, group in enumerate(groups, start=1):
            grid.addWidget(QLabel(group.name or f"Group {row_idx}"), row_idx, 0)
            row_spin = QSpinBox(); row_spin.setRange(0, 999)
            row_spin.setValue(int(group.group_layout.layout_row_idx))
            height_spin = QDoubleSpinBox(); height_spin.setRange(0.1, 1000.0); height_spin.setSingleStep(0.5)
            height_spin.setValue(float(group.group_layout.height_ratio))
            col_spin = QSpinBox(); col_spin.setRange(0, 999)
            col_spin.setValue(int(group.group_layout.layout_column_idx))
            width_spin = QDoubleSpinBox(); width_spin.setRange(0.1, 1000.0); width_spin.setSingleStep(0.5)
            width_spin.setValue(float(group.group_layout.width_ratio))
            grid.addWidget(row_spin, row_idx, 1)
            grid.addWidget(height_spin, row_idx, 2)
            grid.addWidget(col_spin, row_idx, 3)
            grid.addWidget(width_spin, row_idx, 4)
            self._rows.append((row_spin, height_spin, col_spin, width_spin))

        scroll.setWidget(container)
        root.addWidget(scroll, 1)

        actions = QHBoxLayout()
        self.reset_btn = QPushButton("Reset")
        actions.addWidget(self.reset_btn)
        actions.addStretch(1)
        self.cancel_btn = QPushButton("Cancel")
        self.save_btn = QPushButton("Save")
        actions.addWidget(self.cancel_btn)
        actions.addWidget(self.save_btn)
        root.addLayout(actions)

        self.reset_btn.clicked.connect(self._reset)
        self.cancel_btn.clicked.connect(self.reject)
        self.save_btn.clicked.connect(self.accept)

    def _reset(self):
        for row_spin, height_spin, col_spin, width_spin in self._rows:
            row_spin.setValue(0)
            height_spin.setValue(1.0)
            col_spin.setValue(0)
            width_spin.setValue(1.0)

    def get_group_layouts(self) -> List[GroupLayout]:
        return [
            GroupLayout(
                layout_row_idx=row_spin.value(),
                layout_column_idx=col_spin.value(),
                height_ratio=height_spin.value(),
                width_ratio=width_spin.value(),
            )
            for row_spin, height_spin, col_spin, width_spin in self._rows
        ]


class ClickableImageLabel(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._original_pixmap: Optional[QPixmap] = None

    def set_pixmap(self, pixmap: Optional[QPixmap], display_pixmap: Optional[QPixmap] = None):
        self._original_pixmap = pixmap
        if pixmap is None:
            self.clear()
            return
        self.setPixmap(display_pixmap or pixmap)

    def mouseDoubleClickEvent(self, event):
        if self._original_pixmap is None:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Channels mapping image")
        layout = QVBoxLayout(dialog)
        scroll = QScrollArea()
        label = QLabel()
        label.setPixmap(self._original_pixmap)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll.setWidget(label)
        scroll.setWidgetResizable(True)
        layout.addWidget(scroll)
        dialog.resize(800, 600)
        dialog.exec()


class SignalSettingsPanel(QWidget):
    def __init__(self, session_manager: QtEphyrSessionManagerWrapper, parent=None):
        super().__init__(parent)
        self._session_manager = session_manager
        self._updating = False
        self._group_list_widgets: Dict[int, QListWidget] = {}
        self._group_enabled_checkboxes: Dict[Tuple[int, int], QCheckBox] = {}
        self._last_groups_structure_signature: Tuple = tuple()
        self._rebuilding_groups = False
        self._mapping_pixmap: Optional[QPixmap] = None
        self._mapping_text: str = ""
        self._mapping_link_url: str = ""
        self._group_tabs_updating = False
        self._pending_group_tab_move: Optional[Tuple[int, int]] = None
        self.setup_ui()
        self.connect_signals()

    def _add_collapsible_section(self, parent_layout: QVBoxLayout, title: str):
        header_btn = QToolButton()
        header_btn.setText(title)
        header_btn.setCheckable(True)
        header_btn.setChecked(True)
        header_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        header_btn.setArrowType(Qt.ArrowType.DownArrow)
        header_btn.setStyleSheet("QToolButton { font-weight: bold; border: none; text-align: left; }")

        content = QFrame()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(8, 4, 0, 4)
        content_layout.setSpacing(8)

        def on_toggle(checked: bool):
            content.setVisible(checked)
            header_btn.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)

        header_btn.toggled.connect(on_toggle)
        parent_layout.addWidget(header_btn)
        parent_layout.addWidget(content)
        return content_layout

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(8)

        time_layout = self._add_collapsible_section(layout, "Time Settings")
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
        self.number_of_dots_spinbox = QSpinBox()
        self.number_of_dots_spinbox.setRange(
            settings.MIN_NUMBER_OF_DOTS_TO_DISPLAY,
            settings.MAX_NUMBER_OF_DOTS_TO_DISPLAY,
        )
        self.number_of_dots_spinbox.setSingleStep(100)
        self.duration_label = QLabel("Duration to show:")
        self.time_step_label = QLabel("Auto-scroll time step:")
        self.number_of_dots_label = QLabel("Number of dots to display:")
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
            time_layout.addLayout(row)
            if widget is self.current_sweep_spinbox:
                time_layout.addWidget(self.sweep_info_label)

        self.channels_layout = self._add_collapsible_section(layout, "Channel Management")

        dots_row = QHBoxLayout()
        dots_row.addWidget(self.number_of_dots_label)
        dots_row.addWidget(self.number_of_dots_spinbox)
        dots_row.addStretch(1)
        self.channels_layout.addLayout(dots_row)

        self.mapping_group = QGroupBox("Channels mapping image")
        mapping_layout = QVBoxLayout(self.mapping_group)
        buttons_layout = QHBoxLayout()
        self.btn_attach_link = QPushButton("Attach link")
        self.btn_attach_file = QPushButton("Attach file")
        buttons_layout.addWidget(self.btn_attach_link)
        buttons_layout.addWidget(self.btn_attach_file)
        buttons_layout.addStretch(1)
        mapping_layout.addLayout(buttons_layout)

        self.mapping_text_label = QLabel("")
        self.mapping_text_label.setWordWrap(True)
        self.mapping_text_label.setTextFormat(Qt.TextFormat.RichText)
        self.mapping_text_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.mapping_text_label.setOpenExternalLinks(False)
        mapping_layout.addWidget(self.mapping_text_label)

        self.mapping_image_label = ClickableImageLabel()
        self.mapping_image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.mapping_image_label.setMinimumWidth(settings.CHANNELS_MAPPING_IMG_DEFAULT_WIDTH)
        mapping_layout.addWidget(self.mapping_image_label)
        self.channels_layout.addWidget(self.mapping_group)

        instructions = QLabel("Drag&drop tabs to reorder groups. Select multiple channels, then Move selected to target group.")
        instructions.setWordWrap(True)
        instructions.setStyleSheet("color: gray; font-size: 9pt;")
        self.channels_layout.addWidget(instructions)
        btn_controls_row = QHBoxLayout()
        self.create_group_btn = QPushButton("Add channels group")
        self.groups_layout_btn = QPushButton("Groups layout")
        self.set_units_btn = QPushButton("Set units")
        btn_controls_row.addWidget(self.create_group_btn)
        btn_controls_row.addWidget(self.groups_layout_btn)
        btn_controls_row.addWidget(self.set_units_btn)
        self.channels_layout.addLayout(btn_controls_row)
        self.groups_tabs = QTabWidget()
        self.groups_tabs.setTabsClosable(True)
        self.groups_tabs.setMovable(True)
        self.channels_layout.addWidget(self.groups_tabs)
        layout.addStretch(1)

        # Expert-only fields are hidden until apply_gui_mode() enables them.
        self.apply_gui_mode(GuiMode.BEGINNER)

    def apply_gui_mode(self, gui_mode: GuiMode):
        is_expert = gui_mode == GuiMode.EXPERT
        self.number_of_dots_label.setVisible(is_expert)
        self.number_of_dots_spinbox.setVisible(is_expert)
        self.mapping_group.setVisible(is_expert)

    def connect_signals(self):
        self.current_sweep_spinbox.valueChanged.connect(lambda value: self._session_manager.set_current_sweep_idx(value - 1))
        self.start_point_spinbox.valueChanged.connect(self._session_manager.set_start_point)
        self.duration_spinbox.valueChanged.connect(self._on_duration_changed)
        self.time_step_spinbox.valueChanged.connect(self._session_manager.set_time_step_ms)
        self.autoscroll_step_interval_spinbox.valueChanged.connect(self._session_manager.set_autoscroll_step_interval_ms)
        self.number_of_dots_spinbox.valueChanged.connect(self._session_manager.set_number_of_dots_to_display)
        self.create_group_btn.clicked.connect(lambda: self._session_manager.add_channel_group("Group"))
        self.groups_layout_btn.clicked.connect(self.on_groups_layout_clicked)
        self.set_units_btn.clicked.connect(self.on_set_units_clicked)
        self.btn_attach_link.clicked.connect(self.on_attach_link_clicked)
        self.btn_attach_file.clicked.connect(self.on_attach_file_clicked)
        self.mapping_text_label.linkActivated.connect(self.on_mapping_link_activated)
        self.groups_tabs.tabCloseRequested.connect(self._on_group_tab_close_requested)
        self.groups_tabs.tabBar().tabMoved.connect(self._on_group_tab_moved)

        self._session_manager.session_loaded.connect(self.on_session_loaded)
        self._session_manager.channels_groups_changed.connect(self._on_channels_groups_changed)
        self._session_manager.start_point_changed.connect(self._sync_time_controls)
        self._session_manager.duration_ms_changed.connect(self._sync_time_controls)
        self._session_manager.current_sweep_idx_changed.connect(self._sync_time_controls)
        self._session_manager.time_step_ms_changed.connect(self._sync_time_controls)
        self._session_manager.autoscroll_step_interval_ms_changed.connect(self._sync_time_controls)
        self._session_manager.number_of_dots_to_display_changed.connect(self._sync_time_controls)
        self._session_manager.filters_changed.connect(self.on_filters_changed)
        self._session_manager.channels_mapping_img_changed.connect(self.on_channels_mapping_img_changed)
        self._session_manager.header_units_changed.connect(lambda _units: self.rebuild_groups_ui())

    def on_session_loaded(self):
        self._sync_time_controls()
        gui_setup = self._session_manager.gui_setup
        if not gui_setup:
            return
        updated_groups = [g.model_copy(deep=True) for g in gui_setup.channels_groups]
        changed = False
        for group in updated_groups:
            ensured = ensure_filters_list(group.filters)
            if ensured != group.filters:
                group.filters = ensured
                changed = True
        if changed:
            self._session_manager.set_channels_groups(updated_groups)
        self._update_mapping_display(gui_setup.channels_mapping_img)
        self.rebuild_groups_ui()

    def _on_duration_changed(self, duration_ms: int):
        """Keep the time-window center fixed when duration changes in Time settings."""
        if self._updating:
            return
        sm = self._session_manager
        gui_setup = sm.gui_setup
        header = sm.header
        if not gui_setup or not header or float(header.sample_rate) <= 0:
            sm.set_duration_ms(duration_ms)
            return

        old_duration_ms = int(gui_setup.duration_ms)
        old_start = int(gui_setup.start_point)
        sample_rate = float(header.sample_rate)
        center_sample = old_start + int((old_duration_ms / 2000.0) * sample_rate)

        sm.set_duration_ms(duration_ms)
        new_duration_ms = int(sm.gui_setup.duration_ms)
        half_visible = int((new_duration_ms / 2000.0) * sample_rate)
        sm.set_start_point(center_sample - half_visible)

    def _sync_time_controls(self):
        gui_setup = self._session_manager.gui_setup
        if not gui_setup:
            return
        self._updating = True
        current_sweep_idx = int(gui_setup.current_sweep_idx)
        sweeps_num = int(self._session_manager.header.number_of_sweeps) if self._session_manager.header else 1
        self.current_sweep_spinbox.setRange(1, max(1, sweeps_num))
        self.current_sweep_spinbox.setValue(min(max(1, current_sweep_idx + 1), max(1, sweeps_num)))
        self.start_point_spinbox.setValue(gui_setup.start_point)
        self.duration_spinbox.setValue(gui_setup.duration_ms)
        self.time_step_spinbox.setValue(gui_setup.time_step_ms)
        self.autoscroll_step_interval_spinbox.setValue(gui_setup.autoscroll_step_interval_ms)
        self.number_of_dots_spinbox.setValue(gui_setup.number_of_dots_to_display)
        self.duration_label.setText(f"Duration window {milliseconds_to_readable(gui_setup.duration_ms)}")
        self.time_step_label.setText(f"Auto-scroll time step {milliseconds_to_readable(gui_setup.time_step_ms)}")
        self._update_sweep_info_label(current_sweep_idx)
        self._updating = False

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

    def on_filters_changed(self):
        # Do not rebuild filter form here. This signal can be emitted from
        # a filter editor widget (e.g. QDoubleSpinBox.valueChanged); rebuilding
        # that form in the same call stack may delete the active Qt widget and crash.
        pass

    def _build_group_filters_setup(self, layout: QVBoxLayout, group_idx: int, group):
        filters = list(group.filters or [])
        if not filters:
            return

        filter_layout = QVBoxLayout()
        title = QLabel("Group filters")
        title.setStyleSheet("font-weight: bold;")
        filter_layout.addWidget(title)

        add_row = QHBoxLayout()
        add_row.addWidget(QLabel("Choose filter:"))
        selector = QComboBox()
        for flt in filters:
            selector.addItem(flt.filter_name)
        add_row.addWidget(selector, 1)
        filter_layout.addLayout(add_row)

        params_widget = QWidget()
        params_layout = QFormLayout(params_widget)
        params_layout.setContentsMargins(4, 4, 4, 4)
        params_layout.setFormAlignment(Qt.AlignmentFlag.AlignLeft)
        params_layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        filter_layout.addWidget(params_widget)

        enabled_label = QLabel()
        filter_layout.addWidget(enabled_label)

        disable_btn = QPushButton("Disable all")
        filter_layout.addWidget(disable_btn)
        layout.addLayout(filter_layout)

        def current_filters() -> List:
            gui_setup = self._session_manager.gui_setup
            if not gui_setup or not (0 <= group_idx < len(gui_setup.channels_groups)):
                return []
            return list(gui_setup.channels_groups[group_idx].filters or [])

        def save_filters(updated_filters: List):
            self._session_manager.set_channel_group_filters(group_idx, updated_filters)

        def sync_label(local_filters: List):
            enabled = [f.filter_name for f in local_filters if getattr(f, "enabled", False)]
            enabled_label.setText(f"Enabled: {', '.join(enabled) if enabled else 'None'}")

        def clear_form():
            while params_layout.rowCount():
                params_layout.removeRow(0)

        def update_filter_param(index: int, field: str, value):
            updated_filters = current_filters()
            if not (0 <= index < len(updated_filters)):
                return
            flt = updated_filters[index].model_copy()
            setattr(flt, field, value)
            if hasattr(flt, "sos_cache"):
                flt.sos_cache = {}
            updated_filters[index] = flt
            save_filters(updated_filters)
            sync_label(updated_filters)

        def build_form(index: int):
            local_filters = current_filters()
            if not (0 <= index < len(local_filters)):
                clear_form()
                return
            flt = local_filters[index]
            clear_form()
            enabled_checkbox = QCheckBox()
            enabled_checkbox.setChecked(bool(flt.enabled))
            enabled_checkbox.stateChanged.connect(
                lambda state, idx=index: update_filter_param(
                    idx, "enabled", Qt.CheckState(state) == Qt.CheckState.Checked
                )
            )
            params_layout.addRow("Enabled:", enabled_checkbox)
            if isinstance(flt, ButterworthLowPassFilter):
                cutoff = QDoubleSpinBox(); cutoff.setRange(0.1, 1e6); cutoff.setSingleStep(1.0); cutoff.setValue(float(flt.cutoff_hz))
                cutoff.valueChanged.connect(lambda value, idx=index: update_filter_param(idx, "cutoff_hz", value))
                order = QSpinBox(); order.setRange(1, 12); order.setValue(int(flt.order))
                order.valueChanged.connect(lambda value, idx=index: update_filter_param(idx, "order", value))
                params_layout.addRow("Cutoff (Hz):", cutoff); params_layout.addRow("Order:", order)
            elif isinstance(flt, ButterworthHighPassFilter):
                cutoff = QDoubleSpinBox(); cutoff.setRange(0.1, 1e6); cutoff.setSingleStep(1.0); cutoff.setValue(float(flt.cutoff_hz))
                cutoff.valueChanged.connect(lambda value, idx=index: update_filter_param(idx, "cutoff_hz", value))
                order = QSpinBox(); order.setRange(1, 12); order.setValue(int(flt.order))
                order.valueChanged.connect(lambda value, idx=index: update_filter_param(idx, "order", value))
                params_layout.addRow("Cutoff (Hz):", cutoff); params_layout.addRow("Order:", order)
            elif isinstance(flt, ButterworthBandPassFilter):
                lowcut = QDoubleSpinBox(); lowcut.setRange(0.1, 1e6); lowcut.setSingleStep(1.0); lowcut.setValue(float(flt.lowcut_hz))
                lowcut.valueChanged.connect(lambda value, idx=index: update_filter_param(idx, "lowcut_hz", value))
                highcut = QDoubleSpinBox(); highcut.setRange(0.1, 1e6); highcut.setSingleStep(1.0); highcut.setValue(float(flt.highcut_hz))
                highcut.valueChanged.connect(lambda value, idx=index: update_filter_param(idx, "highcut_hz", value))
                order = QSpinBox(); order.setRange(1, 12); order.setValue(int(flt.order))
                order.valueChanged.connect(lambda value, idx=index: update_filter_param(idx, "order", value))
                params_layout.addRow("Low cut (Hz):", lowcut); params_layout.addRow("High cut (Hz):", highcut)
                params_layout.addRow("Order:", order)
            elif isinstance(flt, ChebyshevBandPassFilter):
                lowcut = QDoubleSpinBox(); lowcut.setRange(0.1, 1e6); lowcut.setSingleStep(1.0); lowcut.setValue(float(flt.lowcut_hz))
                lowcut.valueChanged.connect(lambda value, idx=index: update_filter_param(idx, "lowcut_hz", value))
                highcut = QDoubleSpinBox(); highcut.setRange(0.1, 1e6); highcut.setSingleStep(1.0); highcut.setValue(float(flt.highcut_hz))
                highcut.valueChanged.connect(lambda value, idx=index: update_filter_param(idx, "highcut_hz", value))
                order = QSpinBox(); order.setRange(1, 12); order.setValue(int(flt.order))
                order.valueChanged.connect(lambda value, idx=index: update_filter_param(idx, "order", value))
                ripple = QDoubleSpinBox(); ripple.setRange(0.1, 10.0); ripple.setSingleStep(0.1); ripple.setValue(float(flt.ripple_db))
                ripple.valueChanged.connect(lambda value, idx=index: update_filter_param(idx, "ripple_db", value))
                params_layout.addRow("Low cut (Hz):", lowcut); params_layout.addRow("High cut (Hz):", highcut)
                params_layout.addRow("Order:", order); params_layout.addRow("Ripple (dB):", ripple)
            elif isinstance(flt, NotchFilter):
                freq = QDoubleSpinBox(); freq.setRange(1.0, 1e6); freq.setSingleStep(1.0); freq.setValue(float(flt.notch_freq_hz))
                freq.valueChanged.connect(lambda value, idx=index: update_filter_param(idx, "notch_freq_hz", value))
                q_factor = QDoubleSpinBox(); q_factor.setRange(0.1, 200.0); q_factor.setSingleStep(1.0); q_factor.setValue(float(flt.q_factor))
                q_factor.valueChanged.connect(lambda value, idx=index: update_filter_param(idx, "q_factor", value))
                params_layout.addRow("Notch (Hz):", freq); params_layout.addRow("Q factor:", q_factor)
            sync_label(local_filters)

        selector.currentIndexChanged.connect(build_form)

        def disable_all():
            updated_filters = []
            for flt in current_filters():
                copy_flt = flt.model_copy()
                copy_flt.enabled = False
                updated_filters.append(copy_flt)
            save_filters(updated_filters)
            sync_label(updated_filters)
            build_form(selector.currentIndex())

        disable_btn.clicked.connect(disable_all)
        sync_label(filters)
        selector.setCurrentIndex(0)
        build_form(0)

    def rebuild_groups_ui(self):
        gui_setup = self._session_manager.gui_setup
        header = self._session_manager.header
        if not gui_setup or not header:
            return
        self._rebuilding_groups = True
        prev_tab_idx = self.groups_tabs.currentIndex()
        self._group_tabs_updating = True
        self.groups_tabs.blockSignals(True)
        while self.groups_tabs.count():
            tab = self.groups_tabs.widget(0)
            self.groups_tabs.removeTab(0)
            if tab is not None:
                tab.deleteLater()
        self._group_list_widgets.clear()
        self._group_enabled_checkboxes.clear()

        for group_idx, group in enumerate(gui_setup.channels_groups):
            box = QWidget()
            box_layout = QVBoxLayout(box)

            form = QFormLayout()
            form.setFormAlignment(Qt.AlignmentFlag.AlignLeft)
            form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

            name_edit = QLineEdit()
            name_edit.setText(group.name)
            name_edit.editingFinished.connect(
                lambda idx=group_idx, w=name_edit: self._on_group_name_editing_finished(idx, w)
            )
            form.addRow("Name:", name_edit)

            shown = QCheckBox()
            shown.setChecked(group.is_shown)
            shown.stateChanged.connect(
                lambda state, idx=group_idx: self._session_manager.set_channel_group_field(
                    idx, is_shown=(Qt.CheckState(state) == Qt.CheckState.Checked)
                )
            )
            form.addRow("View:", shown)

            cut_traces = QCheckBox()
            cut_traces.setChecked(group.cut_traces)
            cut_traces.stateChanged.connect(
                lambda state, idx=group_idx: self._session_manager.set_cut_traces(
                    idx, Qt.CheckState(state) == Qt.CheckState.Checked
                )
            )
            form.addRow("Cut traces:", cut_traces)

            aux_checkbox = QCheckBox()
            aux_checkbox.setChecked(group.is_auxiliary)
            aux_checkbox.stateChanged.connect(
                lambda state, idx=group_idx: self._on_aux_changed(
                    idx, Qt.CheckState(state) == Qt.CheckState.Checked
                )
            )
            form.addRow("Auxiliary channels:", aux_checkbox)
            box_layout.addLayout(form)

            self._build_group_filters_setup(box_layout, group_idx, group)

            if not group.is_auxiliary:
                self._build_group_common_setup(box_layout, group.channel_indexes, gui_setup.channels_setup)

            channel_list = QListWidget()
            channel_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
            channel_list.setDragDropMode(QListWidget.DragDropMode.NoDragDrop)
            channel_list.setDragEnabled(False)
            channel_list.setAcceptDrops(False)
            self._group_list_widgets[group_idx] = channel_list
            for channel_idx in group.channel_indexes:
                self._add_channel_row(channel_list, group_idx, group, channel_idx, gui_setup.channels_setup)
            box_layout.addWidget(channel_list)

            btn_row = QHBoxLayout()
            reorder_btn = QPushButton("Layout")
            reorder_btn.clicked.connect(lambda _c=False, idx=group_idx: self._open_reorder_dialog(idx))
            enable_all = QPushButton("Enable all")
            enable_all.clicked.connect(lambda _c=False, idx=group_idx: self._set_group_enabled(idx, True))
            disable_all = QPushButton("Disable all")
            disable_all.clicked.connect(lambda _c=False, idx=group_idx: self._set_group_enabled(idx, False))
            btn_row.addWidget(reorder_btn)
            btn_row.addWidget(enable_all)
            btn_row.addWidget(disable_all)
            box_layout.addLayout(btn_row)

            move_row = QHBoxLayout()
            move_row.addWidget(QLabel("Move selected to"))
            move_combo = QComboBox()
            for to_idx, to_group in enumerate(gui_setup.channels_groups):
                if to_idx == group_idx:
                    continue
                move_combo.addItem(f"#{to_idx} {to_group.name}", to_idx)
            move_btn = QPushButton("Move")
            move_btn.clicked.connect(
                lambda _c=False, from_idx=group_idx, combo=move_combo: self._move_selected_to_group(
                    from_idx, int(combo.currentData()) if combo.currentData() is not None else -1
                )
            )
            move_row.addWidget(move_combo, 1)
            move_row.addWidget(move_btn)
            box_layout.addLayout(move_row)
            self.groups_tabs.addTab(box, group.name or f"Group {group_idx + 1}")
        if self.groups_tabs.count():
            self.groups_tabs.setCurrentIndex(min(max(prev_tab_idx, 0), self.groups_tabs.count() - 1))
        self.groups_tabs.blockSignals(False)
        self._group_tabs_updating = False
        self._rebuilding_groups = False
        self._last_groups_structure_signature = self._groups_structure_signature(gui_setup)

    @staticmethod
    def _groups_structure_signature(gui_setup) -> Tuple:
        return tuple(
            (
                group.name,
                tuple(group.channel_indexes),
                tuple(flt.filter_type for flt in (group.filters or [])),
                group.is_auxiliary,
            )
            for group in (gui_setup.channels_groups or [])
        )

    def _on_channels_groups_changed(self, _groups):
        gui_setup = self._session_manager.gui_setup
        if not gui_setup:
            return
        signature = self._groups_structure_signature(gui_setup)
        if signature == self._last_groups_structure_signature and self._group_enabled_checkboxes:
            self._sync_group_enabled_checkboxes()
            return
        self.rebuild_groups_ui()

    def _sync_group_enabled_checkboxes(self):
        gui_setup = self._session_manager.gui_setup
        if not gui_setup:
            return
        for group_idx, group in enumerate(gui_setup.channels_groups):
            enabled_set = set(group.enabled_indexes)
            for channel_idx in group.channel_indexes:
                checkbox = self._group_enabled_checkboxes.get((group_idx, channel_idx))
                if checkbox is None:
                    continue
                should_be_checked = channel_idx in enabled_set
                if checkbox.isChecked() == should_be_checked:
                    continue
                checkbox.blockSignals(True)
                checkbox.setChecked(should_be_checked)
                checkbox.blockSignals(False)

    def _build_group_common_setup(self, layout: QVBoxLayout, channel_indexes: List[int], channels_setup):
        if not channel_indexes:
            return
        sample = channels_setup.get(channel_indexes[0])
        scale_val = float(getattr(sample, "scale", settings.DEFAULT_SCALE))
        y_offset_val = float(getattr(sample, "y_offset", 0.0))
        color_val = str(getattr(sample, "color", "#000000"))

        form = QFormLayout()
        form.setFormAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        scale_spin = QDoubleSpinBox()
        scale_spin.setRange(settings.MIN_SCALE, settings.MAX_SCALE)
        scale_spin.setKeyboardTracking(False)
        scale_spin.setSingleStep(settings.SCALE_STEP)
        scale_spin.setValue(scale_val)
        y_offset_spin = QDoubleSpinBox()
        y_offset_spin.setRange(-1_000_000.0, 1_000_000.0)
        y_offset_spin.setKeyboardTracking(False)
        y_offset_spin.setSingleStep(10.0)
        y_offset_spin.setValue(y_offset_val)
        color_btn = QPushButton()
        color_btn.setProperty("color_str", color_val)
        color_btn.setStyleSheet(f"background-color: {color_val};")
        color_btn.setMaximumWidth(30)

        def apply_to_all():
            color_str = color_btn.property("color_str") or "#000000"
            self._session_manager.set_channels_setup(
                channel_indexes,
                scale=scale_spin.value(),
                y_offset=y_offset_spin.value(),
                color=color_str,
            )

        scale_spin.valueChanged.connect(lambda _v: apply_to_all())
        y_offset_spin.valueChanged.connect(lambda _v: apply_to_all())

        def on_pick_color():
            cur = QColor(color_btn.property("color_str"))
            if not cur.isValid():
                cur = QColor("#000000")
            new = QColorDialog.getColor(cur, self, "Select color")
            if not new.isValid():
                return
            color_btn.setProperty("color_str", new.name())
            color_btn.setStyleSheet(f"background-color: {new.name()};")
            apply_to_all()

        color_btn.clicked.connect(on_pick_color)
        form.addRow("Scale (uV):", scale_spin)
        form.addRow("Y offset:", y_offset_spin)
        form.addRow("Color:", color_btn)
        layout.addLayout(form)

    def _add_channel_row(self, channel_list: QListWidget, group_idx: int, group, channel_idx: int, channels_setup):
        channel_name = self.get_channel_name(channel_idx)
        setup = channels_setup.get(channel_idx)
        info = str(getattr(setup, "info", ""))
        widget = QWidget()
        root = QVBoxLayout(widget)
        root.setContentsMargins(2, 2, 2, 2)
        root.setSpacing(2)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(2)

        enabled_cb = QCheckBox()
        enabled_cb.setChecked(channel_idx in group.enabled_indexes)
        enabled_cb.stateChanged.connect(lambda state, idx=channel_idx, gidx=group_idx: self._on_channel_enabled(gidx, idx, state))
        self._group_enabled_checkboxes[(group_idx, channel_idx)] = enabled_cb
        row.addWidget(enabled_cb)
        row.addSpacing(10)
        row.addWidget(QLabel(f"{channel_idx} [{channel_name}]"), 1)
        info_edit = QLineEdit(info)
        info_edit.setPlaceholderText("Info, e.g. area")
        info_edit.setMinimumWidth(140)

        def apply_info():
            cur_setup = self._session_manager.gui_setup.channels_setup.get(channel_idx)
            self._session_manager.set_channel_setup(
                channel_idx,
                scale=float(getattr(cur_setup, "scale", settings.DEFAULT_SCALE)),
                y_offset=float(getattr(cur_setup, "y_offset", 0.0)),
                color=str(getattr(cur_setup, "color", "#000000")),
                info=info_edit.text().strip(),
            )

        info_edit.editingFinished.connect(apply_info)
        row.addWidget(info_edit)
        root.addLayout(row)

        if group.is_auxiliary:
            color = str(getattr(setup, "color", "#000000"))
            scale = float(getattr(setup, "scale", settings.DEFAULT_SCALE))
            y_offset = float(getattr(setup, "y_offset", 0.0))
            scale_spin = QDoubleSpinBox(); scale_spin.setRange(settings.MIN_SCALE, settings.MAX_SCALE)
            scale_spin.setKeyboardTracking(False)
            scale_spin.setSingleStep(settings.SCALE_STEP); scale_spin.setValue(scale)
            y_spin = QDoubleSpinBox(); y_spin.setRange(-1_000_000.0, 1_000_000.0)
            y_spin.setKeyboardTracking(False)
            y_spin.setSingleStep(10.0); y_spin.setValue(y_offset)
            color_btn = QPushButton(); color_btn.setProperty("color_str", color)
            color_btn.setStyleSheet(f"background-color: {color};"); color_btn.setMaximumWidth(30)

            def apply():
                self._session_manager.set_channel_setup(
                    channel_idx, scale=scale_spin.value(), y_offset=y_spin.value(),
                    color=color_btn.property("color_str") or "#000000",
                    info=info_edit.text().strip(),
                )

            scale_spin.valueChanged.connect(lambda _v: apply())
            y_spin.valueChanged.connect(lambda _v: apply())

            def pick_color():
                cur = QColor(color_btn.property("color_str"))
                new = QColorDialog.getColor(cur, self, "Select color")
                if not new.isValid():
                    return
                color_btn.setProperty("color_str", new.name())
                color_btn.setStyleSheet(f"background-color: {new.name()};")
                apply()

            color_btn.clicked.connect(pick_color)
            aux_row = QHBoxLayout()
            aux_row.addWidget(QLabel("S"))
            aux_row.addWidget(scale_spin)
            aux_row.addWidget(QLabel("Y"))
            aux_row.addWidget(y_spin)
            aux_row.addWidget(QLabel("C"))
            aux_row.addWidget(color_btn)
            aux_row.addStretch(1)
            root.addLayout(aux_row)

        item = QListWidgetItem(channel_list)
        item.setData(Qt.ItemDataRole.UserRole, channel_idx)
        item.setSizeHint(widget.sizeHint())
        channel_list.addItem(item)
        channel_list.setItemWidget(item, widget)

    def _open_reorder_dialog(self, group_idx: int):
        gui_setup = self._session_manager.gui_setup
        if not gui_setup or not (0 <= group_idx < len(gui_setup.channels_groups)):
            return
        group = gui_setup.channels_groups[group_idx]
        dialog = ChannelLayoutDialog(
            group.channel_indexes,
            group.channels_layout.model_copy(deep=True),
            self.get_channel_name,
            self,
            header=self._session_manager.header,
            ephyr_folder=(
                Path(self._session_manager.ephyr_experiment_folder)
                if self._session_manager.ephyr_experiment_folder
                else None
            ),
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._apply_group_channel_order(group_idx, dialog.get_order())
        self._session_manager.set_channels_layout(group_idx, dialog.get_channels_layout())

    def on_groups_layout_clicked(self):
        gui_setup = self._session_manager.gui_setup
        if not gui_setup or not gui_setup.channels_groups:
            return
        dialog = GroupsLayoutDialog(gui_setup.channels_groups, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._session_manager.set_group_layouts(dialog.get_group_layouts())

    def _apply_group_channel_order(self, group_idx: int, new_order: List[int]):
        gui_setup = self._session_manager.gui_setup
        if not gui_setup or not (0 <= group_idx < len(gui_setup.channels_groups)):
            return
        groups = [g.model_copy(deep=True) for g in gui_setup.channels_groups]
        group = groups[group_idx]
        enabled_set = set(group.enabled_indexes)
        group.channel_indexes = list(new_order)
        group.enabled_indexes = {idx for idx in new_order if idx in enabled_set}
        self._session_manager.set_channels_groups(groups)

    def _on_channel_enabled(self, group_idx: int, channel_idx: int, state: int):
        gui_setup = self._session_manager.gui_setup
        if not gui_setup or not (0 <= group_idx < len(gui_setup.channels_groups)):
            return
        groups = [g.model_copy(deep=True) for g in gui_setup.channels_groups]
        group = groups[group_idx]
        checked = Qt.CheckState(state) == Qt.CheckState.Checked
        if checked:
            group.enabled_indexes.add(channel_idx)
        else:
            group.enabled_indexes.discard(channel_idx)
        self._session_manager.set_channels_groups(groups)

    def _set_group_enabled(self, group_idx: int, enabled: bool):
        gui_setup = self._session_manager.gui_setup
        if not gui_setup or not (0 <= group_idx < len(gui_setup.channels_groups)):
            return
        groups = [g.model_copy(deep=True) for g in gui_setup.channels_groups]
        target = groups[group_idx]
        target.enabled_indexes = set(target.channel_indexes) if enabled else set()
        self._session_manager.set_channels_groups(groups)

    def _move_selected_to_group(self, from_group_idx: int, to_group_idx: int):
        if to_group_idx < 0:
            return
        widget = self._group_list_widgets.get(from_group_idx)
        if widget is None:
            return
        selected = []
        for item in widget.selectedItems():
            idx = item.data(Qt.ItemDataRole.UserRole)
            if idx is not None:
                selected.append(int(idx))
        self._session_manager.move_channels_to_group(selected, to_group_idx)

    def _on_remove_group(self, group_idx: int):
        gui_setup = self._session_manager.gui_setup
        if not gui_setup or not (0 <= group_idx < len(gui_setup.channels_groups)):
            return
        group = gui_setup.channels_groups[group_idx]
        if group.channel_indexes:
            QMessageBox.warning(self, "Remove group", "You cannot remove a non-empty group.")
            return
        self._session_manager.remove_channel_group(group_idx)

    def _on_group_tab_close_requested(self, tab_idx: int):
        if self._group_tabs_updating:
            return
        self._on_remove_group(tab_idx)

    def _on_group_name_editing_finished(self, group_idx: int, widget: QLineEdit):
        if self._rebuilding_groups:
            return
        gui_setup = self._session_manager.gui_setup
        if not gui_setup or not (0 <= group_idx < len(gui_setup.channels_groups)):
            return
        new_name = widget.text().strip() or "Group"
        old_name = gui_setup.channels_groups[group_idx].name
        if new_name == old_name:
            return
        self._session_manager.set_channel_group_field(group_idx, name=new_name)

    def _move_group(self, group_idx: int, delta: int):
        gui_setup = self._session_manager.gui_setup
        if not gui_setup:
            return
        groups = [g.model_copy(deep=True) for g in gui_setup.channels_groups]
        new_idx = group_idx + delta
        if new_idx < 0 or new_idx >= len(groups):
            return
        groups[group_idx], groups[new_idx] = groups[new_idx], groups[group_idx]
        for group in groups:
            group.channels_layout.cur_row_idx = 0
            group.channels_layout.cur_column_idx = 0
        self._session_manager.set_channels_groups(groups)

    def _on_group_tab_moved(self, from_idx: int, to_idx: int):
        if self._group_tabs_updating or from_idx == to_idx:
            return
        self._pending_group_tab_move = (from_idx, to_idx)
        # Rebuild happens from channels_groups_changed. Doing it synchronously
        # inside QTabBar.tabMoved may delete tabs while Qt still handles DnD.
        QTimer.singleShot(0, self._apply_pending_group_tab_move)

    def _apply_pending_group_tab_move(self):
        if self._group_tabs_updating:
            return
        if self._pending_group_tab_move is None:
            return
        from_idx, to_idx = self._pending_group_tab_move
        self._pending_group_tab_move = None
        gui_setup = self._session_manager.gui_setup
        if not gui_setup:
            return
        groups = [g.model_copy(deep=True) for g in gui_setup.channels_groups]
        if not (0 <= from_idx < len(groups) and 0 <= to_idx < len(groups)):
            return
        moved = groups.pop(from_idx)
        groups.insert(to_idx, moved)
        for group in groups:
            group.channels_layout.cur_row_idx = 0
            group.channels_layout.cur_column_idx = 0
        self._session_manager.set_channels_groups(groups)

    def _on_aux_changed(self, group_idx: int, is_auxiliary: bool):
        gui_setup = self._session_manager.gui_setup
        if not gui_setup or not (0 <= group_idx < len(gui_setup.channels_groups)):
            return
        current = gui_setup.channels_groups[group_idx]
        if current.is_auxiliary and not is_auxiliary:
            answer = QMessageBox.question(
                self,
                "Disable auxiliary mode",
                "All channels in this group will be reset to default scale/color/offset. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            self._session_manager.set_channels_setup(
                current.channel_indexes,
                scale=settings.DEFAULT_SCALE,
                y_offset=0.0,
                color="#000000",
            )
        self._session_manager.set_channel_group_field(group_idx, is_auxiliary=is_auxiliary)

    def get_channel_name(self, channel_idx: int) -> str:
        header = self._session_manager.header
        if (header and header.channel_info and header.channel_info.name
                and 0 <= channel_idx < len(header.channel_info.name)):
            base_name = header.channel_info.name[channel_idx]
            impedance_values = header.channel_info.impedance_ohm or []
            if channel_idx < len(impedance_values):
                formatted = self._format_impedance(impedance_values[channel_idx])
                if formatted:
                    return f"{base_name} ({formatted})"
            return base_name
        return f"Channel {channel_idx}"

    @staticmethod
    def _format_impedance(impedance_ohm: Optional[float]) -> str:
        if impedance_ohm is None:
            return ""
        try:
            val = float(impedance_ohm)
        except (TypeError, ValueError):
            return ""
        if val < 0:
            return ""
        units = ("Ohm", "kOhm", "MOhm", "GOhm")
        idx = 0
        while val >= 1000.0 and idx < len(units) - 1:
            val /= 1000.0
            idx += 1
        if val >= 100:
            text = f"{val:.0f}"
        elif val >= 10:
            text = f"{val:.1f}".rstrip("0").rstrip(".")
        else:
            text = f"{val:.2f}".rstrip("0").rstrip(".")
        return f"{text} {units[idx]}"

    def on_channels_mapping_img_changed(self, channels_mapping_img: str):
        self._update_mapping_display(channels_mapping_img)

    def on_set_units_clicked(self):
        if not self._session_manager.header:
            return
        HeaderUnitsManagementDialog(self._session_manager, self).exec()

    def on_attach_link_clicked(self):
        link, ok = QInputDialog.getText(self, "Attach link", "Paste image link:")
        if not ok:
            return
        self._session_manager.set_channels_mapping_img(link.strip())

    def on_attach_file_clicked(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select image",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.gif);;All Files (*)",
        )
        if not file_path:
            return
        try:
            with open(file_path, "rb") as file:
                data = file.read()
        except OSError:
            return
        mime, _ = mimetypes.guess_type(file_path)
        mime = mime or "image/png"
        encoded = base64.b64encode(data).decode("ascii")
        self._session_manager.set_channels_mapping_img(f"data:{mime};base64,{encoded}")

    def _update_mapping_display(self, channels_mapping_img: str):
        self._mapping_text = channels_mapping_img or ""
        self._mapping_pixmap = None
        self._mapping_link_url = ""
        self.mapping_image_label.set_pixmap(None)
        if not self._mapping_text:
            self.mapping_text_label.setText("")
            return

        if self._mapping_text.startswith("http://") or self._mapping_text.startswith("https://"):
            self._mapping_link_url = self._mapping_text
            self.mapping_text_label.setText('<a href="mapping">Attached link (click)</a> (double click to view)')
            try:
                with urllib.request.urlopen(self._mapping_text, timeout=5) as response:
                    raw = response.read()
            except Exception:
                self.mapping_text_label.setText('<a href="mapping">Attached link (click)</a><br>Failed to load image')
                return
            pixmap = QPixmap()
            if pixmap.loadFromData(raw):
                self._set_mapping_pixmap(pixmap)
            else:
                self.mapping_text_label.setText('<a href="mapping">Attached link (click)</a><br>Failed to decode image')
            return

        if self._mapping_text.startswith("data:"):
            self.mapping_text_label.setText("Attached file (double click to view)")
            parts = self._mapping_text.split(",", 1)
            if len(parts) != 2:
                self.mapping_text_label.setText("Failed to decode attached file")
                return
            try:
                raw = base64.b64decode(parts[1])
            except Exception:
                self.mapping_text_label.setText("Failed to decode attached file")
                return
            pixmap = QPixmap()
            if pixmap.loadFromData(raw):
                self._set_mapping_pixmap(pixmap)
            else:
                self.mapping_text_label.setText("Failed to decode attached file")
            return

        self.mapping_text_label.setText(self._mapping_text)

    def on_mapping_link_activated(self, _link: str):
        if self._mapping_link_url:
            QDesktopServices.openUrl(QUrl(self._mapping_link_url))

    def _set_mapping_pixmap(self, pixmap: QPixmap):
        self._mapping_pixmap = pixmap
        self._apply_scaled_pixmap()

    def _apply_scaled_pixmap(self):
        if self._mapping_pixmap is None:
            self.mapping_image_label.set_pixmap(None)
            return
        target_width = self.mapping_image_label.width()
        if target_width <= 1:
            target_width = settings.CHANNELS_MAPPING_IMG_DEFAULT_WIDTH
        display = self._mapping_pixmap.scaledToWidth(
            target_width,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.mapping_image_label.set_pixmap(self._mapping_pixmap, display)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._mapping_pixmap is not None:
            self._apply_scaled_pixmap()

