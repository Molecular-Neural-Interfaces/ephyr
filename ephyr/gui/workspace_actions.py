# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

"""Add / Remove / Rename flows of Configs, Records and Sources of a workspace."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

from PyQt6.QtWidgets import QMessageBox, QWidget

from ephyr.converter.source_reader.abstract_source_reader import AbstractSourceReader, ConversionPlan
from ephyr.converter.source_reader.source_reader_factory import SourceReaderFactory
from ephyr.core import layout
from ephyr.core.fingerprint import fingerprint_of_ref
from ephyr.core.global_storage import GlobalStorageManager
from ephyr.core.manifests import Fingerprint
from ephyr.core.validation import has_blocking, match_config, matching_configs
from ephyr.core.workspace import RecordLocation, Workspace, disk_usage, format_size
from ephyr.gui.dialogs.converter_dialog import (
    ConversionCancelledError,
    ImportDialog,
    ImportModeEnum,
    MatchingConfigChoiceEnum,
    MismatchChoiceEnum,
    MismatchDialog,
    RecordingPathDialog,
    ask_matching_config,
    ask_new_name,
    confirm_remove,
    run_with_progress,
)
from ephyr.logger import ephyr_logger


class _Probe:
    """A resolved recording with its metadata plan and content fingerprint."""

    def __init__(self, path: Path):
        self.reader: AbstractSourceReader = SourceReaderFactory.get_reader(path)
        self.plan: ConversionPlan = self.reader.probe(scan=False)
        self.fingerprint: Fingerprint = fingerprint_of_ref(self.plan.ref)

    def scanned_plan(self, options) -> ConversionPlan:
        """Plan for conversion: options applied and calibration taken from the signal when the reader needs it."""
        self.reader.set_conversion_options(options)
        plan = self.reader.probe(scan=True)
        plan.reader_options = dict(options)
        return plan


class WorkspaceActions:
    def __init__(self, parent: QWidget, global_storage_manager: GlobalStorageManager):
        self._parent = parent
        self._storage = global_storage_manager

    # ----- helpers -----

    def _probe(self, path: Optional[Path], title: str) -> Optional[_Probe]:
        path = path or RecordingPathDialog.get_path(title, self._parent)
        if path is None:
            return None
        try:
            return _Probe(path)
        except Exception as exc:
            ephyr_logger().error(f"Cannot read {path}", exc_info=exc)
            QMessageBox.warning(self._parent, "Unsupported recording", f"Cannot read {path}:\n\n{exc}")
            return None

    def _check_duplicate(self, workspace: Workspace, probe: _Probe) -> bool:
        duplicate = workspace.find_duplicate(probe.fingerprint)
        if duplicate is None:
            return True
        config = workspace.config(duplicate.config_id)
        record = workspace.record(duplicate.config_id, duplicate.record_id)
        QMessageBox.information(
            self._parent, "Already imported",
            f"This recording is already in the workspace as Record "
            f"'{record.name if record else duplicate.record_id}' of Config "
            f"'{config.name if config else duplicate.config_id}'.",
        )
        return False

    def _convert(self, title: str, generator):
        try:
            return run_with_progress(self._parent, title, generator)
        except ConversionCancelledError:
            ephyr_logger().info("Conversion cancelled")
            return None
        except Exception as exc:
            ephyr_logger().error("Conversion failed", exc_info=exc)
            QMessageBox.critical(self._parent, "Conversion failed", f"Could not convert the recording:\n\n{exc}")
            return None

    def _remember_source_path(self, workspace: Workspace, location: RecordLocation, plan: ConversionPlan):
        record = workspace.record(location.config_id, location.record_id)
        if record is not None:
            self._storage.set_record_source_path(record.uid, plan.ref.root)

    # ----- add -----

    def add_config(self, workspace: Workspace, path: Optional[Path] = None) -> Optional[RecordLocation]:
        probe = self._probe(path, "Add Config")
        if probe is None or not self._check_duplicate(workspace, probe):
            return None
        matches = matching_configs(workspace.configs(), probe.plan)
        if matches:
            choice, _ = ask_matching_config(self._parent, [match.config.name for match in matches])
            if choice is MatchingConfigChoiceEnum.CANCEL:
                return None
            if choice is MatchingConfigChoiceEnum.ADD_AS_RECORD:
                return self._add_record_with_probe(workspace, matches[0].config.config_id, probe)
        return self._add_config_with_probe(workspace, probe)

    def _add_config_with_probe(self, workspace: Workspace, probe: _Probe) -> Optional[RecordLocation]:
        default_name = probe.plan.recording_name or probe.plan.ref.name
        dialog = ImportDialog(ImportModeEnum.ADD_CONFIG, probe.reader, probe.plan, self._parent,
                              config_name=default_name, record_name=default_name)
        if not dialog.exec():
            return None
        plan = probe.scanned_plan(dialog.conversion_options())
        location = self._convert(
            "Converting recording into the workspace…",
            workspace.add_config(plan, dialog.config_name() or default_name, dialog.record_name(),
                                 dialog.main_source_id(), probe.fingerprint),
        )
        if location is not None:
            self._remember_source_path(workspace, location, plan)
            ephyr_logger().info(f"Config '{location.config_id}' created with Record '{location.record_id}'")
        return location

    def add_record(self, workspace: Workspace, config_id: str,
                   path: Optional[Path] = None) -> Optional[RecordLocation]:
        probe = self._probe(path, "Add Record")
        if probe is None or not self._check_duplicate(workspace, probe):
            return None
        return self._add_record_with_probe(workspace, config_id, probe)

    def _add_record_with_probe(self, workspace: Workspace, config_id: str,
                               probe: _Probe) -> Optional[RecordLocation]:
        config = workspace.config(config_id)
        match = match_config(config, probe.plan)
        warnings = []
        if match.mismatches:
            if has_blocking(match.mismatches):
                choice = MismatchDialog.ask(config.name, match.mismatches, self._parent)
                if choice is MismatchChoiceEnum.NEW_CONFIG:
                    return self._add_config_with_probe(workspace, probe)
                return None
            warnings = match.mismatches
        dialog = ImportDialog(ImportModeEnum.ADD_RECORD, probe.reader, probe.plan, self._parent,
                              warnings=warnings)
        if not dialog.exec():
            return None
        plan = probe.scanned_plan(dialog.conversion_options())
        location = self._convert(
            f"Adding Record to '{config.name}'…",
            workspace.add_record(config_id, plan, dialog.record_name(), probe.fingerprint),
        )
        if location is not None:
            self._remember_source_path(workspace, location, plan)
            ephyr_logger().info(f"Record '{location.record_id}' added to Config '{config_id}'")
        return location

    def add_source(self, workspace: Workspace, config_id: str, record_id: str,
                   path: Optional[Path] = None) -> Optional[List[str]]:
        probe = self._probe(path, "Add Source")
        if probe is None or not self._check_duplicate(workspace, probe):
            return None
        dialog = ImportDialog(ImportModeEnum.ADD_SOURCE, probe.reader, probe.plan, self._parent)
        if not dialog.exec():
            return None
        plan = probe.scanned_plan(dialog.conversion_options())
        new_ids = self._convert(
            "Adding sources to the Record…",
            workspace.add_source(config_id, record_id, plan, dialog.selected_source_ids(), probe.fingerprint),
        )
        if new_ids:
            ephyr_logger().info(f"Sources {new_ids} added to Record '{record_id}'")
        return new_ids

    # ----- remove -----

    def confirm_remove_config(self, workspace: Workspace, config_id: str) -> bool:
        config = workspace.config(config_id)
        details = [
            f"Records: {len(config.records)}",
            f"Sessions: {workspace.sessions_count(config_id)}",
            f"Size on disk: {format_size(disk_usage(workspace.config_dir(config_id)))}",
        ]
        return confirm_remove(self._parent, "Remove Config", f"Config '{config.name}' with all its Records",
                              details)

    def confirm_remove_record(self, workspace: Workspace, config_id: str, record_id: str) -> bool:
        record = workspace.record(config_id, record_id)
        details = [
            f"Sources: {len(record.sources)}",
            f"Sessions: {workspace.sessions_count(config_id, record_id)}",
            f"Size on disk: {format_size(disk_usage(workspace.record_dir(config_id, record_id)))}",
        ]
        return confirm_remove(self._parent, "Remove Record", f"Record '{record.name}' with its sessions and "
                                                             f"add-on data", details)

    def confirm_remove_source(self, workspace: Workspace, config_id: str, record_id: str, source_id: str) -> bool:
        config = workspace.config(config_id)
        if source_id == config.main_source_id:
            QMessageBox.information(self._parent, "Main source",
                                    "The main source of a Config cannot be removed: Records are checked against it.")
            return False
        spec = config.source(source_id)
        folder = layout.source_dir(workspace.record_dir(config_id, record_id), source_id)
        details = [f"Size on disk: {format_size(disk_usage(folder))}",
                   "Other Records keep their copy of this source."]
        return confirm_remove(self._parent, "Remove Source",
                              f"source '{spec.name if spec else source_id}' of this Record", details)

    # ----- rename -----

    def rename_config(self, workspace: Workspace, config_id: str) -> bool:
        name = ask_new_name(self._parent, "Rename Config", workspace.config(config_id).name)
        if name is None:
            return False
        workspace.rename_config(config_id, name)
        return True

    def rename_record(self, workspace: Workspace, config_id: str, record_id: str) -> bool:
        name = ask_new_name(self._parent, "Rename Record", workspace.record(config_id, record_id).name)
        if name is None:
            return False
        workspace.rename_record(config_id, record_id, name)
        return True

    def rename_source(self, workspace: Workspace, config_id: str, source_id: str) -> bool:
        spec = workspace.config(config_id).source(source_id)
        name = ask_new_name(self._parent, "Rename Source", spec.name if spec else source_id)
        if name is None:
            return False
        workspace.rename_source(config_id, source_id, name)
        return True


def records_with_sessions(workspace: Workspace, config_id: str,
                          exclude_record_id: Optional[str]) -> List[Tuple[str, str, List[str]]]:
    """(record_id, name, session names) of the other Records of a Config that have sessions."""
    from ephyr.core.ephyr_session import UserSession
    result = []
    for record in workspace.records(config_id):
        if record.record_id == exclude_record_id:
            continue
        folder = layout.sessions_dir(workspace.record_dir(config_id, record.record_id))
        sessions = sorted(item.name for item in folder.iterdir()
                          if item.is_dir() and UserSession.is_session_folder(item)) if folder.is_dir() else []
        if sessions:
            result.append((record.record_id, record.name, sessions))
    return result
