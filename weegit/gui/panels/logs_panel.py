from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QListWidgetItem, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, \
    QSizePolicy, QListWidget

from weegit import settings
from weegit.logger import weegit_logger, QLogHandler, get_log_directory, get_log_file_path


class LogsPanel(QWidget):
    """Widget that displays a list of text information (logs) with logging integration"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
        self.connect_to_log_handler()

    def setup_ui(self):
        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)

        # Create a container widget with fixed width policy
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(5)

        # Header with controls
        header_layout = QHBoxLayout()
        title_label = QLabel("Application Logs")
        title_label.setStyleSheet("font-weight: bold;")

        # Control buttons - make them compact
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setToolTip("Clear all logs")
        self.clear_btn.clicked.connect(self.clear_logs)
        self.clear_btn.setMaximumWidth(60)

        self.open_btn = QPushButton("Open")
        self.open_btn.setToolTip("Open log file")
        self.open_btn.clicked.connect(self.open_log_file)
        self.open_btn.setMaximumWidth(60)

        header_layout.addWidget(title_label)
        header_layout.addStretch()
        header_layout.addWidget(self.clear_btn)
        header_layout.addWidget(self.open_btn)

        # Log level filter
        filter_layout = QHBoxLayout()
        filter_label = QLabel("Filter:")
        filter_label.setMaximumWidth(40)

        self.log_level_combo = QComboBox()
        self.log_level_combo.addItems(["ALL", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
        self.log_level_combo.setCurrentText("INFO")
        self.log_level_combo.currentTextChanged.connect(self.filter_logs)
        self.log_level_combo.setMaximumWidth(120)

        filter_layout.addWidget(filter_label)
        filter_layout.addWidget(self.log_level_combo)
        filter_layout.addStretch()

        # Logs list with proper width constraints
        self.logs_list = QListWidget()
        self.configure_list_view()

        # Add everything to container layout
        container_layout.addLayout(header_layout)
        container_layout.addLayout(filter_layout)
        container_layout.addWidget(self.logs_list)

        # Add container to main layout
        main_layout.addWidget(container)

        # Set size policies
        self.setSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Expanding)
        container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def connect_to_log_handler(self):
        logger = weegit_logger()
        for handler in logger.handlers:
            if isinstance(handler, QLogHandler):
                handler.log_signal.connect(self.add_log)
                self.add_log(f'Logs are saved to {get_log_directory()}')

    def configure_list_view(self):
        """Configure the list view for optimal width usage"""
        self.logs_list.setWordWrap(True)
        self.logs_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.logs_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.logs_list.setTextElideMode(Qt.TextElideMode.ElideRight)

        # Set a reasonable minimum width
        self.logs_list.setMinimumWidth(250)

        # Use a monospace font for better log readability
        font = self.logs_list.font()
        font.setFamily("Courier New")
        font.setPointSize(12)
        self.logs_list.setFont(font)

    def resizeEvent(self, event):
        """Handle resize to maintain proper width constraints"""
        super().resizeEvent(event)

        # Ensure we respect parent width
        if self.parent():
            max_width = self.parent().width()
            current_width = self.width()

            # If we're wider than parent, adjust
            if current_width > max_width:
                self.setFixedWidth(max_width)
            else:
                self.setMaximumWidth(max_width)

    def filter_logs(self, level_filter: str):
        """Filter logs based on selected level"""
        level_priority = {
            "ALL": -1,
            "DEBUG": 0,
            "INFO": 1,
            "WARNING": 2,
            "ERROR": 3,
            "CRITICAL": 4
        }

        filter_priority = level_priority.get(level_filter, 1)

        for i in range(self.logs_list.count()):
            item = self.logs_list.item(i)
            if item:
                log_text = item.text().upper()
                log_level = self._parse_log_level(log_text)
                log_priority = level_priority.get(log_level, 1)

                if filter_priority == -1:  # ALL
                    item.setHidden(False)
                else:
                    item.setHidden(log_priority < filter_priority)

    def _parse_log_level(self, log_text: str) -> str:
        """Parse log level from log text"""
        log_text_upper = log_text.upper()
        if "CRITICAL" in log_text_upper:
            return "CRITICAL"
        elif "ERROR" in log_text_upper:
            return "ERROR"
        elif "WARNING" in log_text_upper:
            return "WARNING"
        elif "DEBUG" in log_text_upper:
            return "DEBUG"
        else:
            return "INFO"

    def _apply_log_level_color(self, item: QListWidgetItem, log_level: str, log_text: str):
        """Apply color coding based on log level"""
        if log_level == "ERROR" or log_level == "CRITICAL":
            item.setForeground(Qt.GlobalColor.red)
            item.setToolTip("Error level log message")
        elif log_level == "WARNING":
            item.setForeground(Qt.GlobalColor.darkYellow)
            item.setToolTip("Warning level log message")
        elif log_level == "INFO":
            item.setForeground(Qt.GlobalColor.green)
            item.setToolTip("Info level log message")
        elif log_level == "DEBUG":
            item.setForeground(Qt.GlobalColor.gray)
            item.setToolTip("Debug level log message")
        else:
            item.setForeground(Qt.GlobalColor.black)

    def _should_show_log(self, log_level: str) -> bool:
        """Check if log should be shown based on current filter"""
        current_filter = self.log_level_combo.currentText()
        if current_filter == "ALL":
            return True

        level_priority = {
            "DEBUG": 0,
            "INFO": 1,
            "WARNING": 2,
            "ERROR": 3,
            "CRITICAL": 4
        }

        filter_priority = level_priority.get(current_filter, 1)
        log_priority = level_priority.get(log_level, 1)
        return log_priority >= filter_priority

    def _limit_log_items(self):
        """Limit the number of log items to prevent memory issues"""
        if self.logs_list.count() > settings.MAX_LOG_ITEMS:
            # Remove hidden items first
            for i in range(min(100, self.logs_list.count())):
                item = self.logs_list.item(0)
                if item and item.isHidden():
                    self.logs_list.takeItem(0)
                else:
                    break

            while self.logs_list.count() > settings.MAX_LOG_ITEMS:
                self.logs_list.takeItem(0)

    def clear_logs(self):
        """Clear all logs"""
        self.logs_list.clear()
        weegit_logger().info("Logs cleared by user")

    def open_log_file(self):
        """Open the log file in the system default application"""
        log_path = get_log_file_path()
        if not log_path.exists():
            weegit_logger().warning(f"Log file not found: {log_path}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_path)))

    def add_log(self, log_text: str):
        """Add a log entry to the list (thread-safe through signal)"""
        try:
            # Parse log level from the message for coloring
            log_level = self._parse_log_level(log_text)

            item = QListWidgetItem(log_text)

            # Apply color based on log level
            self._apply_log_level_color(item, log_level, log_text)

            # Apply filtering
            if self._should_show_log(log_level):
                self.logs_list.addItem(item)
                self.logs_list.scrollToBottom()
                item.setHidden(False)
            else:
                self.logs_list.addItem(item)
                item.setHidden(True)

            # Limit the number of log items to prevent memory issues
            self._limit_log_items()

        except Exception as e:
            print(f"Error adding log: {e}")
