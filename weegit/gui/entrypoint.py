import sys

from PyQt6 import QtWidgets

from weegit.logger import weegit_logger
from weegit.gui.windows import MainWindow
from weegit.core.weegit_session import WeegitSessionManager
from weegit.core.global_storage import GlobalStorageManager
from weegit.gui.qt_weegit_session_manager_wrapper import QtWeegitSessionManagerWrapper


def excepthook(exc_type, exc_value, exc_tb):
    print(exc_type, exc_value)
    msg = f"Unexpected error occurred"
    weegit_logger().error(msg, exc_info=exc_value)
    QtWidgets.QApplication.exit(1)


def main():
    sys.excepthook = excepthook

    app = QtWidgets.QApplication(sys.argv)
    session_manager = WeegitSessionManager()
    session_manager_wrapper = QtWeegitSessionManagerWrapper(session_manager)
    global_storage_manager = GlobalStorageManager()
    main_window = MainWindow(session_manager_wrapper, global_storage_manager)
    screen = app.primaryScreen()
    main_window.move_to_center(screen)
    main_window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
