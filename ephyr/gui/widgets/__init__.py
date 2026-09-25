# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

from PyQt6.QtWidgets import QComboBox, QDoubleSpinBox, QSpinBox

from ephyr.gui.mixins.wheel_focus_mixin import WheelRequiresFocusMixin


class FocusWheelSpinBox(WheelRequiresFocusMixin, QSpinBox):
    pass


class FocusWheelDoubleSpinBox(WheelRequiresFocusMixin, QDoubleSpinBox):
    pass


class FocusWheelComboBox(WheelRequiresFocusMixin, QComboBox):
    pass
