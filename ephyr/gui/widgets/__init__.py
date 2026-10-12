# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

from PyQt6.QtWidgets import QComboBox, QDoubleSpinBox, QSpinBox

from ephyr.gui.mixins.wheel_focus_mixin import WheelRequiresFocusMixin


class FocusWheelSpinBox(WheelRequiresFocusMixin, QSpinBox):
    pass


class FocusWheelDoubleSpinBox(WheelRequiresFocusMixin, QDoubleSpinBox):
    pass


class TrimmedDoubleSpinBox(FocusWheelDoubleSpinBox):
    """Keeps many decimals for precision but hides trailing zeros: 1000 instead of 1000.000000000."""

    def textFromValue(self, value: float) -> str:
        text = super().textFromValue(value)
        decimal_point = self.locale().decimalPoint()
        if decimal_point in text:
            text = text.rstrip("0").rstrip(decimal_point)
        return text


class FocusWheelComboBox(WheelRequiresFocusMixin, QComboBox):
    pass
