import os.path
from pathlib import Path
from typing import List

from platformdirs import user_data_dir
from pydantic import BaseModel

from weegit import settings
from weegit.core.exceptions import BrokenGlobalStorageFileError


class GlobalStorage(BaseModel):
    recent_experiments: List[Path] = []

    def update_recent_experiments_list(self, opened_weegit_experiment_folder: Path, to_delete: bool):
        try:
            self.recent_experiments.remove(opened_weegit_experiment_folder)
        except ValueError:
            pass

        if not to_delete:
            self.recent_experiments.insert(0, opened_weegit_experiment_folder)
            self.recent_experiments = self.recent_experiments[:settings.RECENT_EXPERIMENTS_LIST_MAX_LENGTH]


class GlobalStorageManager:
    def __init__(self):
        self._user_data_dir = Path(user_data_dir(settings.APP_NAME, appauthor=False))
        self._user_data_dir.mkdir(exist_ok=True)

        self._global_storage_filepath = self._user_data_dir / settings.GLOBAL_STORAGE_FILENAME
        print(self._global_storage_filepath)
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
    def recent_experiments(self):
        return self._global_storage.recent_experiments

    def update_recent_experiments_list(self, opened_weegit_experiment_folder: Path, to_delete: bool = False):
        self._global_storage.update_recent_experiments_list(opened_weegit_experiment_folder, to_delete)
        self._save_global_storage()

    def _save_global_storage(self):
        with open(self._global_storage_filepath, "w") as session_file:
            session_file.write(self._global_storage.model_dump_json(indent=4))
