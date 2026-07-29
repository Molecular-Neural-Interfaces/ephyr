from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit


class InformationPanel(QWidget):
    """Widget that represents an editable large text input"""

    def __init__(self, session_manager, parent=None):
        super().__init__(parent)
        self._session_manager = session_manager
        self.setup_ui()
        self.connect_signals()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        # Header
        header_layout = QHBoxLayout()
        title_label = QLabel("Experiment description")
        title_label.setStyleSheet("font-weight: bold;")

        header_layout.addWidget(title_label)
        header_layout.addStretch()

        # Text editor
        self.text_edit = QTextEdit()
        self.text_edit.setPlaceholderText("Enter information here...")

        layout.addLayout(header_layout)
        layout.addWidget(self.text_edit)

    def connect_signals(self):
        self.text_edit.textChanged.connect(self.on_text_changed)

        self._session_manager.session_loaded.connect(self.on_session_loaded)

    def on_text_changed(self):
        self._session_manager.set_experiment_description(experiment_description=self.text_edit.toPlainText())

    def on_session_loaded(self):
        self.text_edit.setText(self._session_manager.current_user_session.experiment_description)
