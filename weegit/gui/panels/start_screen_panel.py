from __future__ import annotations

from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QHBoxLayout

from weegit import version
from weegit.gui.hotkeys import get_hotkey_descriptions


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

        title = QLabel(f"Weegit v{version.__version__}")
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

    def _on_open_link_clicked(self, _link: str):
        self.open_requested.emit()
