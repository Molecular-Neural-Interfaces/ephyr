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

_filename = 'log.txt'
_backup_count = 5
_max_file_size_kb = 512

_logger_name = 'ephyr'
_log_dir = 'log'
_env_var = 'EPHYR_LOG_DIRECTORY'

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


def _get_file_handler(user_interface: UserInterface, level: int):
    directory = get_log_directory()
    os.makedirs(directory, exist_ok=True)
    path = directory / _filename
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


def _get_formatter(user_interface: UserInterface) -> logging.Formatter:
    format_ = _separator.join(_columns)
    format_ = format_.format(interface=user_interface.value)
    return logging.Formatter(format_)


def get_log_directory() -> Path:
    return _get_env_log_directory() or _get_default_log_directory()


def get_log_file_path() -> Path:
    return get_log_directory() / _filename


def _get_env_log_directory() -> Optional[Path]:
    directory = os.getenv(_env_var)
    if directory is None:
        return None
    return Path(directory)


def _get_default_log_directory() -> Path:
    return Path(settings.LOG_DIRECTORY) / _log_dir


def _file_logging_enabled(logger: logging.Logger) -> bool:
    for handler in logger.handlers:
        if isinstance(handler, logging.FileHandler) and handler.level <= logging.CRITICAL:
            return True
    return False


def _setup_handlers(logger: logging.Logger, user_interface: UserInterface, level: int):
    stream_handler = _get_stream_handler(user_interface, level)
    file_handler = _get_file_handler(user_interface, level)
    qt_handler = _get_qt_handler(user_interface, level)

    formatter = _get_formatter(user_interface)

    logger.handlers.clear()
    if user_interface != UserInterface.tests:
        for handler in [stream_handler, file_handler, qt_handler]:
            handler.setFormatter(formatter)
            logger.addHandler(handler)


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
    global _logger_set_up
    if level is None:
        level = _default_level

    user_interface = UserInterface(user_interface)
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
           'get_log_file_path']
