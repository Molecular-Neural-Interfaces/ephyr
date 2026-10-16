# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import List, Optional

from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QHBoxLayout, QPushButton

from ephyr import version
from ephyr.gui._utils import resolve_app_icon_path
from ephyr.gui.hotkeys import get_hotkey_descriptions

_LOGO_SIZE = 192


class StartScreenStateEnum(Enum):
    NO_WORKSPACE = "no_workspace"
    EMPTY_WORKSPACE = "empty_workspace"
    EMPTY_CONFIG = "empty_config"
    NO_RECORD_OPEN = "no_record_open"


class StartScreenPanel(QWidget):
    create_workspace_requested = pyqtSignal()
    open_workspace_file_requested = pyqtSignal()
    open_workspace_folder_requested = pyqtSignal()
    recent_workspace_requested = pyqtSignal(Path)
    add_config_requested = pyqtSignal()
    add_record_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._recent: List[Path] = []
        self._setup_ui()
        self.set_state(StartScreenStateEnum.NO_WORKSPACE)

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

        # No workspace: Create / Open / Recent
        self.no_workspace_box = QWidget(content)
        box_layout = QVBoxLayout(self.no_workspace_box)
        box_layout.setContentsMargins(0, 0, 0, 0)
        box_layout.setSpacing(6)
        actions = QLabel('<a href="create">Create workspace</a> &nbsp;·&nbsp; '
                         '<a href="open_file">Open workspace file</a> &nbsp;·&nbsp; '
                         '<a href="open_folder">Open workspace folder</a>')
        actions.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        actions.setOpenExternalLinks(False)
        actions.linkActivated.connect(self._on_link)
        box_layout.addWidget(actions)
        # hint = QLabel("A workspace keeps converted recordings, sessions and add-on data. "
        #               "You can also drop a workspace folder or workspace.ephyr here.")
        # hint.setStyleSheet("color: gray;")
        # hint.setWordWrap(True)
        # box_layout.addWidget(hint)
        self.recent_label = QLabel("")
        # self.recent_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        # self.recent_label.setOpenExternalLinks(False)
        # self.recent_label.linkActivated.connect(self._on_recent_link)
        # box_layout.addWidget(self.recent_label)
        for shortcut_text in get_hotkey_descriptions():
            shortcut_label = QLabel(shortcut_text)
            shortcut_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            box_layout.addWidget(shortcut_label)
        content_layout.addWidget(self.no_workspace_box)

        # Workspace open, nothing to show yet
        self.empty_box = QWidget(content)
        empty_layout = QVBoxLayout(self.empty_box)
        empty_layout.setContentsMargins(0, 0, 0, 0)
        empty_layout.setSpacing(10)
        self.empty_label = QLabel("")
        self.empty_label.setWordWrap(True)
        empty_layout.addWidget(self.empty_label)
        buttons_row = QHBoxLayout()
        self.add_record_button = QPushButton("Add record")
        self.add_config_button = QPushButton("Add config")
        for button in (self.add_record_button, self.add_config_button):
            button.setMinimumHeight(40)
            button.setMinimumWidth(160)
            buttons_row.addWidget(button)
        buttons_row.addStretch(1)
        empty_layout.addLayout(buttons_row)
        drop_hint = QLabel("Or drop a recording file or folder here.")
        drop_hint.setStyleSheet("color: gray;")
        empty_layout.addWidget(drop_hint)
        self.add_config_button.clicked.connect(self.add_config_requested)
        self.add_record_button.clicked.connect(self.add_record_requested)
        content_layout.addWidget(self.empty_box)

        content_row = QHBoxLayout()
        content_row.setContentsMargins(0, 0, 0, 0)
        content_row.addStretch(1)
        content_row.addWidget(content)
        content_row.addStretch(1)

        main_layout.addLayout(content_row)
        main_layout.addStretch(1)

    def set_state(self, state: StartScreenStateEnum, workspace_name: str = "", config_name: str = ""):
        self.no_workspace_box.setVisible(state is StartScreenStateEnum.NO_WORKSPACE)
        self.empty_box.setVisible(state is not StartScreenStateEnum.NO_WORKSPACE)
        self.add_record_button.setVisible(state in (StartScreenStateEnum.EMPTY_CONFIG,
                                                    StartScreenStateEnum.NO_RECORD_OPEN))
        if state is StartScreenStateEnum.EMPTY_WORKSPACE:
            self.empty_label.setText(
                f"<b>{workspace_name}</b> is empty.<br>Add a config: the first recording defines "
                f"the signal layout (sample rate, channels, units) that later records are checked against."
            )
        elif state is StartScreenStateEnum.NO_RECORD_OPEN:
            self.empty_label.setText(
                f"Workspace <b>{workspace_name}</b>, config <b>{config_name}</b>.<br>"
                f"Select a record in Recording navigation, or add a new one."
            )
        elif state is StartScreenStateEnum.EMPTY_CONFIG:
            self.empty_label.setText(
                f"Config <b>{config_name}</b> has no records.<br>Add a recording with the same signal layout, "
                f"or add another config."
            )

    def set_recent_workspaces(self, recent: List[Path]):
        self._recent = list(recent)
        if not self._recent:
            self.recent_label.setText("")
            return
        links = "<br>".join(f'<a href="{idx}">{path}</a>' for idx, path in enumerate(self._recent))
        self.recent_label.setText(f"<b>Recent workspaces</b><br>{links}")

    def _on_link(self, link: str):
        {
            "create": self.create_workspace_requested,
            "open_file": self.open_workspace_file_requested,
            "open_folder": self.open_workspace_folder_requested,
        }[link].emit()

    def _on_recent_link(self, link: str):
        idx = int(link)
        if 0 <= idx < len(self._recent):
            self.recent_workspace_requested.emit(self._recent[idx])

    def _logo_label(self) -> Optional[QLabel]:
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
