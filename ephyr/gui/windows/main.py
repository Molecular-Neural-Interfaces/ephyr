from __future__ import annotations

import os
import shutil
import subprocess
from copy import copy
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Optional, List, Dict
from enum import Enum

import numpy as np
from PyQt6.QtCore import Qt, QRect, QDir
from PyQt6.QtGui import QAction, QGuiApplication
from PyQt6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QSplitter,
    QFileDialog,
    QApplication, QStatusBar, QSizePolicy, QMessageBox, QProgressDialog,
    QFrame, QScrollArea, QStackedWidget, QComboBox,
)

from ephyr import settings
from ephyr import version
from ephyr.gui.mixins.qwidget_mixin import QWidgetMixin
from ephyr.gui._utils import capture_widget_to_file
from ephyr.core.ephyr_session import EphyrSessionManager, RightPanelWidgetEnum, UserSession
from ephyr.core.global_storage import GlobalStorageManager, GuiMode
from ephyr.converter.ephyr_io import EphyrIO
from ephyr.converter.legacy_mat_events import (
    LegacyMatEventsImportError,
    import_legacy_events_from_mat,
)
from ephyr.converter.source_reader.source_reader_factory import SourceReaderFactory
from ephyr.gui.dialogs.converter_dialog import ConverterDialog
from ephyr.gui.dialogs.session_name_dialog import SessionNameDialog
from ephyr.gui.dialogs.select_session_dialog import SelectSessionDialog
from ephyr.gui.dialogs.events_vocabulary_dialog import EventsVocabularyDialog
from ephyr.gui.dialogs.periods_vocabulary_dialog import PeriodsVocabularyDialog
from ephyr.gui.dialogs.add_ons_dialog import AddOnsDialog
from ephyr.gui.dialogs.add_on_development_dialog import AddOnDevelopmentDialog
from ephyr.gui.dialogs.script_template_generator_dialog import ScriptTemplateGeneratorDialog
from ephyr.gui.dialogs.screenshot_export_dialog import ScreenshotExportDialog, ScreenshotRenderContext
from ephyr.gui.dialogs.about_dialog import AboutDialog
from ephyr.gui.dialogs.hotkeys_dialog import HotkeysDialog
from ephyr.gui.panels.information_panel import InformationPanel
from ephyr.gui.panels.analysis_panel import AnalysisPanel
from ephyr.gui.panels.logs_panel import LogsPanel
from ephyr.gui.panels.signal_settings_panel import SignalSettingsPanel
from ephyr.gui.panels.signal_panel import SignalPanel
from ephyr.gui.panels.start_screen_panel import StartScreenPanel
from ephyr.gui.qt_ephyr_session_manager_wrapper import QtEphyrSessionManagerWrapper
from ephyr.logger import ephyr_logger


class EventCommandTypeEnum(Enum):
    ADD = "add"
    TOGGLE_BAD = "toggle_bad"
    REMOVE = "remove"


