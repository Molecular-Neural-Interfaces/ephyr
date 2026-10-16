# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

"""Dialogs of adding recordings to a workspace as Configs, Records and Sources."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Sequence, Tuple

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ephyr.converter.source_reader.abstract_source_reader import AbstractSourceReader, ConversionPlan
from ephyr.core.validation import Mismatch
from ephyr.gui._utils import milliseconds_to_readable, sample_rate_to_readable

RECORDING_FILE_FILTER = (
    "Supported recordings "
    "(*.lfp *.abf *.daq *.edf *.xdat *.xdat.json *.ncs *.nev *.nwb *.rhs *.rhd "
    "*.mcd *.raw *.mcsraw *.h5 *.hdf5 *.cmcr *.cmtr *.continuous *.dat *.oebin settings.xml);;"
    "WEEGIT files (*.lfp);;"
    "ABF files (*.abf);;DAQ files (*.daq);;EDF files (*.edf);;"
    "XDAT files (*.xdat *.xdat.json);;Neuralynx files (*.ncs *.nev);;NWB files (*.nwb);;"
    "Multi Channel Systems files (*.mcd *.raw *.mcsraw *.h5 *.hdf5 *.cmcr *.cmtr);;"
    "Intan files (*.rhs *.rhd settings.xml);;"
    "Open Ephys files (*.continuous *.dat *.oebin settings.xml);;All files (*)"
)


class RecordingPathDialog(QDialog):
    """A recording file or folder; folders get their own button because file dialogs cannot pick them."""

    def __init__(self, title: str, parent=None, initial: Optional[Path] = None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(620, 140)
        layout = QVBoxLayout(self)
        hint = QLabel("Select a recording file, or a folder for multi-file formats "
                      "(Neuralynx, Intan, Open Ephys).")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        row = QHBoxLayout()
        self.path_edit = QLineEdit(str(initial) if initial else "")
        file_button = QPushButton("File…")
        folder_button = QPushButton("Folder…")
        file_button.clicked.connect(self._choose_file)
        folder_button.clicked.connect(self._choose_folder)
        row.addWidget(self.path_edit, 1)
        row.addWidget(file_button)
        row.addWidget(folder_button)
        layout.addLayout(row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _choose_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select recording file", self.path_edit.text(),
                                              RECORDING_FILE_FILTER)
        if path:
            self.path_edit.setText(path)

    def _choose_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Select recording folder", self.path_edit.text(),
                                                QFileDialog.Option.ShowDirsOnly)
        if path:
            self.path_edit.setText(path)

    def _accept(self):
        if not self.path:
            return
        if not self.path.exists():
            QMessageBox.warning(self, "Invalid path", f"Selected path does not exist: {self.path}")
            return
        self.accept()

    @property
    def path(self) -> Optional[Path]:
        text = self.path_edit.text().strip()
        return Path(text) if text else None

    @staticmethod
    def get_path(title: str, parent=None, initial: Optional[Path] = None) -> Optional[Path]:
        dialog = RecordingPathDialog(title, parent, initial)
        return dialog.path if dialog.exec() else None


class ImportModeEnum(Enum):
    ADD_CONFIG = "add_config"
    ADD_RECORD = "add_record"
    ADD_SOURCE = "add_source"


def _source_duration_ms(source_plan) -> float:
    return source_plan.total_samples * 1000.0 / source_plan.sample_rate if source_plan.sample_rate > 0 else 0.0


class ImportDialog(QDialog):
    """Names, main source and reader options of a recording that is about to be converted."""

    def __init__(self, mode: ImportModeEnum, reader: AbstractSourceReader, plan: ConversionPlan,
                 parent=None, config_name: str = "", record_name: str = "",
                 warnings: Sequence[Mismatch] = ()):
        super().__init__(parent)
        self._mode = mode
        self._reader = reader
        self._plan = plan
        self._option_boxes: Dict[str, QCheckBox] = {}
        self.setWindowTitle({
            ImportModeEnum.ADD_CONFIG: "Add Config",
            ImportModeEnum.ADD_RECORD: "Add Record",
            ImportModeEnum.ADD_SOURCE: "Add Source",
        }[mode])
        self.resize(720, 420)
        self._build_ui(config_name, record_name, warnings)

    def _build_ui(self, config_name: str, record_name: str, warnings: Sequence[Mismatch]):
        layout = QVBoxLayout(self)
        ref = self._plan.ref
        detected = QLabel(f"Format: <b>{ref.format}</b>  ·  {ref.kind}: <b>{ref.name}</b><br>{ref.root}")
        detected.setWordWrap(True)
        detected.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(detected)

        self.sources_table = QTableWidget(len(self._plan.sources), 5)
        self.sources_table.setHorizontalHeaderLabels(["Source", "Sample rate", "Channels", "Segments", "Duration"])
        self.sources_table.verticalHeader().setVisible(False)
        self.sources_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.sources_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.sources_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for row, source_plan in enumerate(self._plan.sources):
            name_item = QTableWidgetItem(source_plan.name or source_plan.source_id)
            name_item.setData(Qt.ItemDataRole.UserRole, source_plan.source_id)
            if self._mode is ImportModeEnum.ADD_SOURCE:
                name_item.setFlags(name_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                name_item.setCheckState(Qt.CheckState.Checked)
            self.sources_table.setItem(row, 0, name_item)
            self.sources_table.setItem(row, 1, QTableWidgetItem(sample_rate_to_readable(source_plan.sample_rate)))
            self.sources_table.setItem(row, 2, QTableWidgetItem(str(source_plan.number_of_channels)))
            self.sources_table.setItem(row, 3, QTableWidgetItem(
                f"{len(source_plan.segments)} × {source_plan.segment_kind.label.lower()}"))
            self.sources_table.setItem(row, 4, QTableWidgetItem(
                milliseconds_to_readable(int(round(_source_duration_ms(source_plan))))))
        layout.addWidget(self.sources_table, 1)

        if self._plan.events or self._plan.periods:
            annotations = QLabel(f"Annotations in the recording: {len(self._plan.events)} events, "
                                 f"{len(self._plan.periods)} periods. They become the starting "
                                 f"annotations of every new session.")
            annotations.setWordWrap(True)
            layout.addWidget(annotations)

        form = QFormLayout()
        self.config_name_edit: Optional[QLineEdit] = None
        self.record_name_edit: Optional[QLineEdit] = None
        self.main_source_combo: Optional[QComboBox] = None
        if self._mode is ImportModeEnum.ADD_CONFIG:
            self.config_name_edit = QLineEdit(config_name)
            form.addRow("Config name:", self.config_name_edit)
            if len(self._plan.sources) > 1:
                self.main_source_combo = QComboBox()
                for source_plan in self._plan.sources:
                    self.main_source_combo.addItem(source_plan.name or source_plan.source_id, source_plan.source_id)
                form.addRow("Main source:", self.main_source_combo)
                hint = QLabel("Records added later to this Config are checked against the main source.")
                hint.setStyleSheet("color: gray; font-size: 9pt;")
                hint.setWordWrap(True)
                form.addRow("", hint)
        if self._mode in (ImportModeEnum.ADD_CONFIG, ImportModeEnum.ADD_RECORD):
            self.record_name_edit = QLineEdit(record_name or self._plan.recording_name or self._plan.ref.name)
            form.addRow("Record name:", self.record_name_edit)
        layout.addLayout(form)

        for option in self._reader.conversion_options():
            box = QCheckBox(option.label)
            box.setChecked(bool(self._plan.reader_options.get(option.key, option.default)))
            self._option_boxes[option.key] = box
            layout.addWidget(box)

        if warnings:
            text = "\n".join(f"• {mismatch_text(mismatch)}" for mismatch in warnings)
            warning_label = QLabel(f"Differences from the Config (not blocking):\n{text}")
            warning_label.setStyleSheet("color: #a06000;")
            warning_label.setWordWrap(True)
            layout.addWidget(warning_label)

        note = QLabel("Ephyr copies the signal into the workspace; the original files are not modified.")
        note.setStyleSheet("color: gray; font-size: 9pt;")
        note.setWordWrap(True)
        layout.addWidget(note)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Convert")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _accept(self):
        if self._mode is ImportModeEnum.ADD_SOURCE and not self.selected_source_ids():
            QMessageBox.warning(self, "No sources", "Select at least one source to add.")
            return
        self.accept()

    def config_name(self) -> str:
        return self.config_name_edit.text().strip() if self.config_name_edit else ""

    def record_name(self) -> str:
        return self.record_name_edit.text().strip() if self.record_name_edit else ""

    def main_source_id(self) -> str:
        if self.main_source_combo is not None:
            return str(self.main_source_combo.currentData())
        return self._plan.sources[0].source_id

    def selected_source_ids(self) -> List[str]:
        selected = []
        for row in range(self.sources_table.rowCount()):
            item = self.sources_table.item(row, 0)
            if item.checkState() == Qt.CheckState.Checked:
                selected.append(str(item.data(Qt.ItemDataRole.UserRole)))
        return selected

    def conversion_options(self) -> Dict[str, Any]:
        return {key: bool(box.isChecked()) for key, box in self._option_boxes.items()}


def mismatch_text(mismatch: Mismatch) -> str:
    where = f" (channel {mismatch.channel + 1})" if mismatch.channel is not None else ""
    return f"{mismatch.field}{where}: {mismatch.expected or '—'} in Config, {mismatch.actual or '—'} in recording"


class MismatchChoiceEnum(Enum):
    CONTINUE = "continue"
    NEW_CONFIG = "new_config"
    CANCEL = "cancel"


class MismatchDialog(QDialog):
    """Differences between the main source of a Config and the recording being added to it."""

    def __init__(self, config_name: str, mismatches: Sequence[Mismatch], parent=None):
        super().__init__(parent)
        self.choice = MismatchChoiceEnum.CANCEL
        blocking = any(mismatch.is_blocking for mismatch in mismatches)
        self.setWindowTitle("Recording does not match the Config" if blocking else "Differences from the Config")
        self.resize(720, 400)
        layout = QVBoxLayout(self)
        if blocking:
            text = (f"The recording cannot be added to Config <b>{config_name}</b>: its main source differs "
                    f"in the fields marked as blocking. Channel groups and settings of the Config refer to "
                    f"channels by position, so a different sample rate, channel set or channel order "
                    f"needs its own Config.")
        else:
            text = f"The recording differs from Config <b>{config_name}</b> only in descriptive fields."
        info = QLabel(text)
        info.setWordWrap(True)
        layout.addWidget(info)

        table = QTableWidget(len(mismatches), 5)
        table.setHorizontalHeaderLabels(["Field", "Channel", "In Config", "In recording", "Level"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for row, mismatch in enumerate(mismatches):
            values = [
                mismatch.field,
                str(mismatch.channel + 1) if mismatch.channel is not None else "",
                mismatch.expected or "—",
                mismatch.actual or "—",
                "blocking" if mismatch.is_blocking else "warning",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if mismatch.is_blocking:
                    item.setForeground(Qt.GlobalColor.darkRed)
                table.setItem(row, column, item)
        layout.addWidget(table, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        new_config = QPushButton("Create new Config from this recording")
        new_config.clicked.connect(lambda: self._finish(MismatchChoiceEnum.NEW_CONFIG))
        buttons.addWidget(cancel)
        buttons.addWidget(new_config)
        if not blocking:
            proceed = QPushButton(f"Add to {config_name}")
            proceed.setDefault(True)
            proceed.clicked.connect(lambda: self._finish(MismatchChoiceEnum.CONTINUE))
            buttons.addWidget(proceed)
        layout.addLayout(buttons)

    def _finish(self, choice: MismatchChoiceEnum):
        self.choice = choice
        self.accept()

    @staticmethod
    def ask(config_name: str, mismatches: Sequence[Mismatch], parent=None) -> MismatchChoiceEnum:
        dialog = MismatchDialog(config_name, mismatches, parent)
        dialog.exec()
        return dialog.choice


class MatchingConfigChoiceEnum(Enum):
    ADD_AS_RECORD = "add_as_record"
    NEW_CONFIG = "new_config"
    CANCEL = "cancel"


def ask_matching_config(parent, config_names: Sequence[str]) -> Tuple[MatchingConfigChoiceEnum, int]:
    """The recording fits existing Configs: add it as a Record to one of them or create a new Config."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle("Matching Config found")
    names = ", ".join(f"'{name}'" for name in config_names)
    box.setText(f"The recording has the same signal layout as Config {names}.")
    box.setInformativeText("Records of one Config share channel groups and settings. "
                           "Add the recording as a new Record there, or create a separate Config?")
    add_button = box.addButton(f"Add as Record to '{config_names[0]}'", QMessageBox.ButtonRole.AcceptRole)
    new_button = box.addButton("Create new Config", QMessageBox.ButtonRole.ActionRole)
    box.addButton(QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(add_button)
    box.exec()
    clicked = box.clickedButton()
    if clicked is add_button:
        return MatchingConfigChoiceEnum.ADD_AS_RECORD, 0
    if clicked is new_button:
        return MatchingConfigChoiceEnum.NEW_CONFIG, 0
    return MatchingConfigChoiceEnum.CANCEL, 0


def confirm_remove(parent, title: str, what: str, details: Sequence[str]) -> bool:
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle(title)
    box.setText(f"Remove {what}?")
    lines = list(details) + ["The original recording files are not touched.", "This cannot be undone."]
    box.setInformativeText("\n".join(lines))
    remove_button = box.addButton("Remove", QMessageBox.ButtonRole.DestructiveRole)
    box.addButton(QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(QMessageBox.StandardButton.Cancel)
    box.exec()
    return box.clickedButton() is remove_button


def ask_new_name(parent, title: str, current: str) -> Optional[str]:
    name, ok = QInputDialog.getText(parent, title, "New name:", QLineEdit.EchoMode.Normal, current)
    name = name.strip()
    if not ok or not name or name == current:
        return None
    return name


class ConversionCancelledError(Exception):
    pass


def run_with_progress(parent, title: str, generator: Generator[float, None, Any]) -> Any:
    """Drive a conversion generator that yields progress 0..1 and return its result.

    Cancelling closes the generator, which removes the partially written data.
    """
    progress = QProgressDialog(title, "Cancel", 0, 100, parent)
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setWindowTitle("Please wait")
    progress.setMinimumDuration(0)
    progress.show()
    QApplication.processEvents()
    try:
        while True:
            try:
                fraction = next(generator)
            except StopIteration as stop:
                return stop.value
            if progress.wasCanceled():
                generator.close()
                raise ConversionCancelledError()
            progress.setValue(int(round(max(0.0, min(1.0, fraction)) * 100)))
            QApplication.processEvents()
    finally:
        progress.close()


class ImportSettingsDialog(QDialog):
    """Pick a session of another Record of the same Config to copy GUI settings from."""

    def __init__(self, records: Sequence[Tuple[str, str, List[str]]], parent=None,
                 preferred: Optional[Tuple[str, str]] = None):
        """records: (record_id, record name, session names)."""
        super().__init__(parent)
        self.setWindowTitle("Import settings from Record")
        self.resize(520, 260)
        layout = QVBoxLayout(self)
        info = QLabel("Channel groups, channel setup, filters, add-on toggles, layer visibility, time window, "
                      "right panel and navigation mode are copied. The current segment, position and overlay "
                      "stay as they are.")
        info.setWordWrap(True)
        layout.addWidget(info)

        form = QFormLayout()
        self.record_combo = QComboBox()
        self.session_combo = QComboBox()
        self._records = list(records)
        for record_id, name, _sessions in self._records:
            self.record_combo.addItem(name, record_id)
        form.addRow("Record:", self.record_combo)
        form.addRow("Session:", self.session_combo)
        layout.addLayout(form)
        self.vocabularies_box = QCheckBox("Also import event and period vocabularies (merged by name)")
        self.vocabularies_box.setChecked(True)
        layout.addWidget(self.vocabularies_box)

        self.record_combo.currentIndexChanged.connect(self._fill_sessions)
        if preferred is not None:
            idx = self.record_combo.findData(preferred[0])
            if idx >= 0:
                self.record_combo.setCurrentIndex(idx)
        self._fill_sessions()
        if preferred is not None and preferred[1]:
            idx = self.session_combo.findText(preferred[1])
            if idx >= 0:
                self.session_combo.setCurrentIndex(idx)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Import")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._sync_ok()

    def _fill_sessions(self, *_args):
        self.session_combo.clear()
        idx = self.record_combo.currentIndex()
        if 0 <= idx < len(self._records):
            self.session_combo.addItems(self._records[idx][2])
        if hasattr(self, "_ok"):
            self._sync_ok()

    def _sync_ok(self):
        self._ok.setEnabled(self.session_combo.count() > 0)

    def selection(self) -> Tuple[str, str, bool]:
        return (str(self.record_combo.currentData()), self.session_combo.currentText(),
                self.vocabularies_box.isChecked())


class CreateWorkspaceDialog(QDialog):
    def __init__(self, parent=None, default_parent: Optional[Path] = None):
        super().__init__(parent)
        self.setWindowTitle("Create Ephyr Workspace")
        self.resize(560, 150)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name_edit = QLineEdit("")
        self.name_edit.setPlaceholderText("e.g. Hippocampus project")
        form.addRow("Name:", self.name_edit)
        parent_row = QWidget()
        parent_layout = QHBoxLayout(parent_row)
        parent_layout.setContentsMargins(0, 0, 0, 0)
        self.parent_edit = QLineEdit(str(default_parent or Path.home()))
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        parent_layout.addWidget(self.parent_edit, 1)
        parent_layout.addWidget(browse)
        form.addRow("Location:", parent_row)
        layout.addLayout(form)
        self.target_label = QLabel("")
        self.target_label.setStyleSheet("color: gray; font-size: 9pt;")
        layout.addWidget(self.target_label)
        self.name_edit.textChanged.connect(self._update_target)
        self.parent_edit.textChanged.connect(self._update_target)
        self._update_target()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Create")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(self, "Select location", self.parent_edit.text(),
                                                  QFileDialog.Option.ShowDirsOnly)
        if folder:
            self.parent_edit.setText(folder)

    def _update_target(self, *_args):
        from ephyr.core.workspace import Workspace
        name = self.name_edit.text().strip()
        self.target_label.setText(
            f"Folder: {Path(self.parent_edit.text()) / Workspace.default_folder_name(name)}" if name else "")

    def _accept(self):
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, "Name required", "Enter a workspace name.")
            return
        if not Path(self.parent_edit.text()).is_dir():
            QMessageBox.warning(self, "Invalid location", "Select an existing folder.")
            return
        self.accept()

    def values(self) -> Tuple[Path, str]:
        return Path(self.parent_edit.text()), self.name_edit.text().strip()
