# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QHBoxLayout

from ephyr import version
from ephyr.gui._utils import resolve_app_icon_path
from ephyr.gui.hotkeys import get_hotkey_descriptions

_LOGO_SIZE = 192


class StartScreenPanel(QWidget):
    open_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(8)

        main_layout.addStretch(1)

        content = QWidget(self)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(10)

        logo = self._logo_label()
        if logo is not None:
            content_layout.addWidget(logo)

        title = QLabel(f"Ephyr v{version.__version__}")
        title_font = title.font()
        title_font.setPointSize(28)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        content_layout.addWidget(title)

        open_row = QHBoxLayout()
        open_row.setContentsMargins(0, 0, 0, 0)
        open_row.setSpacing(8)

        instruction = QLabel("Choose an experiment folder:")
        instruction.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        open_row.addWidget(instruction)

        open_link = QLabel('<a href="open">Open</a>')
        open_link.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        open_link.setOpenExternalLinks(False)
        open_link.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        open_link.linkActivated.connect(self._on_open_link_clicked)
        open_row.addWidget(open_link)
        open_row.addStretch(1)
        content_layout.addLayout(open_row)

        for shortcut_text in get_hotkey_descriptions():
            shortcut_label = QLabel(shortcut_text)
            shortcut_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            content_layout.addWidget(shortcut_label)

        content_row = QHBoxLayout()
        content_row.setContentsMargins(0, 0, 0, 0)
        content_row.addStretch(1)
        content_row.addWidget(content)
        content_row.addStretch(1)

        main_layout.addLayout(content_row)
        main_layout.addStretch(1)

    def _logo_label(self) -> QLabel | None:
        icon_path = resolve_app_icon_path()
        if icon_path is None:
            return None
        pixmap = QPixmap(str(icon_path))
        if pixmap.isNull():
            return None
        logo = QLabel(self)
        logo.setPixmap(
            pixmap.scaled(
                _LOGO_SIZE,
                _LOGO_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        logo.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        return logo

    def _on_open_link_clicked(self, _link: str):
        self.open_requested.emit()
