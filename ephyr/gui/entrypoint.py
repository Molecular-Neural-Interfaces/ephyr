# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
#
# This file is part of Ephyr.
#
# Ephyr is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.
#
# Ephyr is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Ephyr. If not, see <https://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-only

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
