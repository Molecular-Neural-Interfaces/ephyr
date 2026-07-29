from PyQt6.QtWidgets import QDialog, QLabel, QLineEdit, QPushButton, QVBoxLayout


class SessionNameDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Session Name")

        # Create widgets
        self.label = QLabel("Enter unique session name:", self)
        self.line_edit = QLineEdit(self)
        self.button = QPushButton("Save", self)

        # Create layout and add widgets
        layout = QVBoxLayout()
        layout.addWidget(self.label)
        layout.addWidget(self.line_edit)
        layout.addWidget(self.button)
        self.setLayout(layout)

        # Connect the button click to the dialog's accept slot
        self.button.clicked.connect(self.accept)

    @property
    def result(self):
        return self.line_edit.text()
