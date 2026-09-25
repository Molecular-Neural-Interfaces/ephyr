# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QWheelEvent


class WheelRequiresFocusMixin:
    """Let an ancestor scroll area handle wheel events until this editor is focused."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event: QWheelEvent):
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()
