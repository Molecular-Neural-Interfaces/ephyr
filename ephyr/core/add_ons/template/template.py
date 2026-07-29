# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
from PyQt6.QtCore import QRect
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QWidget

from ephyr.core.add_ons.base import BaseAddOn, ViewEntitiesZIndexEnum


class ExampleAddOn(BaseAddOn):
    Z_INDEX = ViewEntitiesZIndexEnum.TRACES.value + 1
    TRANSFORMATION = {transformation_enabled}
    VIEWABLE = {viewable_enabled}
    RUNNABLE = {runnable_enabled}
    REQUIRED_SAMPLE_RATE = 0.0

{transform_block}

{view_block}

{run_block}