class MainWindow(QMainWindow, QWidgetMixin):
    """Main window for EEG analysis application.

    - Resizable window with initial size 800x600.
    - Menu bar with File, View, Filters.
    - Header with filename label and four action buttons.
    - Vertical splitter with main EEG panel and optional Analogue panel.
    - Right panel for additional widgets like Logs and Information.
    """

    def __init__(self, session_manager: QtEphyrSessionManagerWrapper, global_storage_manager: GlobalStorageManager):
        super().__init__()
        self.setWindowTitle(f"Ephyr v{version.__version__}")
        self.setMinimumSize(800, 600)

        # Get the primary screen object
        screen = QGuiApplication.primaryScreen()
        # Get the available geometry (excluding taskbars, etc.)
        available_geometry = screen.availableGeometry()
        self.resize(available_geometry.width(), available_geometry.height())

        self.session_manager: QtEphyrSessionManagerWrapper = session_manager
        self.global_storage_manager = global_storage_manager
        self._processed_channels_data_cache: Dict[int, np.ndarray[np.float64]] = {}
        self._filters_enabled_last = False

        # Menu bar and actions
        self.setup_ui()
        self.build_menus()
        self.connect_signals()

    def setup_ui(self):
        # Track widgets in right panel
        self.right_panel_widgets: List[RightPanelWidgetEnum] = []
        self.logs_panel = LogsPanel()
        self.info_panel = InformationPanel(self.session_manager)
        self.analysis_panel = AnalysisPanel(self.session_manager)
        self.signal_settings_panel = SignalSettingsPanel(self.session_manager)

        # Central contents
        central = QWidget(self)
        central_layout = QVBoxLayout()
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(8)
        central.setLayout(central_layout)
        self.setCentralWidget(central)

        # Header bar
        header = QWidget(self)
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(8, 8, 8, 0)
        header_layout.setSpacing(8)
        header.setLayout(header_layout)

        self.status_label = QLabel("")
        self.current_session_label = QLabel("No session loaded", header)
        self.current_session_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        self.btn_screenshot = QToolButton(header)
        # self.btn_screenshot.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))
        self.btn_screenshot.setText("Screenshot")

        self.btn_right_panel_toggle = QToolButton(header)
        # self.btn_right_panel_toggle.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TitleBarMinButton))
        self.btn_right_panel_toggle.setText("Panel")

        if settings.DEBUG:
            self.btn_debug = QToolButton(header)
            self.btn_debug.setText("Debug")
            header_layout.addWidget(self.btn_debug)

        header_layout.addWidget(self.btn_screenshot)
        header_layout.addWidget(self.btn_right_panel_toggle)
        header_layout.addWidget(self.current_session_label, 1)

        # Ensure header does not expand vertically
        header.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        header.setMaximumHeight(header.sizeHint().height())

        # Main horizontal splitter for left content and right panel
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal, self)

        # Left side: signal panel
        self.vertical_splitter = QSplitter(Qt.Orientation.Vertical, self)
        self.left_panel_stack = QStackedWidget(self.vertical_splitter)
        self.start_screen_panel = StartScreenPanel(self.left_panel_stack)
        self.signal_panel = SignalPanel(self.session_manager, self)
        self.left_panel_stack.addWidget(self.start_screen_panel)
        self.left_panel_stack.addWidget(self.signal_panel)
        self.vertical_splitter.addWidget(self.left_panel_stack)
        self.vertical_splitter.setChildrenCollapsible(False)
        self.vertical_splitter.setStretchFactor(0, 1)

        # Right panel - now with scroll area
        self.right_panel_scroll = QScrollArea(self)
        self.right_panel_scroll.setVisible(False)
        self.right_panel_scroll.setWidgetResizable(True)
        self.right_panel_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.right_panel_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        # Create the container widget for the scroll area
        self.right_panel_container = QWidget()
        self.right_panel_layout = QVBoxLayout(self.right_panel_container)
        self.right_panel_layout.setContentsMargins(5, 5, 5, 5)
        self.right_panel_layout.setSpacing(8)

        # GUI mode selector at the top of the right panel
        gui_mode_row = QWidget()
        gui_mode_layout = QHBoxLayout(gui_mode_row)
        gui_mode_layout.setContentsMargins(0, 0, 0, 0)
        gui_mode_layout.setSpacing(8)
        gui_mode_layout.addWidget(QLabel("GUI mode:"))
        self.gui_mode_combo = QComboBox()
        for mode in GuiMode:
            self.gui_mode_combo.addItem(mode.label, mode)
        current_mode = self.global_storage_manager.gui_mode
        self.gui_mode_combo.setCurrentIndex(self.gui_mode_combo.findData(current_mode))
        gui_mode_layout.addWidget(self.gui_mode_combo, 1)
        self.right_panel_layout.addWidget(gui_mode_row)
        self.signal_settings_panel.apply_gui_mode(current_mode)

        # Add a stretch to push widgets to the top when there's empty space
        self.right_panel_layout.addStretch(1)

        # Set the container as the scroll area's widget
        self.right_panel_scroll.setWidget(self.right_panel_container)

        # Style the scroll area frame
        self.right_panel_scroll.setFrameShape(QFrame.Shape.StyledPanel)
        self.right_panel_scroll.setStyleSheet("QFrame { border-left: 1px solid gray; }")

        # Add both to main splitter
        self.main_splitter.addWidget(self.vertical_splitter)
        self.main_splitter.addWidget(self.right_panel_scroll)

        # Set initial sizes: 80% for main content, 20% for right panel
        self.main_splitter.setSizes([800, 200])
        self.main_splitter.setStretchFactor(0, 4)  # Main content gets 4/5 of space
        self.main_splitter.setStretchFactor(1, 1)  # Right panel gets 1/5 of space

        # Assemble central layout
        central_layout.addWidget(header)
        central_layout.addWidget(self.main_splitter, 1)

        # Status bar
        status_bar = QStatusBar()
        self.setStatusBar(status_bar)
        status_bar.addWidget(self.status_label)
        self.__update_main_content_panel()

    def build_menus(self):
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("File")
        self.act_open = QAction("Open", self)
        file_menu.addAction(self.act_open)

        self.menu_open_recent = file_menu.addMenu("Open Recent")
        self.__update_recent_dirs()

        file_menu.addSection("Session")
        self.act_new_session = QAction("New", self)
        file_menu.addAction(self.act_new_session)
        self.act_save_session = QAction("Save", self)
        self.act_save_session.setShortcut("Ctrl+S")
        file_menu.addAction(self.act_save_session)
        self.menu_import = file_menu.addMenu("Import")
        self.act_import_session = QAction("session", self)
        self.act_import_events = QAction("events", self)
        self.act_import_periods = QAction("periods", self)
        self.act_import_settings = QAction("settings", self)
        self.menu_import.addAction(self.act_import_session)
        self.menu_import.addAction(self.act_import_events)
        self.menu_import.addAction(self.act_import_periods)
        self.menu_import.addAction(self.act_import_settings)
        self.act_export_session = QAction("Export", self)
        file_menu.addAction(self.act_export_session)
        self.act_open_session_in_explorer = QAction("Open in Explorer", self)
        file_menu.addAction(self.act_open_session_in_explorer)
        self.menu_sessions = file_menu.addMenu("Other Sessions")

        file_menu.addSeparator()
        self.act_exit = QAction("Exit", self)
        file_menu.addAction(self.act_exit)

        # Edit menu
        edit_menu = menubar.addMenu("Edit")
        self.undo_action = QAction("Undo", self)
        self.redo_action = QAction("Redo", self)
        edit_menu.addAction(self.undo_action)
        edit_menu.addAction(self.redo_action)

        # View menu (checkable)
        view_menu = menubar.addMenu("View")
        view_menu.addSection("Signal")
        self.view_traces = QAction("Traces", self, checkable=True, checked=True)
        self.view_events = QAction("Events", self, checkable=True, checked=False)
        self.view_periods = QAction("Periods", self, checkable=True, checked=False)
        for action in (
                self.view_traces,
                self.view_events,
                self.view_periods,
        ):
            view_menu.addAction(action)

        view_menu.addSection("Tools")
        self.view_signal_settings_panel = QAction("Electrophys trace settings", self, checkable=True, checked=False)
        self.view_info_panel = QAction("Information", self, checkable=True, checked=False)
        self.view_logs_panel = QAction("Logs", self, checkable=True, checked=False)
        self.view_analysis_panel = QAction("Add-ons", self, checkable=True, checked=False)
        for action in (
                self.view_signal_settings_panel,
                self.view_info_panel,
                self.view_logs_panel,
                self.view_analysis_panel,
        ):
            view_menu.addAction(action)

        # Events menu
        events_menu = menubar.addMenu("Events")
        self.events_show_all_action = QAction("Show table", self)
        self.events_add_action = QAction("Add", self)
        self.events_set_bad_event_action = QAction("Set bad event", self)
        self.events_unset_bad_event_action = QAction("Unset bad event", self)
        self.events_remove_action = QAction("Remove", self)
        events_menu.addAction(self.events_show_all_action)
        events_menu.addAction(self.events_add_action)
        events_menu.addAction(self.events_set_bad_event_action)
        events_menu.addAction(self.events_unset_bad_event_action)
        events_menu.addAction(self.events_remove_action)

        # Periods menu
        periods_menu = menubar.addMenu("Periods")
        self.periods_show_all_action = QAction("Show table", self)
        self.periods_add_action = QAction("Add period", self)
        periods_menu.addAction(self.periods_show_all_action)
        periods_menu.addAction(self.periods_add_action)

        # Add-ons
        add_ons_menu = menubar.addMenu("Add-ons")
        self.add_ons_manage = QAction("Manage", self)
        add_ons_menu.addAction(self.add_ons_manage)
        self.add_ons_create_template = QAction("Create", self)
        add_ons_menu.addAction(self.add_ons_create_template)
        self.add_ons_generate_script = QAction("Generate script", self)
        add_ons_menu.addAction(self.add_ons_generate_script)

        # Help
        help_menu = menubar.addMenu("Help")
        self.act_about = QAction("About", self)
        self.act_about.setMenuRole(QAction.MenuRole.NoRole)
        help_menu.addAction(self.act_about)
        self.act_hotkeys = QAction("Hotkeys", self)
        self.act_hotkeys.setMenuRole(QAction.MenuRole.NoRole)
        help_menu.addAction(self.act_hotkeys)

    def connect_signals(self):
        if settings.DEBUG:
            self.btn_debug.clicked.connect(self.on_debug)

        # Buttons
        self.btn_screenshot.clicked.connect(self.on_screenshot)
        self.btn_right_panel_toggle.clicked.connect(self.toggle_right_panel)
        self.gui_mode_combo.currentIndexChanged.connect(self.on_gui_mode_changed)
        self.start_screen_panel.open_requested.connect(self.on_open)

        # Menus
        self.act_open.triggered.connect(self.on_open)
        self.act_new_session.triggered.connect(self.on_new_session)
        self.act_save_session.triggered.connect(self.on_save_session)
        self.act_import_session.triggered.connect(self.on_import_session)
        self.act_import_events.triggered.connect(self.on_import_events)
        self.act_import_periods.triggered.connect(self.on_import_periods)
        self.act_import_settings.triggered.connect(self.on_import_settings)
        self.act_export_session.triggered.connect(self.on_export_session)
        self.act_open_session_in_explorer.triggered.connect(self.on_open_session_in_explorer)
        self.act_exit.triggered.connect(self.on_exit)
        self.undo_action.triggered.connect(self.on_undo)
        self.redo_action.triggered.connect(self.on_redo)
        self.view_traces.triggered.connect(self.on_view_traces)
        self.view_events.triggered.connect(self.on_view_events)
        self.view_periods.triggered.connect(self.on_view_periods)
        self.view_signal_settings_panel.triggered.connect(self.on_view_signal_settings_panel)
        self.view_info_panel.triggered.connect(self.on_view_info_panel)
        self.view_logs_panel.triggered.connect(self.on_view_logs_panel)
        self.view_analysis_panel.triggered.connect(self.on_view_analysis_panel)
        self.events_show_all_action.triggered.connect(self.on_show_events)
        self.events_add_action.triggered.connect(self.on_add_event)
        self.events_set_bad_event_action.triggered.connect(self.on_set_bad_event)
        self.events_unset_bad_event_action.triggered.connect(self.on_unset_bad_event)
        self.events_remove_action.triggered.connect(self.on_remove_event)
        self.periods_show_all_action.triggered.connect(self.on_show_periods)
        self.periods_add_action.triggered.connect(self.on_add_period)
        self.add_ons_manage.triggered.connect(self.on_add_ons_manage)
        self.add_ons_create_template.triggered.connect(self.on_add_ons_create_template)
        self.add_ons_generate_script.triggered.connect(self.on_add_ons_generate_script)
        self.act_about.triggered.connect(self.on_about)
        self.act_hotkeys.triggered.connect(self.on_hotkeys)

        # Different signal params changed
        self.session_manager.number_of_dots_to_display_changed.connect(self.on_number_of_dots_to_display_changed)
        self.session_manager.channels_groups_changed.connect(self.on_visible_channel_indexes_changed)
        self.session_manager.start_point_changed.connect(self.on_time_window_changed)
        self.session_manager.duration_ms_changed.connect(self.on_time_window_changed)
        self.session_manager.traces_are_shown_changed.connect(self.on_view_categories_changed)
        self.session_manager.events_are_shown_changed.connect(self.on_view_categories_changed)
        self.session_manager.periods_are_shown_changed.connect(self.on_view_categories_changed)
        self.session_manager.cut_traces_changed.connect(self.on_view_categories_changed)
        self.session_manager.channel_setup_changed.connect(self.on_channel_setup_changed)
        self.session_manager.header_units_changed.connect(self.on_header_units_changed)
        self.session_manager.current_sweep_idx_changed.connect(self.on_sweep_idx_changed)
        self.session_manager.add_ons_changed.connect(self.on_add_ons_changed)
        self.session_manager.add_ons_run.connect(self.on_add_ons_run)
        self.session_manager.filters_changed.connect(self.on_filters_changed)

        # Events changed
        self.session_manager.events_changed.connect(self.on_events_changed)
        self.session_manager.periods_changed.connect(self.on_periods_changed)

        # From panels
        self.signal_panel.channel_scroll_changed.connect(self.on_visible_channel_indexes_changed)

    # ---------- Callbacks session manager ----------
    def on_number_of_dots_to_display_changed(self):
        self.__recalculate_and_redraw_necessary_signals(recalculate_data=True, )

    def on_visible_channel_indexes_changed(self):
        self.__recalculate_and_redraw_necessary_signals(recalculate_data=True, )

    def on_view_categories_changed(self):
        self.__recalculate_and_redraw_necessary_signals(recalculate_data=False, )

    def on_channel_setup_changed(self):
        self.__recalculate_and_redraw_necessary_signals(recalculate_data=False)

    def on_header_units_changed(self, _units):
        self.__recalculate_and_redraw_necessary_signals(recalculate_data=True)

    def on_time_window_changed(self):
        self.__recalculate_and_redraw_necessary_signals(recalculate_data=True, )

    def on_filters_changed(self):
        if not self.session_manager.session_is_active:
            return
        gui_setup = self.session_manager.gui_setup
        if not gui_setup:
            return
        any_enabled = any(
            getattr(flt, "enabled", False)
            for group in (gui_setup.channels_groups or [])
            for flt in (group.filters or [])
        )
        if any_enabled or self._filters_enabled_last:
            self.__recalculate_and_redraw_necessary_signals(recalculate_data=True)
        self._filters_enabled_last = any_enabled

    def on_sweep_idx_changed(self):
        self.__recalculate_and_redraw_necessary_signals(recalculate_data=True, )

    def __recalculate_and_redraw_necessary_signals(self, recalculate_data: bool = True, ):
        group_layouts = self.signal_panel.get_visible_groups_layout()
        channel_indexes = []
        for group in group_layouts:
            channel_indexes.extend(group.visible_enabled_channels())
        if recalculate_data:
            self._processed_channels_data_cache = self.session_manager.experiment_data.process_data_pipeline(
                params=self.session_manager.gui_setup,
                sweep_idx=self.session_manager.gui_setup.current_sweep_idx,
                channel_indexes=channel_indexes,
                output_number_of_dots=self.session_manager.gui_setup.number_of_dots_to_display,
                transformation_add_ons=self.session_manager.get_transformation_add_ons(),
            )

        self.signal_panel.reset_data_and_redraw(
            self._processed_channels_data_cache,
            group_layouts=group_layouts,
            visible_channels=channel_indexes,
        )

    # ---------- Right Panel Management ----------
    def on_gui_mode_changed(self, index: int):
        mode = self.gui_mode_combo.itemData(index)
        if mode is None:
            return
        self.global_storage_manager.set_gui_mode(mode)
        self.signal_settings_panel.apply_gui_mode(mode)

    def toggle_right_panel(self):
        """Toggle the visibility of the right panel"""
        is_visible = self.right_panel_scroll.isVisible()
        self.right_panel_scroll.setVisible(not is_visible)

        # Adjust splitter sizes based on visibility
        if not is_visible:
            # Show right panel - set to 20% width
            total_width = self.main_splitter.width()
            main_width = int(total_width * 0.8)
            panel_width = int(total_width * 0.4)
            self.main_splitter.setSizes([main_width, panel_width])
        else:
            # Hide right panel - give all space to main content
            total_width = self.main_splitter.width()
            self.main_splitter.setSizes([total_width, 0])

    def add_widget_to_right_panel(self, widget_type: RightPanelWidgetEnum, update_session: bool = True):
        widget = self.__get_panel_by_type(widget_type)
        self.remove_widget_from_right_panel(widget_type)
        # self.right_panel_layout.insertWidget(self.right_panel_layout.count() - 1, widget)
        self.right_panel_layout.insertWidget(
            self.__get_right_panel_widget_position(widget_type, self.right_panel_widgets), widget)
        self.right_panel_widgets.append(widget_type)
        self.__set_panel_checked_by_type(widget_type, checked=True)

        if not self.right_panel_scroll.isVisible():
            self.toggle_right_panel()

        if update_session:
            self.session_manager.set_right_panel_widgets(self.right_panel_widgets)

    def remove_widget_from_right_panel(self, widget_type: RightPanelWidgetEnum, update_session: bool = True):
        """Remove a widget from the right panel"""
        if widget_type in self.right_panel_widgets:
            widget = self.__get_panel_by_type(widget_type)
            self.right_panel_layout.removeWidget(widget)
            widget.setParent(None)
            self.right_panel_widgets.remove(widget_type)
            self.__set_panel_checked_by_type(widget_type, checked=False)

        if not self.right_panel_widgets and self.right_panel_scroll.isVisible():
            self.toggle_right_panel()

        if update_session:
            self.session_manager.set_right_panel_widgets(self.right_panel_widgets)

    # ---------- Callbacks menu ----------
    def on_open(self):
        dialog = QFileDialog(self, "Select experiment folder or source file", "")
        dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptOpen)
        dialog.setFileMode(QFileDialog.FileMode.AnyFile)
        dialog.setFilter(QDir.Filter.AllEntries | QDir.Filter.NoDotAndDotDot)
        dialog.setNameFilter(
            "Supported source files "
            "(*.abf *.daq *.edf *.xdat *.xdat.json *.ncs *.nwb *.rhs *.rhd *.continuous *.dat settings.xml);;"
            "ABF files (*.abf);;DAQ files (*.daq);;EDF files (*.edf);;"
            "XDAT files (*.xdat *.xdat.json);;Neuralynx files (*.ncs *.nev);;NWB files (*.nwb);;"
            "Intan files (*.rhs *.rhd settings.xml);;"
            "Open Ephys files (*.continuous *.dat settings.xml);;All files (*)"
        )
        dialog.setOption(QFileDialog.Option.DontConfirmOverwrite, True)

        if not dialog.exec():
            return

        selected_paths = dialog.selectedFiles()
        if not selected_paths:
            return

        experiment_path = Path(selected_paths[0])
        if not experiment_path.exists():
            QMessageBox.warning(self, "Invalid path", f"Selected path does not exist: {experiment_path}")
            return

        self.__open_experiment_path(experiment_path)

    def __open_experiment_path(self, experiment_path: Path):
        # fixme: we assume for now that only one folder will be created
        is_ephyr, ephyr_experiment_folder_path = EphyrIO.ephyr_dir_of_experiment(experiment_path)
        if not is_ephyr and not EphyrIO.is_valid_ephyr_folder(ephyr_experiment_folder_path):
            try:
                source_reader = SourceReaderFactory.get_reader(experiment_path)
            except Exception as exc:
                QMessageBox.warning(self, "Unsupported source", str(exc))
                return

            converter_dialog = ConverterDialog(source_reader, ephyr_experiment_folder_path, self)
            if converter_dialog.exec():
                progress = QProgressDialog("Converting to ephyr data...", "Cancel", 0, 100, self)
                progress.setWindowModality(Qt.WindowModality.WindowModal)  # Block the entire app
                progress.setWindowTitle("Please Wait")
                progress.show()
                for convertion_progress_percents in EphyrIO.convert_from_source_to_ephyr(
                        experiment_path,
                        ephyr_experiment_folder_path,
                        reader_options=converter_dialog.conversion_options(),
                ):
                    if progress.wasCanceled():
                        shutil.rmtree(ephyr_experiment_folder_path)
                        return

                    progress.setValue(convertion_progress_percents)
            else:
                return

        self.__load_session(ephyr_experiment_folder_path)

    def on_open_recent_experiment(self, experiment_path: Path):
        try:
            self.__load_session(experiment_path)
        except FileNotFoundError:
            self.global_storage_manager.update_recent_experiments_list(experiment_path, to_delete=True)
            self.__update_recent_dirs()
            self.__set_status("Recent experiment folder does not exist")

    def on_open_another_session(self, session_filename: str):
        try:
            self.__switch_to_session(session_filename)
        except Exception as e:
            self.__set_status(repr(e))
        else:
            self.__set_status("Session was switched to " + self.session_manager.user_session.session_filename)

    def on_new_session(self):
        session_name = self.__new_unique_session_name()
        if session_name is None:
            return
        
        selected_session = UserSession.session_name_to_filename(session_name)
        self.session_manager.new_user_session(selected_session)
        self.__switch_to_session(selected_session)

    def on_save_session(self):
        if self.session_manager.session_is_active:
            self.session_manager.save_user_session()
            self.__set_status("Session was saved successfully")

    def on_import_session(self):
        if self.session_manager.session_is_active:
            file_to_import, _ = QFileDialog.getOpenFileName(self, "Select a session file")

            if file_to_import:
                session_to_import = EphyrSessionManager.parse_session_file(Path(file_to_import))
                if session_to_import is not None:
                    while self.session_manager.session_filename_already_exists(session_to_import.session_filename):
                        new_session_name = self.__new_unique_session_name()
                        if new_session_name is None:
                            return

                        session_to_import.change_name(new_session_name)

                    self.session_manager.import_new_session(session_to_import)
                    self.__update_sessions()
                    self.__set_status("Imported successfully as " + session_to_import.session_filename)
                else:
                    self.__set_status("Corrupted session file")
        else:
            self.__set_status("Warning: there is no active ephyr folder to import to")

    def on_import_events(self):
        if self.session_manager.session_is_active:
            file_to_import, _ = QFileDialog.getOpenFileName(
                self,
                "Select events source",
                "",
                "Session/Legacy events (*.json *.mat);;Session files (*.json);;MAT files (*.mat);;All files (*)",
            )

            if file_to_import:
                header = self.session_manager.header
                if header is None:
                    self.__set_status("Header is not loaded")
                    return

                file_path = Path(file_to_import)
                try:
                    if file_path.suffix.lower() == ".mat":
                        imported_vocabulary, imported_events, debug_info = import_legacy_events_from_mat(file_path, header)
                    else:
                        session_to_import = EphyrSessionManager.parse_session_file(file_path)
                        if session_to_import is None:
                            self.__set_status("Corrupted session file")
                            return
                        imported_vocabulary = session_to_import.events_vocabulary
                        imported_events = session_to_import.events
                        debug_info = {"source": "session_json"}
                except LegacyMatEventsImportError as e:
                    self.__set_status(f"Import error (.mat): {e}")
                    return
                except Exception as e:
                    self.__set_status(f"Import error: {e}")
                    return

                for imported_event in imported_events:
                    if imported_event.sweep_idx < 0 or imported_event.sweep_idx >= header.number_of_sweeps:
                        self.__set_status(
                            f"Import error: event sweep_idx={imported_event.sweep_idx} is out of range"
                        )
                        return
                    sweep_duration_ms = self.__sweep_duration_ms(header, imported_event.sweep_idx)
                    if imported_event.time_ms < 0 or imported_event.time_ms > sweep_duration_ms:
                        self.__set_status(
                            f"Import error: event time_ms={imported_event.time_ms:.3f} is out of sweep range"
                        )
                        return

                self.session_manager.import_vocabulary_and_events(
                    imported_vocabulary,
                    imported_events,
                )
                status_text = (
                    f"Imported events: {len(imported_events)}; "
                    f"vocabulary entries: {len(imported_vocabulary)}"
                )
                if file_path.suffix.lower() == ".mat":
                    status_text += (
                        f"; conversion={debug_info.get('time_conversion', 'n/a')}; "
                        f"skipped={debug_info.get('skipped_out_of_range', '0')}"
                    )
                self.__set_status(status_text)
        else:
            self.__set_status("Warning: there is no active ephyr folder to import to")

    def on_import_periods(self):
        if self.session_manager.session_is_active:
            file_to_import, _ = QFileDialog.getOpenFileName(self, "Select a session file")

            if file_to_import:
                session_to_import = EphyrSessionManager.parse_session_file(Path(file_to_import))
                if session_to_import is None:
                    self.__set_status("Corrupted session file")
                    return

                self.session_manager.import_vocabulary_and_periods(
                    session_to_import.periods_vocabulary,
                    session_to_import.periods,
                )
                self.__set_status(
                    f"Imported periods: {len(session_to_import.periods)}; "
                    f"vocabulary entries: {len(session_to_import.periods_vocabulary)}"
                )
        else:
            self.__set_status("Warning: there is no active ephyr folder to import to")
    
    def on_import_settings(self):
        if self.session_manager.session_is_active:
            file_to_import, _ = QFileDialog.getOpenFileName(self, "Select a session file")

            if file_to_import:
                session_to_import = EphyrSessionManager.parse_session_file(Path(file_to_import))
                if session_to_import is None:
                    self.__set_status("Corrupted session file")
                    return

                header = self.session_manager.header
                if header is None:
                    self.__set_status("Header is not loaded")
                    return

                imported_setup = session_to_import.gui_setup
                imported_setup.current_sweep_idx = 0
                imported_setup.start_point = 0
                # Keep imported duration, but clamp it to the current sweep length.
                # Forcing full-sweep duration makes the time scrollbar unusable (max=0).
                sweep_duration_ms = self.__sweep_duration_ms(header, imported_setup.current_sweep_idx)
                imported_setup.duration_ms = max(
                    settings.MIN_DURATION,
                    min(int(imported_setup.duration_ms), sweep_duration_ms),
                )

                self.session_manager.replace_gui_setup(imported_setup)
                self.__recalculate_and_redraw_necessary_signals(recalculate_data=True)
                self.__set_status("Imported GUI settings successfully")
        else:
            self.__set_status("Warning: there is no active ephyr folder to import to")


    def on_export_session(self):
        destination_dir = QFileDialog.getExistingDirectory(
            self, "Select a destination directory", "",
            options=QFileDialog.Option.ShowDirsOnly)

        if destination_dir:
            destination_path = Path(destination_dir)
            export_name = self.session_manager.export_current_session(destination_path)
            self.__set_status("Session was exported successfully to \"" + export_name + "\"")

    def on_open_session_in_explorer(self):
        if self.session_manager.session_is_active:
            if os.name == 'nt':  # Windows
                subprocess.run(['explorer', self.session_manager.ephyr_experiment_folder])
            elif os.name == 'posix':  # macOS or Linux
                subprocess.run(['open', self.session_manager.ephyr_experiment_folder])  # For macOS
                # For Linux, you might need 'xdg-open' or a specific file manager command
                # subprocess.run(['xdg-open', folder_path])
        else:
            self.__set_status("Warning: ephyr session is not active")

    def closeEvent(self, event):
        if (self.session_manager.session_is_active
                and self.session_manager.user_session
                and not self.session_manager.user_session.changes_saved):
            result = QMessageBox.warning(
                self,
                "Session not saved",
                "Some changes in the session was not saved. Are you sure you want to exit?",
                QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel
            )
            if result == QMessageBox.StandardButton.Cancel:
                event.ignore()
            else:
                event.accept()

    def on_exit(self):
        if (self.session_manager.session_is_active
                and self.session_manager.user_session
                and not self.session_manager.user_session.changes_saved):
            result = QMessageBox.warning(
                self,
                "Session not saved",
                "Some changes in the session was not saved. Are you sure you want to exit?",
                QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel
            )
            if result == QMessageBox.StandardButton.Cancel:
                return

        QApplication.instance().quit()

    def on_undo(self):
        message = self.session_manager.undo()
        if message:
            self.__set_status(message)

    def on_redo(self):
        message = self.session_manager.redo()
        if message:
            self.__set_status(message)

    def on_view_traces(self, checked: bool, *args, **kwargs):
        if self.session_manager.session_is_active:
            self.session_manager.set_traces_shown(checked)

    def on_view_events(self, checked: bool, *args, **kwargs):
        if self.session_manager.session_is_active:
            self.session_manager.set_events_shown(checked)

    def on_view_periods(self, checked: bool, *args, **kwargs):
        if self.session_manager.session_is_active:
            self.session_manager.set_periods_shown(checked)

    def on_view_signal_settings_panel(self, checked: bool, *args, **kwargs):
        if checked:
            self.add_widget_to_right_panel(RightPanelWidgetEnum.SIGNAL_SETTINGS)
        else:
            self.remove_widget_from_right_panel(RightPanelWidgetEnum.SIGNAL_SETTINGS)

    def on_view_info_panel(self, checked: bool, *args, **kwargs):
        if checked:
            self.add_widget_to_right_panel(RightPanelWidgetEnum.INFORMATION)
        else:
            self.remove_widget_from_right_panel(RightPanelWidgetEnum.INFORMATION)

    def on_view_logs_panel(self, checked: bool, *args, **kwargs):
        if checked:
            self.add_widget_to_right_panel(RightPanelWidgetEnum.LOGS)
        else:
            self.remove_widget_from_right_panel(RightPanelWidgetEnum.LOGS)

    def on_view_analysis_panel(self, checked: bool, *args, **kwargs):
        if checked:
            self.add_widget_to_right_panel(RightPanelWidgetEnum.ANALYSIS)
        else:
            self.remove_widget_from_right_panel(RightPanelWidgetEnum.ANALYSIS)

    def on_filter_highpass(self, checked: bool, *args, **kwargs):
        pass

    def on_filter_lowpass(self, checked: bool, *args, **kwargs):
        pass

    def on_filter_bandpass(self, checked: bool, *args, **kwargs):
        pass

    def on_events_changed(self, *args, **kwargs):
        """Redraw EEG panel when events list changes."""
        self.__recalculate_and_redraw_necessary_signals(recalculate_data=False)

    def on_periods_changed(self, *args, **kwargs):
        """Redraw EEG panel when periods list changes."""
        self.__recalculate_and_redraw_necessary_signals(recalculate_data=False)

    def on_add_ons_changed(self, *args, **kwargs):
        self.__recalculate_and_redraw_necessary_signals(recalculate_data=True)

    def on_add_ons_run(self, *_args, **_kwargs):
        self.__recalculate_and_redraw_necessary_signals(recalculate_data=True)

    def on_show_events(self):
        if not self.session_manager.session_is_active:
            self.__set_status("Warning: ephyr session is not active")
            return

        EventsVocabularyDialog(self.session_manager, self).exec()

    def on_add_event(self):
        if not self.session_manager.session_is_active:
            self.__set_status("Warning: ephyr session is not active")
            return

        dialog = EventsVocabularyDialog(self.session_manager, self)
        if dialog.exec():
            selected_id = dialog.get_selected_event_vocabulary_id()
            if selected_id is None:
                return

            # Enter interactive event placement mode on EEG panel
            self.signal_panel.start_event_add_mode(selected_id)

    def on_set_bad_event(self):
        if not self.session_manager.session_is_active:
            self.__set_status("Warning: ephyr session is not active")
            return

        if not self.session_manager.events:
            self.__set_status("Warning: there are no events in the current session")
            return

        self.signal_panel.start_set_bad_event_mode()
        self.__set_status("Select two points on EEG panel to mark events as bad (right click to cancel)")

    def on_unset_bad_event(self):
        if not self.session_manager.session_is_active:
            self.__set_status("Warning: ephyr session is not active")
            return

        if not self.session_manager.events:
            self.__set_status("Warning: there are no events in the current session")
            return

        self.signal_panel.start_unset_bad_event_mode()
        self.__set_status("Select two points on EEG panel to unset bad flag for events (right click to cancel)")

    def on_remove_event(self):
        if not self.session_manager.session_is_active:
            self.__set_status("Warning: ephyr session is not active")
            return

        if not self.session_manager.events:
            self.__set_status("Warning: there are no events in the current session")
            return

        self.signal_panel.start_event_remove_mode()
        self.__set_status("Select two points on EEG panel to remove events (right click to cancel)")

    def on_show_periods(self):
        if not self.session_manager.session_is_active:
            self.__set_status("Warning: ephyr session is not active")
            return

        PeriodsVocabularyDialog(self.session_manager, self).exec()

    def on_add_period(self):
        if not self.session_manager.session_is_active:
            self.__set_status("Warning: ephyr session is not active")
            return

        dialog = PeriodsVocabularyDialog(self.session_manager, self)
        if dialog.exec():
            selected_id = dialog.get_selected_period_vocabulary_id()
            if selected_id is None:
                return

            # Enter interactive period placement mode on EEG panel
            self.signal_panel.start_period_add_mode(selected_id)
            self.__set_status("Select two points on EEG panel to add period (right click to cancel)")

    def on_add_ons_manage(self):
        if not self.session_manager.session_is_active:
            self.__set_status("Warning: ephyr session is not active")
            return

        AddOnsDialog(self.session_manager, self).exec()

    def on_add_ons_create_template(self):
        AddOnDevelopmentDialog(self).exec()

    def on_add_ons_generate_script(self):
        ScriptTemplateGeneratorDialog(self.session_manager, self).exec()

    def on_about(self):
        AboutDialog(self).exec()

    def on_hotkeys(self):
        HotkeysDialog(self).exec()

    def on_debug(self):
        capture_widget_to_file(self, self, "main_window_full")
        capture_widget_to_file(self, self.right_panel_container, "right_panel")
        self.__set_status("DEBUG DONE")

    def on_screenshot(self):
        if not self.session_manager.session_is_active or not self.session_manager.gui_setup:
            self.__set_status("Warning: ephyr session is not active")
            return

        panel = self.signal_panel
        signal_widget = panel.signal_widget
        top_navigator_widget = panel.top_navigator_widget
        if signal_widget.width() <= 0 or signal_widget.height() <= 0:
            self.__set_status("Warning: signal widget is empty")
            return

        signal_top_left_in_panel = signal_widget.mapTo(panel, signal_widget.rect().topLeft())
        top_source_rect = QRect(
            signal_top_left_in_panel.x(),
            0,
            signal_widget.width(),
            top_navigator_widget.height(),
        )
        gui_setup = self.session_manager.gui_setup
        context = ScreenshotRenderContext(
            signal_widget=signal_widget,
            top_navigator_widget=top_navigator_widget,
            top_source_rect=top_source_rect,
            current_sweep_idx=gui_setup.current_sweep_idx,
            start_point=gui_setup.start_point,
            duration_ms=gui_setup.duration_ms,
            groups_layout=self.signal_panel.get_visible_groups_layout(),
            channels_setup=gui_setup.channels_setup,
        )
        result = ScreenshotExportDialog.run_export(self, context)
        self.__set_status(result.message)

    def __load_session(self, ephyr_experiment_folder_path: Path):
        self.session_manager.init_from_folder(ephyr_experiment_folder_path)
        sessions = self.session_manager.other_session_filenames
        selected_session = None
        if len(sessions) == 1:
            selected_session = sessions[0]
        elif len(sessions) > 1:
            selected_session = SelectSessionDialog(sessions).get_selected_item()

        if selected_session is None:
            session_name = self.__new_unique_session_name()
            if session_name is None:
                return
            
            selected_session = UserSession.session_name_to_filename(session_name)
            self.session_manager.new_user_session(selected_session)

        self.__switch_to_session(selected_session)
        self.global_storage_manager.update_recent_experiments_list(ephyr_experiment_folder_path)
        self.__set_status("Session is loaded successfully")

    def __switch_to_session(self, selected_session):
        self.session_manager.switch_sessions(selected_session)
        self.__update_main_content_panel()
        self.__recalculate_and_redraw_necessary_signals(recalculate_data=True, )
        self.__update_recent_dirs()
        self.__update_sessions()
        self.__update_menu()
        self.__redraw_header()

        if self.session_manager.user_session.gui_setup.right_panel_widgets:
            for cur_right_panel_widget in copy(self.right_panel_widgets):
                self.remove_widget_from_right_panel(cur_right_panel_widget, update_session=False)
            for right_panel_widget in self.session_manager.user_session.gui_setup.right_panel_widgets:
                self.add_widget_to_right_panel(right_panel_widget, update_session=False)


    def __update_recent_dirs(self):
        self.menu_open_recent.clear()
        for recent in self.global_storage_manager.recent_experiments:
            act_open_recent = QAction(str(recent), self)
            act_open_recent.triggered.connect(partial(self.on_open_recent_experiment, recent))
            self.menu_open_recent.addAction(act_open_recent)

    def __update_sessions(self):
        self.menu_sessions.clear()
        for session_filename in self.session_manager.other_session_filenames:
            act_open_session = QAction(session_filename, self)
            act_open_session.triggered.connect(partial(self.on_open_another_session, session_filename))
            self.menu_sessions.addAction(act_open_session)

    def __update_menu(self):
        self.view_traces.setChecked(self.session_manager.gui_setup.traces_are_shown)
        self.view_events.setChecked(self.session_manager.gui_setup.events_are_shown)
        self.view_periods.setChecked(self.session_manager.gui_setup.periods_are_shown)

    def __redraw_header(self):
        session_filename = self.session_manager.ephyr_experiment_folder.name
        if self.session_manager.user_session is not None:
            session_filename += ":" + self.session_manager.user_session.session_filename
        self.current_session_label.setText(session_filename)

    @staticmethod
    def __sweep_points(header, sweep_idx: int) -> int:
        points = list(header.number_of_points_per_sweep)
        sweep_idx = max(0, min(int(sweep_idx), len(points) - 1))
        return int(points[sweep_idx])

    @staticmethod
    def __sweep_duration_ms(header, sweep_idx: int) -> int:
        return int((header.sample_interval_microseconds / 10 ** 3) * MainWindow.__sweep_points(header, sweep_idx))

    def __set_status(self, text: str):
        current_time = datetime.now()
        formatted_time = current_time.strftime("%H:%M:%S")
        self.status_label.setText(f"{formatted_time} " + text)
        ephyr_logger().info(text)

    def __update_main_content_panel(self):
        if self.session_manager.session_is_active:
            self.left_panel_stack.setCurrentWidget(self.signal_panel)
        else:
            self.left_panel_stack.setCurrentWidget(self.start_screen_panel)

    def __new_unique_session_name(self) -> Optional[str]:
        is_created = False
        while not is_created:
            dialog = SessionNameDialog(self)
            if dialog.exec():
                session_name = dialog.line_edit.text()
                if self.session_manager.session_name_already_exists(session_name):
                    QMessageBox.warning(self, "Warning",
                                        f"Session with the name {session_name} already exists.")
                else:
                    return session_name
            else:
                return None

    def __get_panel_by_type(self, widget_type: RightPanelWidgetEnum):
        if widget_type == RightPanelWidgetEnum.SIGNAL_SETTINGS:
            return self.signal_settings_panel
        elif widget_type == RightPanelWidgetEnum.LOGS:
            return self.logs_panel
        elif widget_type == RightPanelWidgetEnum.INFORMATION:
            return self.info_panel
        elif widget_type == RightPanelWidgetEnum.ANALYSIS:
            return self.analysis_panel
        else:
            raise ValueError("Unknown widget_type")

    def __set_panel_checked_by_type(self, widget_type: RightPanelWidgetEnum, checked: bool):
        if widget_type == RightPanelWidgetEnum.SIGNAL_SETTINGS:
            self.view_signal_settings_panel.setChecked(checked)
        elif widget_type == RightPanelWidgetEnum.LOGS:
            self.view_logs_panel.setChecked(checked)
        elif widget_type == RightPanelWidgetEnum.INFORMATION:
            self.view_info_panel.setChecked(checked)
        elif widget_type == RightPanelWidgetEnum.ANALYSIS:
            self.view_analysis_panel.setChecked(checked)
        else:
            raise ValueError("Unknown widget_type")

    def __get_right_panel_widget_position(self, widget_type: RightPanelWidgetEnum, right_panel_widgets: List[RightPanelWidgetEnum]):
        # Index 0 is reserved for the GUI mode selector at the top of the right panel.
        idx = 1
        for widget in RightPanelWidgetEnum.widgets_order():
            if widget == widget_type:
                return idx
            elif widget in right_panel_widgets:
                idx += 1
