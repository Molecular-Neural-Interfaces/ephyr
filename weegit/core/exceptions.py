from pathlib import Path


class BrokenSessionFileError(Exception):
    def __init__(self, session_file_path: Path):
        super().__init__(f"Broken session file: {session_file_path}.")
        self.session_file_path = session_file_path


class InvalidSessionNameError(Exception):
    def __init__(self, session_filename: str):
        super().__init__(f"Invalid weegit session name: {session_filename}.")
        self.session_filename = session_filename


class BrokenGlobalStorageFileError(Exception):
    def __init__(self, global_file_path: Path):
        super().__init__(f"Broken session file: {global_file_path}.")
        self.global_file_path = global_file_path


class SessionAlreadyExistsError(Exception):
    pass
