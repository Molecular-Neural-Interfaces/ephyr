import sys
from PyQt6.QtWidgets import (QApplication, QDialog, QVBoxLayout,
                             QListWidget, QDialogButtonBox, QMessageBox)


class SelectSessionDialog(QDialog):
    def __init__(self, items, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select session")
        self.resize(300, 200)

        layout = QVBoxLayout(self)

        # Create list widget
        self.list_widget = QListWidget()
        self.list_widget.addItems(items)
        layout.addWidget(self.list_widget)

        # Create button box
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        layout.addWidget(self.button_box)

        # Connect signals
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        self.list_widget.itemDoubleClicked.connect(self.accept)

    def get_selected_item(self):
        if self.exec() == QDialog.DialogCode.Accepted:
            selected_items = self.list_widget.selectedItems()
            if selected_items:
                return selected_items[0].text()
        return None
