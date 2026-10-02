# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
)

from ephyr import version
from ephyr.gui._utils import resolve_app_icon_path


_ABOUT_DESCRIPTION = (
"""
This application is a lightweight yet powerful environment for multimodal annotation of electrophysiological data. It combines an adaptive interface with intelligent performance scaling to match your machine’s resources, ensuring stable real‑time operation even under heavy loads.

Fully open‑source and built in Python, the platform provides a flexible API for post‑annotation data access. Its add‑on architecture lets you extend functionality seamlessly without modifying the core codebase.
"""
)


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About Ephyr")
        self.setModal(True)
        self.resize(620, 360)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(16)

        icon_path = resolve_app_icon_path()
        if icon_path is not None:
            pixmap = QPixmap(str(icon_path))
            if not pixmap.isNull():
                icon_label = QLabel(self)
                icon_label.setPixmap(
                    pixmap.scaled(
                        96,
                        96,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                icon_label.setAlignment(Qt.AlignmentFlag.AlignTop)
                header.addWidget(icon_label)

        title_block = QVBoxLayout()
        title_block.setSpacing(6)

        title = QLabel(f"Ephyr v{version.__version__}", self)
        title_font = title.font()
        title_font.setPointSize(16)
        title_font.setBold(True)
        title.setFont(title_font)
        title_block.addWidget(title)

        description = QLabel(_ABOUT_DESCRIPTION, self)
        description.setWordWrap(True)
        description.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        title_block.addWidget(description)

        copyright_label = QLabel(
            "Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)\n"
            "Licensed under the GNU General Public License v3.0",
            self,
        )
        copyright_label.setWordWrap(True)
        copyright_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        title_block.addWidget(copyright_label)
        title_block.addStretch(1)

        header.addLayout(title_block, stretch=1)
        layout.addLayout(header)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
