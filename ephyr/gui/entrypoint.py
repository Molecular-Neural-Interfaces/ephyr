import sys

from PyQt6 import QtWidgets

from ephyr.logger import ephyr_logger
from ephyr.gui.windows import MainWindow
from ephyr.core.ephyr_session import EphyrSessionManager
from ephyr.core.global_storage import GlobalStorageManager
from ephyr.gui.qt_ephyr_session_manager_wrapper import QtEphyrSessionManagerWrapper


def excepthook(exc_type, exc_value, exc_tb):
    print(exc_type, exc_value)
    msg = f"Unexpected error occurred"
    ephyr_logger().error(msg, exc_info=exc_value)
    QtWidgets.QApplication.exit(1)


def main():
    sys.excepthook = excepthook

    app = QtWidgets.QApplication(sys.argv)
    session_manager = EphyrSessionManager()
    session_manager_wrapper = QtEphyrSessionManagerWrapper(session_manager)
    global_storage_manager = GlobalStorageManager()
    main_window = MainWindow(session_manager_wrapper, global_storage_manager)
    screen = app.primaryScreen()
    main_window.move_to_center(screen)
    main_window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
