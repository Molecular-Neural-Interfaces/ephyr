# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

from platformdirs import user_data_dir
from pydantic import BaseModel, Field

from ephyr import settings
from ephyr.core.exceptions import BrokenGlobalStorageFileError


class GuiMode(str, Enum):
    BEGINNER = "beginner"
    EXPERT = "expert"

    @property
    def label(self) -> str:
        return {
            GuiMode.BEGINNER: "Beginner mode",
            GuiMode.EXPERT: "Expert mode",
        }[self]


class WorkspacePosition(BaseModel):
    """What was open in a workspace the last time, so it reopens in the same place."""
    config_id: Optional[str] = None
    record_id: Optional[str] = None
    session_name: Optional[str] = None
    # Last opened Record of each Config: offered as the settings source for new Records.
    last_record_by_config: Dict[str, str] = Field(default_factory=dict)


def default_local_add_ons_dir() -> Path:
    """Development add-ons folder used until the user picks another one."""
    return (Path.cwd() / "add_on_development").resolve()


class GlobalStorage(BaseModel):
    recent_workspaces: List[Path] = Field(default_factory=list)
    workspace_positions: Dict[str, WorkspacePosition] = Field(default_factory=dict)
    # Last known location of the recording each Record was converted from, on this machine only.
    record_source_paths: Dict[str, Path] = Field(default_factory=dict)
    gui_mode: GuiMode = GuiMode.BEGINNER
    # Absolute folder of local (development) add-ons. Unset uses ./add_on_development in the working directory.
    local_add_ons_dir: Optional[Path] = None

    def update_recent_workspaces_list(self, workspace_root: Path, to_delete: bool):
        try:
            self.recent_workspaces.remove(workspace_root)
        except ValueError:
            pass

        if not to_delete:
            self.recent_workspaces.insert(0, workspace_root)
            self.recent_workspaces = self.recent_workspaces[:settings.RECENT_WORKSPACES_LIST_MAX_LENGTH]


class GlobalStorageManager:
    def __init__(self):
        self._user_data_dir = Path(user_data_dir(settings.APP_NAME, appauthor=False))
        self._user_data_dir.mkdir(parents=True, exist_ok=True)

        self._global_storage_filepath = self._user_data_dir / settings.GLOBAL_STORAGE_FILENAME
        if self._global_storage_filepath.exists():
            try:
                with open(self._global_storage_filepath) as global_storage_filename:
                    self._global_storage = GlobalStorage.model_validate_json(global_storage_filename.read())
            except Exception:
                raise BrokenGlobalStorageFileError(self._global_storage_filepath)
        else:
            self._global_storage = GlobalStorage()
            self._save_global_storage()

    @property
    def recent_workspaces(self) -> List[Path]:
        return self._global_storage.recent_workspaces

    @property
    def gui_mode(self) -> GuiMode:
        return self._global_storage.gui_mode

    def set_gui_mode(self, gui_mode: GuiMode):
        self._global_storage.gui_mode = gui_mode
        self._save_global_storage()

    @property
    def local_add_ons_dir(self) -> Path:
        stored = self._global_storage.local_add_ons_dir
        if stored is None:
            return default_local_add_ons_dir()
        return Path(stored)

    def set_local_add_ons_dir(self, path: Path):
        self._global_storage.local_add_ons_dir = Path(path).resolve()
        self._save_global_storage()

    def update_recent_workspaces_list(self, workspace_root: Path, to_delete: bool = False):
        self._global_storage.update_recent_workspaces_list(Path(workspace_root), to_delete)
        self._save_global_storage()

    def workspace_position(self, workspace_uid: str) -> WorkspacePosition:
        return self._global_storage.workspace_positions.get(workspace_uid, WorkspacePosition())

    def remember_position(self, workspace_uid: str, config_id: Optional[str], record_id: Optional[str],
                          session_name: Optional[str]):
        position = self._global_storage.workspace_positions.setdefault(workspace_uid, WorkspacePosition())
        position.config_id = config_id
        position.record_id = record_id
        position.session_name = session_name
        if config_id and record_id:
            position.last_record_by_config[config_id] = record_id
        self._save_global_storage()

    def record_source_path(self, record_uid: str) -> Optional[Path]:
        return self._global_storage.record_source_paths.get(record_uid)

    def set_record_source_path(self, record_uid: str, path: Path):
        self._global_storage.record_source_paths[record_uid] = Path(path)
        self._save_global_storage()

    def _save_global_storage(self):
        with open(self._global_storage_filepath, "w") as session_file:
            session_file.write(self._global_storage.model_dump_json(indent=4))
