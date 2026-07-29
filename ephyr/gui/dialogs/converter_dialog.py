from pathlib import Path
from typing import Dict, Any

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QLabel,
    QDialogButtonBox,
    QCheckBox,
)

from ephyr.converter.source_reader.intan_rhs_source_reader import IntanRhdSourceReader, IntanRhsSourceReader
from ephyr.converter.source_reader.weegit_reader import WeegitSourceReader


class ConverterDialog(QDialog):
    def __init__(self, reader, output_folder: Path, parent=None):
        super().__init__(parent)
        self._reader = reader
        self._output_folder = output_folder
        self._group_intan_checkbox = None
        self.setWindowTitle("Convert to Ephyr")
        self.resize(540, 220)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        if isinstance(self._reader, IntanRhsSourceReader):
            source_name = "Intan RHS"
        elif isinstance(self._reader, IntanRhdSourceReader):
            source_name = "Intan RHD"
        elif isinstance(self._reader, WeegitSourceReader):
            source_name = "Weegit"
        else:
            source_name = self._reader.__class__.__name__

        source_label = QLabel(f"Detected source type: {source_name}")
        source_label.setWordWrap(True)
        layout.addWidget(source_label)

        if isinstance(self._reader, (IntanRhsSourceReader, IntanRhdSourceReader)):
            intan_files_count = self._reader.get_intan_files_count()
            intan_info = QLabel(f"Detected Intan files: {intan_files_count}")
            intan_info.setWordWrap(True)
            layout.addWidget(intan_info)
            if intan_files_count > 1:
                self._group_intan_checkbox = QCheckBox("Group all Intan files into one sweep")
                self._group_intan_checkbox.setChecked(True)
                layout.addWidget(self._group_intan_checkbox)
                intan_hint = QLabel(
                    "If disabled, each Intan file is converted to a separate sweep."
                )
                intan_hint.setWordWrap(True)
                layout.addWidget(intan_hint)

        confirmation = QLabel(
            f"Ephyr is going to create folder {self._output_folder} with the required files."
        )
        confirmation.setWordWrap(True)
        layout.addWidget(confirmation)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Proceed")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancel")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def conversion_options(self) -> Dict[str, Any]:
        options: Dict[str, Any] = {}
        if self._group_intan_checkbox is not None:
            options["group_intan_files_into_single_sweep"] = bool(self._group_intan_checkbox.isChecked())
        return options
