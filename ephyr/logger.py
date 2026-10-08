# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

import logging
import logging.handlers
import os
from enum import Enum
from pathlib import Path
from typing import Optional, Union
from platformdirs import user_log_dir

from PyQt6.QtCore import QObject, pyqtSignal

from ephyr import settings

_logger_set_up = False
_user_interface: Optional['UserInterface'] = None
_level: Optional[int] = None

_filename = 'log.txt'
_backup_count = 5
_max_file_size_kb = 512

_logger_name = 'ephyr'
_log_dir = 'log'
_env_var = 'EPHYR_LOG_DIRECTORY'

_experiment_log_dir = 'logs'
_experiment_log_filename = 'ephyr.log'

_experiment_folder: Optional[Path] = None
_session_name: Optional[str] = None

# _columns = ['[%(name)s]', '%(asctime)s', '%(threadName)s', '(%(thread)d)', '%(levelname)s',
#             '%(message)s']
_columns = ['%(asctime)s', '%(levelname)s', '%(message)s']
_separator = '\t'  # group separator
_escaped_separator = '\\t'

_dont_log_at_all = logging.CRITICAL + 1
_default_level = _dont_log_at_all
_minimal_qt_stream_level = logging.WARNING
_minimal_qt_file_level = logging.INFO


class UserInterface(str, Enum):
    qt = 'qt'
    tests = 'tests'


def _get_stream_handler(user_interface: UserInterface, level: int):
    handler = logging.StreamHandler()
    handler.setLevel(level)
    if user_interface != UserInterface.qt:
        handler.setLevel(_dont_log_at_all)
    else:
        handler.setLevel(min(level, _minimal_qt_stream_level))
    return handler


def _get_file_handler(user_interface: UserInterface, level: int, path: Path):
    os.makedirs(path.parent, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(filename=path,
                                                   maxBytes=_max_file_size_kb * 1024,
                                                   backupCount=_backup_count)
    if user_interface != UserInterface.qt:
        handler.setLevel(level)
    else:
        handler.setLevel(min(level, _minimal_qt_file_level))
    return handler


def _get_qt_handler(user_interface: UserInterface, level: int):
    handler = QLogHandler()
    handler.setLevel(min(level, _minimal_qt_file_level))
    return handler


class _SessionFormatter(logging.Formatter):
    """Prepends the current user session name (if any) to every record."""

    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)
        if _session_name:
            return f'[{_session_name}]{_separator}{message}'
        return message


def _get_formatter(user_interface: UserInterface) -> logging.Formatter:
    format_ = _separator.join(_columns)
    format_ = format_.format(interface=user_interface.value)
    return _SessionFormatter(format_)


def get_log_directory() -> Path:
    return get_log_file_path().parent


def get_log_file_path() -> Path:
    file_handler = _find_file_handler(logging.getLogger(_logger_name))
    if file_handler is not None:
        return Path(file_handler.baseFilename)
    return _target_log_file_path()


def _target_log_file_path() -> Path:
    if _experiment_folder is not None:
        return _experiment_folder / _experiment_log_dir / _experiment_log_filename
    return _get_global_log_directory() / _filename


def _get_global_log_directory() -> Path:
    return _get_env_log_directory() or _get_default_log_directory()


def _get_env_log_directory() -> Optional[Path]:
    directory = os.getenv(_env_var)
    if directory is None:
        return None
    return Path(directory)


def _get_default_log_directory() -> Path:
    return Path(settings.LOG_DIRECTORY) / _log_dir


def _find_file_handler(logger: logging.Logger) -> Optional[logging.FileHandler]:
    for handler in logger.handlers:
        if isinstance(handler, logging.FileHandler):
            return handler
    return None


def _file_logging_enabled(logger: logging.Logger) -> bool:
    handler = _find_file_handler(logger)
    return handler is not None and handler.level <= logging.CRITICAL


def _setup_handlers(logger: logging.Logger, user_interface: UserInterface, level: int):
    stream_handler = _get_stream_handler(user_interface, level)
    file_handler = _get_file_handler(user_interface, level, _target_log_file_path())
    qt_handler = _get_qt_handler(user_interface, level)

    formatter = _get_formatter(user_interface)

    for handler in logger.handlers:
        handler.close()
    logger.handlers.clear()
    if user_interface != UserInterface.tests:
        for handler in [stream_handler, file_handler, qt_handler]:
            handler.setFormatter(formatter)
            logger.addHandler(handler)
    else:
        file_handler.close()


def _switch_file_handler(logger: logging.Logger) -> None:
    """Point the file handler to the log file of the current experiment (or the global one)."""
    old_handler = _find_file_handler(logger)
    if old_handler is None:
        return

    new_path = _target_log_file_path()
    if Path(old_handler.baseFilename) == new_path.absolute():
        return

    try:
        new_handler = _get_file_handler(_user_interface, _level, new_path)
    except OSError as e:
        logger.warning(f'Cannot write logs to {new_path}: {e}. Keep logging to {old_handler.baseFilename}')
        return

    logger.info(f'Logs are switched to {new_path}')
    new_handler.setFormatter(old_handler.formatter)
    logger.removeHandler(old_handler)
    old_handler.close()
    logger.addHandler(new_handler)
    logger.info(f'Logs are saved to {new_path.parent}')


def set_log_experiment(experiment_folder: Optional[Path]) -> None:
    """Write logs into EXPERIMENT_ephyr/logs/ephyr.log; None switches back to the global log file."""
    global _experiment_folder
    _experiment_folder = Path(experiment_folder) if experiment_folder is not None else None
    _switch_file_handler(ephyr_logger())


def set_log_session_name(session_name: Optional[str]) -> None:
    """Session name to prefix every log record with; None or empty disables the prefix."""
    global _session_name
    _session_name = session_name or None


class QLogHandler(logging.Handler, QObject):
    """Custom logging handler that emits PyQt signals for log messages"""
    log_signal = pyqtSignal(str)  # Signal to emit log messages

    def __init__(self):
        logging.Handler.__init__(self)
        QObject.__init__(self)
        self.setFormatter(logging.Formatter('%(levelname)s - %(message)s', '%H:%M:%S'))

    def emit(self, record):
        """Emit log record as a formatted string"""
        try:
            msg = self.format(record)
            self.log_signal.emit(msg)
        except Exception:
            self.handleError(record)


def setup_logging(user_interface: Union[str, UserInterface], level: Optional[int] = None):
    global _logger_set_up, _user_interface, _level
    if level is None:
        level = _default_level

    user_interface = UserInterface(user_interface)
    _user_interface = user_interface
    _level = level
    logger = logging.getLogger(_logger_name)
    _setup_handlers(logger, user_interface, level)

    logger.setLevel(logging.DEBUG)  # desired level is specified on the handlers level

    if _file_logging_enabled(logger):
        logger.info(f'Logs are saved to {get_log_directory()}')

    _logger_set_up = True


class LoggerNotSetup(Exception):
    def __init__(self):
        super().__init__("setup_logging(..) has not been called. Please setup the logging first")


def ephyr_logger():
    if not _logger_set_up:
        # Auto-setup with reasonable defaults instead of throwing error
        setup_logging(UserInterface.qt, level=logging.DEBUG if settings.DEBUG else logging.INFO)

    return logging.getLogger(_logger_name)


__all__ = ['ephyr_logger', 'setup_logging', 'UserInterface', 'QLogHandler', 'get_log_directory',
           'get_log_file_path', 'set_log_experiment', 'set_log_session_name']
