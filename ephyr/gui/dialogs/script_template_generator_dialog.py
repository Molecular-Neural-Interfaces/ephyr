from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from ephyr import settings
from ephyr.core.add_ons.script_template import render_script_template
from ephyr.gui.qt_ephyr_session_manager_wrapper import QtEphyrSessionManagerWrapper


class ScriptTemplateGeneratorDialog(QDialog):
    def __init__(self, session_manager: QtEphyrSessionManagerWrapper, parent=None):
        super().__init__(parent)
        self._session_manager = session_manager
        self._build_ui()
        self._set_defaults()

    def _build_ui(self):
        self.setWindowTitle("Generate Python script")
        self.resize(760, 280)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        form = QFormLayout()
        root.addLayout(form)

        folder_row = QHBoxLayout()
        self.ephyr_folder_input = QLineEdit()
        self.ephyr_folder_input.setPlaceholderText("/path/to/experiment_ephyr")
        self.btn_pick_ephyr_folder = QPushButton("Browse")
        self.btn_pick_ephyr_folder.clicked.connect(self._pick_ephyr_folder)
        folder_row.addWidget(self.ephyr_folder_input, 1)
        folder_row.addWidget(self.btn_pick_ephyr_folder)
        form.addRow("Ephyr folder:", folder_row)

        self.session_name_input = QLineEdit()
        self.session_name_input.setPlaceholderText("session name without .json")
        form.addRow("Session name:", self.session_name_input)

        output_row = QHBoxLayout()
        self.output_script_path_input = QLineEdit()
        self.output_script_path_input.setPlaceholderText("/path/to/generated_script.py")
        self.btn_pick_output_script = QPushButton("Browse")
        self.btn_pick_output_script.clicked.connect(self._pick_output_script)
        output_row.addWidget(self.output_script_path_input, 1)
        output_row.addWidget(self.btn_pick_output_script)
        form.addRow("Output script:", output_row)

        self.events_block_checkbox = QCheckBox("Include events block")
        self.events_block_checkbox.setChecked(True)
        form.addRow("Blocks:", self.events_block_checkbox)

        self.periods_block_checkbox = QCheckBox("Include periods block")
        self.periods_block_checkbox.setChecked(True)
        form.addRow("", self.periods_block_checkbox)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_generate = QPushButton("Generate")
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_generate.clicked.connect(self._on_generate_clicked)
        buttons.addWidget(self.btn_cancel)
        buttons.addWidget(self.btn_generate)
        root.addLayout(buttons)

    def _set_defaults(self):
        ephyr_folder = self._session_manager.ephyr_experiment_folder
        if ephyr_folder:
            self.ephyr_folder_input.setText(str(ephyr_folder))

        user_session = self._session_manager.current_user_session
        if user_session and user_session.session_filename:
            session_name = user_session.session_filename
            if session_name.endswith(settings.SESSION_EXTENSION):
                session_name = session_name[: -len(settings.SESSION_EXTENSION)]
            self.session_name_input.setText(session_name)

        default_dir = Path.cwd()
        if ephyr_folder:
            default_dir = Path(ephyr_folder)
        self.output_script_path_input.setText(str(default_dir / "generated_ephyr_script.py"))

    def _pick_ephyr_folder(self):
        selected = QFileDialog.getExistingDirectory(self, "Select ephyr experiment folder")
        if selected:
            self.ephyr_folder_input.setText(selected)

    def _pick_output_script(self):
        initial = self.output_script_path_input.text().strip() or "generated_ephyr_script.py"
        selected, _ = QFileDialog.getSaveFileName(
            self,
            "Save generated script",
            initial,
            "Python script (*.py)",
        )
        if selected:
            if not selected.endswith(".py"):
                selected += ".py"
            self.output_script_path_input.setText(selected)

    def _on_generate_clicked(self):
        ephyr_folder = self.ephyr_folder_input.text().strip()
        session_name = self.session_name_input.text().strip()
        output_script = self.output_script_path_input.text().strip()

        if not ephyr_folder:
            QMessageBox.warning(self, "Generate Python script", "Field [Ephyr folder] is required.")
            return
        if not Path(ephyr_folder).is_dir():
            QMessageBox.warning(self, "Generate Python script", "Field [Ephyr folder] must be an existing directory.")
            return
        if not session_name:
            QMessageBox.warning(self, "Generate Python script", "Field [Session name] is required.")
            return
        if not output_script:
            QMessageBox.warning(self, "Generate Python script", "Field [Output script] is required.")
            return

        output_path = Path(output_script)
        if output_path.suffix.lower() != ".py":
            output_path = output_path.with_suffix(".py")

        if output_path.exists():
            reply = QMessageBox.question(
                self,
                "Overwrite file",
                f"File already exists:\n{output_path}\n\nOverwrite it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            script_content = render_script_template(
                out_ephyr_folder=ephyr_folder,
                session_name=session_name,
                include_events_block=self.events_block_checkbox.isChecked(),
                include_periods_block=self.periods_block_checkbox.isChecked(),
            )
            output_path.write_text(script_content, encoding="utf-8")
        except Exception as exc:
            QMessageBox.warning(self, "Generate Python script", f"Failed to generate script: {exc}")
            return

        QMessageBox.information(
            self,
            "Generate Python script",
            f"Script generated:\n{output_path}",
        )
        self.accept()
