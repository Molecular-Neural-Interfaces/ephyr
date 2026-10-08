# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

import base64
import mimetypes
import urllib.request
from typing import Optional

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ephyr import settings
from ephyr.core.global_storage import GuiMode


class ClickableImageLabel(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._original_pixmap: Optional[QPixmap] = None

    def set_pixmap(self, pixmap: Optional[QPixmap], display_pixmap: Optional[QPixmap] = None):
        self._original_pixmap = pixmap
        if pixmap is None:
            self.clear()
            return
        self.setPixmap(display_pixmap or pixmap)

    def mouseDoubleClickEvent(self, event):
        if self._original_pixmap is None:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Visual attachment")
        layout = QVBoxLayout(dialog)
        scroll = QScrollArea()
        label = QLabel()
        label.setPixmap(self._original_pixmap)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll.setWidget(label)
        scroll.setWidgetResizable(True)
        layout.addWidget(scroll)
        dialog.resize(800, 600)
        dialog.exec()


class InformationPanel(QWidget):
    """Widget that represents an editable large text input"""

    def __init__(self, session_manager, parent=None):
        super().__init__(parent)
        self._session_manager = session_manager
        self._mapping_pixmap: Optional[QPixmap] = None
        self._mapping_text: str = ""
        self._mapping_link_url: str = ""
        self.setup_ui()
        self.connect_signals()
        self.apply_gui_mode(GuiMode.BEGINNER)

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        header_layout = QHBoxLayout()
        title_label = QLabel("Recording description")
        title_label.setStyleSheet("font-weight: bold;")
        header_layout.addWidget(title_label)
        header_layout.addStretch()

        self.text_edit = QTextEdit()
        self.text_edit.setPlaceholderText("Enter information here...")

        self.mapping_group = QGroupBox("Visual attachment")
        mapping_layout = QVBoxLayout(self.mapping_group)
        buttons_layout = QHBoxLayout()
        self.btn_attach_link = QPushButton("Attach link")
        self.btn_attach_file = QPushButton("Attach file")
        buttons_layout.addWidget(self.btn_attach_link)
        buttons_layout.addWidget(self.btn_attach_file)
        buttons_layout.addStretch(1)
        mapping_layout.addLayout(buttons_layout)

        self.mapping_text_label = QLabel("")
        self.mapping_text_label.setWordWrap(True)
        self.mapping_text_label.setTextFormat(Qt.TextFormat.RichText)
        self.mapping_text_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.mapping_text_label.setOpenExternalLinks(False)
        mapping_layout.addWidget(self.mapping_text_label)

        self.mapping_image_label = ClickableImageLabel()
        self.mapping_image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.mapping_image_label.setMinimumWidth(settings.VISUAL_ATTACHMENT_DEFAULT_WIDTH)
        mapping_layout.addWidget(self.mapping_image_label)

        layout.addLayout(header_layout)
        layout.addWidget(self.text_edit)
        layout.addWidget(self.mapping_group)

    def connect_signals(self):
        self.text_edit.textChanged.connect(self.on_text_changed)
        self.btn_attach_link.clicked.connect(self.on_attach_link_clicked)
        self.btn_attach_file.clicked.connect(self.on_attach_file_clicked)
        self.mapping_text_label.linkActivated.connect(self.on_mapping_link_activated)

        self._session_manager.session_loaded.connect(self.on_session_loaded)
        self._session_manager.visual_attachment_changed.connect(self.on_visual_attachment_changed)

    def apply_gui_mode(self, gui_mode: GuiMode):
        # self.mapping_group.setVisible(gui_mode == GuiMode.EXPERT)
        pass

    def on_text_changed(self):
        self._session_manager.set_experiment_description(experiment_description=self.text_edit.toPlainText())

    def on_session_loaded(self):
        session = self._session_manager.current_user_session
        if session is None:
            return
        self.text_edit.setText(session.experiment_description)
        gui_setup = self._session_manager.gui_setup
        self._update_mapping_display(gui_setup.visual_attachment if gui_setup else "")

    def on_visual_attachment_changed(self, visual_attachment: str):
        self._update_mapping_display(visual_attachment)

    def on_attach_link_clicked(self):
        link, ok = QInputDialog.getText(self, "Attach link", "Paste image link:")
        if not ok:
            return
        self._session_manager.set_visual_attachment(link.strip())

    def on_attach_file_clicked(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select image",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.gif);;All Files (*)",
        )
        if not file_path:
            return
        try:
            with open(file_path, "rb") as file:
                data = file.read()
        except OSError:
            return
        mime, _ = mimetypes.guess_type(file_path)
        mime = mime or "image/png"
        encoded = base64.b64encode(data).decode("ascii")
        self._session_manager.set_visual_attachment(f"data:{mime};base64,{encoded}")

    def _update_mapping_display(self, visual_attachment: str):
        self._mapping_text = visual_attachment or ""
        self._mapping_pixmap = None
        self._mapping_link_url = ""
        self.mapping_image_label.set_pixmap(None)
        if not self._mapping_text:
            self.mapping_text_label.setText("")
            return

        if self._mapping_text.startswith("http://") or self._mapping_text.startswith("https://"):
            self._mapping_link_url = self._mapping_text
            self.mapping_text_label.setText('<a href="mapping">Attached link (click)</a> (double click to view)')
            try:
                with urllib.request.urlopen(self._mapping_text, timeout=5) as response:
                    raw = response.read()
            except Exception:
                self.mapping_text_label.setText('<a href="mapping">Attached link (click)</a><br>Failed to load image')
                return
            pixmap = QPixmap()
            if pixmap.loadFromData(raw):
                self._set_mapping_pixmap(pixmap)
            else:
                self.mapping_text_label.setText('<a href="mapping">Attached link (click)</a><br>Failed to decode image')
            return

        if self._mapping_text.startswith("data:"):
            self.mapping_text_label.setText("Attached file (double click to view)")
            parts = self._mapping_text.split(",", 1)
            if len(parts) != 2:
                self.mapping_text_label.setText("Failed to decode attached file")
                return
            try:
                raw = base64.b64decode(parts[1])
            except Exception:
                self.mapping_text_label.setText("Failed to decode attached file")
                return
            pixmap = QPixmap()
            if pixmap.loadFromData(raw):
                self._set_mapping_pixmap(pixmap)
            else:
                self.mapping_text_label.setText("Failed to decode attached file")
            return

        self.mapping_text_label.setText(self._mapping_text)

    def on_mapping_link_activated(self, _link: str):
        if self._mapping_link_url:
            QDesktopServices.openUrl(QUrl(self._mapping_link_url))

    def _set_mapping_pixmap(self, pixmap: QPixmap):
        self._mapping_pixmap = pixmap
        self._apply_scaled_pixmap()

    def _apply_scaled_pixmap(self):
        if self._mapping_pixmap is None:
            self.mapping_image_label.set_pixmap(None)
            return
        target_width = self.mapping_image_label.width()
        if target_width <= 1:
            target_width = settings.VISUAL_ATTACHMENT_DEFAULT_WIDTH
        display = self._mapping_pixmap.scaledToWidth(
            target_width,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.mapping_image_label.set_pixmap(self._mapping_pixmap, display)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._mapping_pixmap is not None:
            self._apply_scaled_pixmap()
