# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

from enum import Enum
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional

import numpy as np
from PyQt6.QtCore import QRect
from PyQt6.QtGui import QPainter, QColor
from PyQt6.QtWidgets import QWidget


class ViewEntitiesZIndexEnum(Enum):
    MIDDLE_LINE = 100
    TRACES = 200
    PERIODS = 300
    EVENTS = 400


class TransformationAddOn:
    TRANSFORMATION = False
    REQUIRED_SAMPLE_RATE = 0.0

    def transform(self, channel_data: np.ndarray, sample_rate: float):
        if not self.TRANSFORMATION:
            return channel_data

        raise NotImplementedError

    def required_sample_rate(self) -> float:
        return max(0.0, float(self.REQUIRED_SAMPLE_RATE))

    def applicable(self, channel_idx: int) -> bool:
        _ = channel_idx
        return True


class ViewableAddOn:
    VIEWABLE = False
    Z_INDEX = ViewEntitiesZIndexEnum.TRACES.value

    def view(
            self,
            add_on_data_dir: Path,

            # DATA
            processed_data: Dict[int, np.ndarray[np.float64]],
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

            # UI
            painter: QPainter,
            signal_widget: QWidget,
            # (channel_idx, cell_rect) for each enabled visible cell. With custom
            # layouts these cells form a 2D grid (multiple columns): map time to X
            # using each cell_rect's own left()/width() rather than signal_width.
            channel_rects: List[Tuple[int, QRect]],
            signal_width: int,
            draw_area_height: int,
            bg_color: QColor,
            grid_color: QColor,
            signal_color: QColor,
            text_color: QColor,
            axis_color: QColor,
    ):
        if not self.VIEWABLE:
            return

        raise NotImplementedError


class RunnableAddOn:
    RUNNABLE = False

    def run(self, session_manager, add_on_data_dir):
        if not self.RUNNABLE:
            return

        raise NotImplementedError


class BaseAddOn(TransformationAddOn, ViewableAddOn, RunnableAddOn):
    pass


def required_sample_rate_for_transformations(transformations: Optional[List[BaseAddOn]]) -> float:
    if not transformations:
        return 0.0
    required = 0.0
    for add_on in transformations:
        if getattr(add_on, "TRANSFORMATION", False):
            required = max(required, float(add_on.required_sample_rate()))
    return required
