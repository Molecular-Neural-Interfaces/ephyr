from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, List, Dict, Any, Callable

import numpy as np
from PyQt6.QtCore import QByteArray, QBuffer, QIODevice, QPoint, QRect, QSize, Qt, QMimeData
from PyQt6.QtGui import QColor, QFont, QPainter, QPixmap, QRegion, QPen
from PyQt6.QtSvg import QSvgGenerator
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ephyr.core.ephyr_session import ChannelGroup


@dataclass(frozen=True)
class ScreenshotExportOptions:
    image_format: str  # "png" | "svg"
    action: str  # "copy" | "save"


@dataclass(frozen=True)
class ScreenshotRenderContext:
    signal_widget: QWidget
    top_navigator_widget: QWidget
    top_source_rect: QRect
    current_sweep_idx: int
    start_point: int
    duration_ms: float
    groups_layout: List[ChannelGroup]
    channels_setup: Dict[int, Any]
    footer_height: int = 38


@dataclass(frozen=True)
class ScreenshotExportResult:
    status: str  # "saved" | "copied" | "canceled" | "failed"
    message: str


class ScreenshotExportDialog(QDialog):
    """Reusable dialog for screenshot export options."""

    def __init__(self, parent=None, *, title: str = "Screenshot options"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(320, 120)

        self._selected_action: Optional[str] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        layout.addWidget(QLabel("Image format:", self))
        self.format_combo = QComboBox(self)
        self.format_combo.addItems(["png", "svg"])
        layout.addWidget(self.format_combo)

        buttons = QDialogButtonBox(self)
        self.copy_button = buttons.addButton("Copy to clipboard", QDialogButtonBox.ButtonRole.ActionRole)
        self.save_button = buttons.addButton("Save as file", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        layout.addWidget(buttons)

        self.copy_button.clicked.connect(self._on_copy_clicked)
        self.save_button.clicked.connect(self._on_save_clicked)
        buttons.rejected.connect(self.reject)

    def _on_copy_clicked(self):
        self._selected_action = "copy"
        self.accept()

    def _on_save_clicked(self):
        self._selected_action = "save"
        self.accept()

    def get_options(self) -> Optional[ScreenshotExportOptions]:
        if self.exec() != QDialog.DialogCode.Accepted or self._selected_action is None:
            return None
        return ScreenshotExportOptions(
            image_format=self.format_combo.currentText().lower(),
            action=self._selected_action,
        )

    @classmethod
    def run_export(cls, parent: QWidget, context: ScreenshotRenderContext) -> ScreenshotExportResult:
        if context.signal_widget.width() <= 0 or context.signal_widget.height() <= 0:
            return ScreenshotExportResult("failed", "Warning: signal widget is empty")

        options = cls(parent).get_options()
        if options is None:
            return ScreenshotExportResult("canceled", "Screenshot canceled")

        QApplication.processEvents()
        if options.action == "copy":
            if options.image_format == "png":
                QApplication.clipboard().setPixmap(cls._build_pixmap(context))
                return ScreenshotExportResult("copied", "Screenshot copied to clipboard (PNG)")

            mime_data = QMimeData()
            mime_data.setData("image/svg+xml", QByteArray(cls._build_svg_bytes(context)))
            # Add raster fallback for apps that cannot paste SVG payloads.
            mime_data.setImageData(cls._build_pixmap(context).toImage())
            QApplication.clipboard().setMimeData(mime_data)
            return ScreenshotExportResult("copied", "Screenshot copied to clipboard (SVG)")

        image_filter = "PNG Image (*.png)" if options.image_format == "png" else "SVG Image (*.svg)"
        save_path, _ = QFileDialog.getSaveFileName(
            parent,
            "Save screenshot",
            cls._default_filename(context, options.image_format),
            image_filter,
        )
        if not save_path:
            return ScreenshotExportResult("canceled", "Screenshot canceled")

        save_path = cls._ensure_extension(save_path, options.image_format)
        if options.image_format == "png":
            ok = cls._build_pixmap(context).save(save_path, "PNG")
        else:
            ok = cls._save_svg(save_path, context)
        if ok:
            return ScreenshotExportResult("saved", f"Screenshot saved: {save_path}")
        return ScreenshotExportResult("failed", "Failed to save screenshot")

    @classmethod
    def run_export_for_pixmap(
        cls,
        parent: QWidget,
        pixmap: QPixmap,
        *,
        default_name_prefix: str = "screenshot",
        vector_draw_fn: Optional[Callable[[QPainter], None]] = None,
        vector_size: Optional[QSize] = None,
    ) -> ScreenshotExportResult:
        if pixmap.isNull() or pixmap.width() <= 0 or pixmap.height() <= 0:
            return ScreenshotExportResult("failed", "Nothing to export")

        options = cls(parent).get_options()
        if options is None:
            return ScreenshotExportResult("canceled", "Screenshot canceled")

        if options.action == "copy":
            if options.image_format == "png":
                QApplication.clipboard().setPixmap(pixmap)
                return ScreenshotExportResult("copied", "Screenshot copied to clipboard (PNG)")

            if vector_draw_fn is not None:
                svg_bytes = cls._build_svg_bytes_from_draw_fn(vector_draw_fn, vector_size or pixmap.size())
            else:
                svg_bytes = cls._build_svg_bytes_from_pixmap(pixmap)
            mime_data = QMimeData()
            mime_data.setData("image/svg+xml", QByteArray(svg_bytes))
            mime_data.setImageData(pixmap.toImage())
            QApplication.clipboard().setMimeData(mime_data)
            return ScreenshotExportResult("copied", "Screenshot copied to clipboard (SVG)")

        image_filter = "PNG Image (*.png)" if options.image_format == "png" else "SVG Image (*.svg)"
        save_path, _ = QFileDialog.getSaveFileName(
            parent,
            "Save screenshot",
            cls._default_filename_from_prefix(default_name_prefix, options.image_format),
            image_filter,
        )
        if not save_path:
            return ScreenshotExportResult("canceled", "Screenshot canceled")

        save_path = cls._ensure_extension(save_path, options.image_format)
        if options.image_format == "png":
            ok = pixmap.save(save_path, "PNG")
        else:
            if vector_draw_fn is not None:
                ok = cls._save_svg_from_draw_fn(save_path, vector_draw_fn, vector_size or pixmap.size())
            else:
                ok = cls._save_svg_from_pixmap(save_path, pixmap)
        if ok:
            return ScreenshotExportResult("saved", f"Screenshot saved: {save_path}")
        return ScreenshotExportResult("failed", "Failed to save screenshot")

    @classmethod
    def _size(cls, context: ScreenshotRenderContext) -> QSize:
        top_height = max(0, context.top_navigator_widget.height())
        footer_height = cls._footer_height(context)
        return QSize(
            context.signal_widget.width(),
            top_height + context.signal_widget.height() + footer_height,
        )

    @classmethod
    def _format_scale(cls, value: float) -> str:
        return f"{value:.3f}".rstrip("0").rstrip(".")

    @classmethod
    def _build_non_aux_group_scales_text(cls, context: ScreenshotRenderContext) -> str:
        parts: List[str] = []
        for group in context.groups_layout:
            if group.is_auxiliary:
                continue
            channels = list(group.visible_channels())
            if not channels:
                continue

            scales: List[float] = []
            for ch_idx in channels:
                setup = context.channels_setup.get(ch_idx)
                scales.append(float(getattr(setup, "scale", 1.0) or 1.0))

            unique_scales = sorted({round(scale, 6) for scale in scales})
            group_name = str(group.name or "group")
            if len(unique_scales) == 1:
                parts.append(f"{group_name}: scale={cls._format_scale(unique_scales[0])} uV")
            else:
                parts.append(
                    f"{group_name}: scale={cls._format_scale(min(unique_scales))}.."
                    f"{cls._format_scale(max(unique_scales))} uV"
                )
        return " | ".join(parts)

    @classmethod
    def _footer_height(cls, context: ScreenshotRenderContext) -> int:
        group_scales_text = cls._build_non_aux_group_scales_text(context)
        return context.footer_height + (18 if group_scales_text else 0)

    @classmethod
    def _draw_composite(cls, painter: QPainter, context: ScreenshotRenderContext):
        size = cls._size(context)
        top_height = max(0, context.top_navigator_widget.height())
        signal_widget = context.signal_widget
        group_scales_text = cls._build_non_aux_group_scales_text(context)

        painter.fillRect(QRect(0, 0, size.width(), size.height()), QColor(255, 255, 255))

        if top_height > 0:
            painter.save()
            context.top_navigator_widget.render(
                painter,
                targetOffset=QPoint(0, 0),
                sourceRegion=QRegion(context.top_source_rect),
            )
            painter.restore()

        painter.save()
        painter.setClipping(False)
        painter.translate(0, top_height)
        signal_widget.render(
            painter,
            targetOffset=QPoint(0, 0),
            sourceRegion=QRegion(signal_widget.rect()),
        )
        painter.restore()

        base_footer_text = (
            f"current_sweep_idx={context.current_sweep_idx}    "
            f"start_point={context.start_point}    "
            f"duration_ms={context.duration_ms}"
        )
        painter.setPen(QColor(0, 0, 0))
        font = QFont()
        font.setPointSize(10)
        painter.setFont(font)
        footer_top = top_height + signal_widget.height()
        line_height = max(14, painter.fontMetrics().height())
        first_line_y = footer_top + 6 + line_height

        painter.drawText(12, first_line_y, base_footer_text)
        if group_scales_text:
            second_line_y = min(footer_top + cls._footer_height(context) - 6, first_line_y + line_height + 2)
            painter.drawText(12, second_line_y, group_scales_text)

    @classmethod
    def _build_pixmap(cls, context: ScreenshotRenderContext) -> QPixmap:
        size = cls._size(context)
        pixmap = QPixmap(size)
        pixmap.fill(QColor(255, 255, 255))
        painter = QPainter(pixmap)
        cls._draw_composite(painter, context)
        painter.end()
        return pixmap

    @classmethod
    def _build_svg_bytes(cls, context: ScreenshotRenderContext) -> bytes:
        size = cls._size(context)
        byte_array = QByteArray()
        buffer = QBuffer(byte_array)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)

        generator = QSvgGenerator()
        generator.setOutputDevice(buffer)
        generator.setSize(size)
        generator.setViewBox(QRect(0, 0, size.width(), size.height()))
        generator.setTitle("Ephyr Screenshot")

        painter = QPainter(generator)
        cls._draw_composite_vector_svg(painter, context)
        painter.end()
        buffer.close()
        return bytes(byte_array)

    @classmethod
    def _save_svg(cls, save_path: str, context: ScreenshotRenderContext) -> bool:
        size = cls._size(context)
        generator = QSvgGenerator()
        generator.setFileName(save_path)
        generator.setSize(size)
        generator.setViewBox(QRect(0, 0, size.width(), size.height()))
        generator.setTitle("Ephyr Screenshot")
        painter = QPainter(generator)
        if not painter.isActive():
            return False
        cls._draw_composite_vector_svg(painter, context)
        painter.end()
        return True

    @classmethod
    def _draw_composite_vector_svg(cls, painter: QPainter, context: ScreenshotRenderContext):
        size = cls._size(context)
        top_height = max(0, context.top_navigator_widget.height())
        signal_widget = context.signal_widget
        group_scales_text = cls._build_non_aux_group_scales_text(context)

        painter.fillRect(QRect(0, 0, size.width(), size.height()), QColor(255, 255, 255))
        if top_height > 0:
            painter.save()
            context.top_navigator_widget.render(
                painter,
                targetOffset=QPoint(0, 0),
                sourceRegion=QRegion(context.top_source_rect),
            )
            painter.restore()

        painter.save()
        painter.setClipping(False)
        cls._draw_signal_widget_vector(painter, signal_widget, y_offset=top_height)
        painter.restore()

        base_footer_text = (
            f"current_sweep_idx={context.current_sweep_idx}    "
            f"start_point={context.start_point}    "
            f"duration_ms={context.duration_ms}"
        )
        painter.setPen(QColor(0, 0, 0))
        font = QFont()
        font.setPointSize(10)
        painter.setFont(font)
        footer_top = top_height + signal_widget.height()
        line_height = max(14, painter.fontMetrics().height())
        first_line_y = footer_top + 6 + line_height
        painter.drawText(12, first_line_y, base_footer_text)
        if group_scales_text:
            second_line_y = min(footer_top + cls._footer_height(context) - 6, first_line_y + line_height + 2)
            painter.drawText(12, second_line_y, group_scales_text)

    @classmethod
    def _draw_signal_widget_vector(cls, painter: QPainter, signal_widget: QWidget, y_offset: int):
        sw = signal_widget
        left_margin = int(getattr(sw, "_left_margin", 80))
        width = sw.width()
        height = sw.height()
        bg_color = QColor(getattr(sw, "_BG_COLOR", QColor(240, 240, 240)))

        digital_rects = list(getattr(sw, "_digital_channel_rects", []))
        processed_data = dict(getattr(sw, "_processed_data", {}))
        channels_setup = dict(getattr(sw, "_channels_setup", {}))
        traces_are_visible = bool(getattr(sw, "_traces_are_visible", True))
        group_layouts = list(getattr(sw, "_group_layouts", []))
        aux_group_rects = list(getattr(sw, "_auxiliary_group_rects", []))
        signal_default_color = QColor(getattr(sw, "_SIGNAL_COLOR", QColor(0, 0, 0)))
        target_svg_dots = cls._target_svg_dots_for_main_signal(sw)

        painter.save()
        painter.setClipping(False)
        painter.translate(0, y_offset)
        painter.fillRect(QRect(0, 0, width, height), bg_color)

        # Draw signal-domain entities in the same coordinate system as pixmap_cache (x starts at 0).
        painter.save()
        painter.translate(left_margin, 0)
        painter.setClipping(False)
        sw._draw_group_separators(painter)
        if traces_are_visible:
            for _channel_idx, channel_rect in digital_rects:
                sw._draw_middle_line(painter, channel_rect)
            for draw_idx, (channel_idx, channel_rect) in enumerate(digital_rects):
                channel_data = processed_data.get(channel_idx)
                if channel_data is None:
                    continue
                cls._draw_trace_resampled(
                    painter=painter,
                    channel_data=channel_data,
                    channel_rect=channel_rect,
                    channel_idx=channel_idx,
                    channels_setup=channels_setup,
                    default_color=signal_default_color,
                    target_dots=target_svg_dots,
                )
        if bool(getattr(sw, "_periods_are_visible", True)):
            sw._draw_periods(painter)
        if bool(getattr(sw, "_events_are_visible", True)):
            sw._draw_events(painter)
        cls._draw_auxiliary_groups_resampled(
            painter=painter,
            processed_data=processed_data,
            channels_setup=channels_setup,
            group_layouts=group_layouts,
            aux_group_rects=aux_group_rects,
            axis_width=max(0, int(getattr(sw, "_axis_width", width - left_margin))),
            grid_color=QColor(getattr(sw, "_GRID_COLOR", QColor(200, 200, 200))),
            default_color=signal_default_color,
            target_dots=target_svg_dots,
        )
        painter.restore()

        # Draw channel labels and time axis in widget coordinates.
        for channel_idx, rect in digital_rects:
            sw.draw_channel_info(painter, channel_idx, rect)
        sw._draw_time_axis(painter, width, height)

        # Overlay: draw only measure bar primitives to keep SVG clean and vector-based.
        overlay = getattr(sw, "_overlay_widget", None)
        if overlay is not None:
            overlay_mode = getattr(overlay, "_overlay_mode", None)
            cursor_pos = getattr(overlay, "_cursor_pos", None)
            if (
                cursor_pos is not None
                and overlay_mode is not None
                and getattr(overlay_mode, "name", "") == "TIME_VOLTAGE_BAR"
            ):
                painter.save()
                painter.setPen(QPen(QColor(255, 0, 0)))
                painter.setFont(getattr(overlay, "_font", QFont()))
                if hasattr(overlay, "_draw_voltage_scale_bar"):
                    overlay._draw_voltage_scale_bar(painter)
                if hasattr(overlay, "_draw_time_scale_bar"):
                    overlay._draw_time_scale_bar(painter)
                painter.restore()
        painter.restore()

    @classmethod
    def _target_svg_dots_for_main_signal(cls, signal_widget: QWidget) -> int:
        sample_rate = float(getattr(signal_widget, "_sample_rate", 1.0))
        start_point = int(getattr(signal_widget, "_axis_start_point", 0))
        duration_ms = float(getattr(signal_widget, "_axis_duration_ms", 0.0))
        if sample_rate <= 0:
            return 2
        duration_points = int(round((duration_ms / 1000.0) * sample_rate))
        end_point = start_point + max(0, duration_points)
        dots = (
            end_point * (1000.0 / sample_rate)
            - start_point * (1000.0 / sample_rate)
        )
        return max(2, int(round(dots)))

    @classmethod
    def _resample_data_to_dots(cls, data: np.ndarray, target_dots: int) -> np.ndarray:
        if data is None or len(data) < 2:
            return data
        if target_dots <= 1:
            return data
        if len(data) == target_dots:
            return data
        old_x = np.linspace(0.0, 1.0, len(data), dtype=np.float64)
        new_x = np.linspace(0.0, 1.0, target_dots, dtype=np.float64)
        return np.interp(new_x, old_x, data).astype(np.float64)

    @classmethod
    def _draw_trace_resampled(
        cls,
        *,
        painter: QPainter,
        channel_data: np.ndarray,
        channel_rect: QRect,
        channel_idx: int,
        channels_setup: Dict[int, Any],
        default_color: QColor,
        target_dots: int,
    ):
        if channel_data is None or len(channel_data) < 2:
            return
        setup = channels_setup.get(channel_idx)
        color = QColor(str(getattr(setup, "color", "#000000")))
        if not color.isValid():
            color = default_color
        scale = float(getattr(setup, "scale", 1.0) or 1.0)
        y_offset = float(getattr(setup, "y_offset", 0.0))
        data = cls._resample_data_to_dots(channel_data, target_dots)
        n = len(data)
        if n < 2:
            return

        x_coords = np.linspace(channel_rect.left(), channel_rect.right(), n, dtype=np.float64)
        pixel_per_uv = channel_rect.height() / max(scale, 1e-12)
        y_mid = channel_rect.top() + channel_rect.height() / 2.0
        y_coords = y_mid - (data + y_offset) * pixel_per_uv
        top = channel_rect.top()
        bottom = channel_rect.bottom()

        painter.setPen(QPen(color, 1.2))
        prev_x = float(x_coords[0])
        prev_y = float(y_coords[0])
        for i in range(1, n):
            cur_x = float(x_coords[i])
            cur_y = float(y_coords[i])
            if top <= prev_y <= bottom and top <= cur_y <= bottom:
                painter.drawLine(int(prev_x), int(prev_y), int(cur_x), int(cur_y))
            prev_x = cur_x
            prev_y = cur_y

    @classmethod
    def _draw_auxiliary_groups_resampled(
        cls,
        *,
        painter: QPainter,
        processed_data: Dict[int, np.ndarray],
        channels_setup: Dict[int, Any],
        group_layouts: List[Dict[str, Any]],
        aux_group_rects: List[Any],
        axis_width: int,
        grid_color: QColor,
        default_color: QColor,
        target_dots: int,
    ):
        for group_idx, group_rect in aux_group_rects:
            if group_rect.height() <= 0:
                continue
            center_y = group_rect.top() + group_rect.height() / 2.0
            painter.setPen(QPen(grid_color, 1, Qt.PenStyle.DotLine))
            painter.drawLine(0, int(center_y), axis_width, int(center_y))

            channels = []
            if 0 <= int(group_idx) < len(group_layouts):
                channels = list(group_layouts[int(group_idx)].get("channels", []))
            for channel_idx in channels:
                data = processed_data.get(channel_idx)
                if data is None or len(data) < 2:
                    continue
                setup = channels_setup.get(channel_idx)
                color = QColor(str(getattr(setup, "color", "#000000")))
                if not color.isValid():
                    color = default_color
                scale = float(getattr(setup, "scale", 1.0) or 1.0)
                y_offset = float(getattr(setup, "y_offset", 0.0))
                data_rs = cls._resample_data_to_dots(data, target_dots)
                n = len(data_rs)
                if n < 2:
                    continue

                x_coords = np.linspace(0, max(0, axis_width - 1), n, dtype=np.float64)
                pixel_per_uv = group_rect.height() / max(scale, 1e-12)
                y_coords = center_y - (data_rs + y_offset) * pixel_per_uv
                top = group_rect.top()
                bottom = group_rect.bottom()

                painter.setPen(QPen(color, 1.1))
                prev_x = float(x_coords[0])
                prev_y = float(y_coords[0])
                for i in range(1, n):
                    cur_x = float(x_coords[i])
                    cur_y = float(y_coords[i])
                    if top <= prev_y <= bottom and top <= cur_y <= bottom:
                        painter.drawLine(int(prev_x), int(prev_y), int(cur_x), int(cur_y))
                    prev_x = cur_x
                    prev_y = cur_y

    @classmethod
    def _build_svg_bytes_from_pixmap(cls, pixmap: QPixmap) -> bytes:
        byte_array = QByteArray()
        buffer = QBuffer(byte_array)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        generator = QSvgGenerator()
        generator.setOutputDevice(buffer)
        generator.setSize(pixmap.size())
        generator.setViewBox(QRect(0, 0, pixmap.width(), pixmap.height()))
        generator.setTitle("Ephyr Screenshot")
        painter = QPainter(generator)
        painter.drawPixmap(0, 0, pixmap)
        painter.end()
        buffer.close()
        return bytes(byte_array)

    @classmethod
    def _save_svg_from_pixmap(cls, save_path: str, pixmap: QPixmap) -> bool:
        generator = QSvgGenerator()
        generator.setFileName(save_path)
        generator.setSize(pixmap.size())
        generator.setViewBox(QRect(0, 0, pixmap.width(), pixmap.height()))
        generator.setTitle("Ephyr Screenshot")
        painter = QPainter(generator)
        if not painter.isActive():
            return False
        painter.drawPixmap(0, 0, pixmap)
        painter.end()
        return True

    @classmethod
    def _build_svg_bytes_from_draw_fn(cls, draw_fn: Callable[[QPainter], None], size: QSize) -> bytes:
        byte_array = QByteArray()
        buffer = QBuffer(byte_array)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        generator = QSvgGenerator()
        generator.setOutputDevice(buffer)
        generator.setSize(size)
        generator.setViewBox(QRect(0, 0, size.width(), size.height()))
        generator.setTitle("Ephyr Screenshot")
        painter = QPainter(generator)
        draw_fn(painter)
        painter.end()
        buffer.close()
        return bytes(byte_array)

    @classmethod
    def _save_svg_from_draw_fn(cls, save_path: str, draw_fn: Callable[[QPainter], None], size: QSize) -> bool:
        generator = QSvgGenerator()
        generator.setFileName(save_path)
        generator.setSize(size)
        generator.setViewBox(QRect(0, 0, size.width(), size.height()))
        generator.setTitle("Ephyr Screenshot")
        painter = QPainter(generator)
        if not painter.isActive():
            return False
        draw_fn(painter)
        painter.end()
        return True

    @classmethod
    def _default_filename(cls, context: ScreenshotRenderContext, image_format: str) -> str:
        from datetime import datetime

        return (
            f"screenshot_sweep_{context.current_sweep_idx}_"
            f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.{image_format}"
        )

    @classmethod
    def _default_filename_from_prefix(cls, prefix: str, image_format: str) -> str:
        from datetime import datetime

        return f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{image_format}"

    @classmethod
    def _ensure_extension(cls, path: str, image_format: str) -> str:
        ext = f".{image_format}"
        if path.lower().endswith(ext):
            return path
        return path + ext
