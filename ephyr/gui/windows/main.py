# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import gc
import os
import subprocess
from copy import copy
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from enum import Enum

import numpy as np
from PyQt6.QtCore import Qt, QRect, QUrl
from PyQt6.QtGui import QAction, QDesktopServices, QGuiApplication
from PyQt6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QSplitter,
    QFileDialog,
    QApplication, QStatusBar, QSizePolicy, QMessageBox,
    QFrame, QScrollArea, QStackedWidget, QStyle,
)

from ephyr import settings
from ephyr import version
from ephyr.gui.mixins.qwidget_mixin import QWidgetMixin
from ephyr.gui._utils import capture_widget_to_file
from ephyr.gui.widgets import FocusWheelComboBox as QComboBox
from ephyr.core import layout
from ephyr.core.ephyr_session import RightPanelWidgetEnum, UserSession, is_valid_session_name
from ephyr.core.global_storage import GlobalStorageManager, GuiMode
from ephyr.core.workspace import Workspace, WorkspaceError, find_workspace_root
from ephyr.converter.legacy_mat_events import (
    LegacyMatEventsImportError,
    import_legacy_events_from_mat,
)
from ephyr.gui.dialogs.converter_dialog import CreateWorkspaceDialog, ImportSettingsDialog
from ephyr.gui.workspace_actions import WorkspaceActions, records_with_sessions
from ephyr.gui.dialogs.session_name_dialog import SessionNameDialog
from ephyr.gui.dialogs.select_session_dialog import SelectSessionDialog
from ephyr.gui.dialogs.events_vocabulary_dialog import EventsVocabularyDialog
from ephyr.gui.dialogs.periods_vocabulary_dialog import PeriodsVocabularyDialog
from ephyr.gui.dialogs.add_ons_dialog import AddOnsDialog
from ephyr.gui.dialogs.add_on_development_dialog import AddOnDevelopmentDialog
from ephyr.gui.dialogs.screenshot_export_dialog import ScreenshotExportDialog, ScreenshotRenderContext
from ephyr.gui.dialogs.about_dialog import AboutDialog
from ephyr.gui.dialogs.hotkeys_dialog import HotkeysDialog
from ephyr.gui.panels.information_panel import InformationPanel
from ephyr.gui.panels.analysis_panel import AnalysisPanel
from ephyr.gui.panels.logs_panel import LogsPanel
from ephyr.gui.panels.channel_management_panel import ChannelManagementPanel
from ephyr.gui.panels.recording_navigation_panel import RecordingNavigationPanel, WorkspaceLevelEnum
from ephyr.gui.panels.time_settings_panel import TimeSettingsPanel
from ephyr.gui.panels.signal_panel import SignalPanel
from ephyr.gui.panels.start_screen_panel import StartScreenPanel, StartScreenStateEnum
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
        self.workspace_actions = WorkspaceActions(self, global_storage_manager)
        self._workspace: Optional[Workspace] = None
        # Config chosen in the navigation panel; it can have no open Record.
        self._config_id: Optional[str] = None
        self._processed_channels_data_cache: Dict[int, np.ndarray[np.float64]] = {}
        self._overlay_channels_data_cache: Dict[int, Dict[int, np.ndarray[np.float64]]] = {}
        self._overlay_cache_segment_idxs: Tuple[int, ...] = ()
        self._overlay_data_version = 0
        self._filters_enabled_last = False

        self.setAcceptDrops(True)

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
        self.recording_navigation_panel = RecordingNavigationPanel(self.session_manager)
        self.time_settings_panel = TimeSettingsPanel(self.session_manager)
        self.channel_management_panel = ChannelManagementPanel(self.session_manager)

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
        self.current_session_label = QLabel("No session loaded")
        self.current_session_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        self.btn_scalebar = QToolButton(header)
        self.btn_scalebar.setText("Scalebar")
        self.btn_scalebar.setCheckable(True)

        self.btn_zoom_to_area = QToolButton(header)
        self.btn_zoom_to_area.setText("Zoom to area")
        self.btn_zoom_to_area.setCheckable(True)

        self.btn_screenshot = QToolButton(header)
        self.btn_screenshot.setText("Export canvas")

        self.btn_right_panel_toggle = QToolButton(header)
        self.btn_right_panel_toggle.setText("Show session panel")

        if settings.DEBUG:
            self.btn_debug = QToolButton(header)
            self.btn_debug.setText("Debug")
            header_layout.addWidget(self.btn_debug)

        header_layout.addWidget(self.btn_scalebar)
        header_layout.addWidget(self.btn_zoom_to_area)
        header_layout.addWidget(self.btn_screenshot)
        header_layout.addWidget(self.btn_right_panel_toggle)
        header_layout.addStretch(1)

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

        # Session panel selector (Beginner / Expert) at the top of the right panel
        gui_mode_row = QWidget()
        gui_mode_layout = QHBoxLayout(gui_mode_row)
        gui_mode_layout.setContentsMargins(0, 0, 0, 0)
        gui_mode_layout.setSpacing(8)
        gui_mode_layout.addWidget(QLabel("Session panel:"))
        self.gui_mode_combo = QComboBox()
        for mode in GuiMode:
            self.gui_mode_combo.addItem(mode.label, mode)
        current_mode = self.global_storage_manager.gui_mode
        self.gui_mode_combo.setCurrentIndex(self.gui_mode_combo.findData(current_mode))
        gui_mode_layout.addWidget(self.gui_mode_combo, 1)
        self.right_panel_layout.addWidget(gui_mode_row)
        self.time_settings_panel.apply_gui_mode(current_mode)
        self.channel_management_panel.apply_gui_mode(current_mode)
        self.info_panel.apply_gui_mode(current_mode)

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
        status_bar.addWidget(self.status_label, 1)
        status_bar.addPermanentWidget(self.current_session_label)
        self.__update_main_content_panel()

    def build_menus(self):
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("File")
        self._add_labeled_menu_section(file_menu, "Workspace")
        self.act_create_workspace = QAction("Create Ephyr Workspace…", self)
        file_menu.addAction(self.act_create_workspace)
        self.menu_open_workspace = file_menu.addMenu("Open Ephyr Workspace")
        self.act_open_workspace_file = QAction("Open File (workspace.ephyr)…", self)
        self.act_open_workspace_folder = QAction("Open Folder…", self)
        self.menu_open_workspace.addAction(self.act_open_workspace_file)
        self.menu_open_workspace.addAction(self.act_open_workspace_folder)
        self.menu_open_recent = file_menu.addMenu("Recent Workspaces")
        self.__update_recent_dirs()
        self.act_add_config = QAction("Add Config…", self)
        self.act_add_record = QAction("Add Record…", self)
        self.act_add_source = QAction("Add Source…", self)
        file_menu.addAction(self.act_add_config)
        file_menu.addAction(self.act_add_record)
        file_menu.addAction(self.act_add_source)

        self._add_labeled_menu_section(file_menu, "Session")
        self.act_new_session = QAction("New", self)
        file_menu.addAction(self.act_new_session)
        self.act_save_session = QAction("Save", self)
        self.act_save_session.setShortcut("Ctrl+S")
        file_menu.addAction(self.act_save_session)
        self.menu_import = file_menu.addMenu("Import")
        self.act_import_session = QAction("Full Session", self)
        self.act_import_events = QAction("Events", self)
        self.act_import_periods = QAction("Periods", self)
        self.act_import_settings = QAction("Settings from Record…", self)
        self.menu_import.addAction(self.act_import_session)
        self.menu_import.addSeparator()
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
        self.act_copy_image = QAction("Export Canvas", self)
        edit_menu.addAction(self.act_copy_image)
        edit_menu.addSeparator()
        self.undo_action = QAction("Undo", self)
        self.redo_action = QAction("Redo", self)
        edit_menu.addAction(self.undo_action)
        edit_menu.addAction(self.redo_action)

        # View menu (checkable)
        view_menu = menubar.addMenu("View")
        self._add_labeled_menu_section(view_menu, "Data Panel")
        self.view_traces = QAction("Channel Traces", self, checkable=True, checked=True)
        self.view_channel_names = QAction("Channel Names", self, checkable=True, checked=True)
        self.view_channel_info = QAction("Channel Info", self, checkable=True, checked=True)
        self.view_events = QAction("Events", self, checkable=True, checked=False)
        self.view_periods = QAction("Periods", self, checkable=True, checked=False)
        for action in (
                self.view_traces,
                self.view_channel_names,
                self.view_channel_info,
                self.view_events,
                self.view_periods,
        ):
            view_menu.addAction(action)

        self._add_labeled_menu_section(view_menu, "Session Panel")
        self.view_recording_navigation_panel = QAction("Recording Navigation", self, checkable=True, checked=False)
        self.view_time_settings_panel = QAction("Timeline Settings", self, checkable=True, checked=False)
        self.view_channel_management_panel = QAction("Channel Management", self, checkable=True, checked=False)
        self.view_info_panel = QAction("Recording Description", self, checkable=True, checked=False)
        self.view_logs_panel = QAction("Application Logs", self, checkable=True, checked=False)
        self.view_analysis_panel = QAction("Add-ons", self, checkable=True, checked=False)
        for action in (
                self.view_recording_navigation_panel,
                self.view_time_settings_panel,
                self.view_channel_management_panel,
                self.view_analysis_panel,
                self.view_info_panel,
                self.view_logs_panel,
        ):
            view_menu.addAction(action)

        # Events menu
        events_menu = menubar.addMenu("Events")
        self.events_show_all_action = QAction("Manage", self)
        self.events_remove_action = QAction("Remove in Range", self)
        self.events_set_bad_event_action = QAction("Mark as Invalid", self)
        self.events_unset_bad_event_action = QAction("Remove Invalid Mark", self)
        events_menu.addAction(self.events_show_all_action)
        events_menu.addAction(self.events_remove_action)
        events_menu.addAction(self.events_set_bad_event_action)
        events_menu.addAction(self.events_unset_bad_event_action)

        # Periods menu
        periods_menu = menubar.addMenu("Periods")
        self.periods_show_all_action = QAction("Manage", self)
        periods_menu.addAction(self.periods_show_all_action)

        # Add-ons
        add_ons_menu = menubar.addMenu("Add-ons")
        self.add_ons_manage = QAction("Manage", self)
        add_ons_menu.addAction(self.add_ons_manage)
        self.add_ons_create_template = QAction("Create", self)
        add_ons_menu.addAction(self.add_ons_create_template)

        # Help
        help_menu = menubar.addMenu("Help")
        self.act_ephyr_guide = QAction("Guide", self)
        self.act_ephyr_guide.setMenuRole(QAction.MenuRole.NoRole)
        help_menu.addAction(self.act_ephyr_guide)
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
        self.btn_scalebar.clicked.connect(self.on_scalebar)
        self.btn_zoom_to_area.clicked.connect(self.on_zoom_to_area)
        self.btn_screenshot.clicked.connect(self.on_screenshot)
        self.btn_right_panel_toggle.clicked.connect(self.toggle_right_panel)
        self.gui_mode_combo.currentIndexChanged.connect(self.on_gui_mode_changed)
        self.start_screen_panel.create_workspace_requested.connect(self.on_create_workspace)
        self.start_screen_panel.open_workspace_file_requested.connect(self.on_open_workspace_file)
        self.start_screen_panel.open_workspace_folder_requested.connect(self.on_open_workspace_folder)
        self.start_screen_panel.recent_workspace_requested.connect(self.on_open_recent_workspace)
        self.start_screen_panel.add_config_requested.connect(lambda: self.on_add_requested(WorkspaceLevelEnum.CONFIG))
        self.start_screen_panel.add_record_requested.connect(lambda: self.on_add_requested(WorkspaceLevelEnum.RECORD))
        self.recording_navigation_panel.config_selected.connect(self.on_config_selected)
        self.recording_navigation_panel.record_selected.connect(self.on_record_selected)
        self.recording_navigation_panel.add_requested.connect(self.on_add_requested)
        self.recording_navigation_panel.remove_requested.connect(self.on_remove_requested)
        self.recording_navigation_panel.rename_requested.connect(self.on_rename_requested)
        self.signal_panel.interaction_modes_changed.connect(self._sync_toolbar_modes)

        # Menus
        self.act_create_workspace.triggered.connect(self.on_create_workspace)
        self.act_open_workspace_file.triggered.connect(self.on_open_workspace_file)
        self.act_open_workspace_folder.triggered.connect(self.on_open_workspace_folder)
        self.act_add_config.triggered.connect(lambda: self.on_add_requested(WorkspaceLevelEnum.CONFIG))
        self.act_add_record.triggered.connect(lambda: self.on_add_requested(WorkspaceLevelEnum.RECORD))
        self.act_add_source.triggered.connect(lambda: self.on_add_requested(WorkspaceLevelEnum.SOURCE))
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
        self.act_copy_image.triggered.connect(self.on_screenshot)
        self.view_traces.triggered.connect(self.on_view_traces)
        self.view_channel_names.triggered.connect(self.on_view_channel_names)
        self.view_channel_info.triggered.connect(self.on_view_channel_info)
        self.view_events.triggered.connect(self.on_view_events)
        self.view_periods.triggered.connect(self.on_view_periods)
        self.view_recording_navigation_panel.triggered.connect(self.on_view_recording_navigation_panel)
        self.view_time_settings_panel.triggered.connect(self.on_view_time_settings_panel)
        self.view_channel_management_panel.triggered.connect(self.on_view_channel_management_panel)
        self.view_info_panel.triggered.connect(self.on_view_info_panel)
        self.view_logs_panel.triggered.connect(self.on_view_logs_panel)
        self.view_analysis_panel.triggered.connect(self.on_view_analysis_panel)
        self.events_show_all_action.triggered.connect(self.on_show_events)
        self.events_set_bad_event_action.triggered.connect(self.on_set_bad_event)
        self.events_unset_bad_event_action.triggered.connect(self.on_unset_bad_event)
        self.events_remove_action.triggered.connect(self.on_remove_event)
        self.periods_show_all_action.triggered.connect(self.on_show_periods)
        self.add_ons_manage.triggered.connect(self.on_add_ons_manage)
        self.add_ons_create_template.triggered.connect(self.on_add_ons_create_template)
        self.act_ephyr_guide.triggered.connect(self.on_ephyr_guide)
        self.act_about.triggered.connect(self.on_about)
        self.act_hotkeys.triggered.connect(self.on_hotkeys)

        # Different signal params changed
        self.session_manager.number_of_dots_to_display_changed.connect(self.on_number_of_dots_to_display_changed)
        self.session_manager.channels_groups_changed.connect(self.on_visible_channel_indexes_changed)
        self.session_manager.start_point_changed.connect(self.on_time_window_changed)
        self.session_manager.duration_ms_changed.connect(self.on_time_window_changed)
        self.session_manager.traces_are_shown_changed.connect(self.on_view_categories_changed)
        self.session_manager.channel_names_are_shown_changed.connect(self.on_view_categories_changed)
        self.session_manager.channel_infos_are_shown_changed.connect(self.on_view_categories_changed)
        self.session_manager.events_are_shown_changed.connect(self.on_view_categories_changed)
        self.session_manager.periods_are_shown_changed.connect(self.on_view_categories_changed)
        self.session_manager.cut_traces_changed.connect(self.on_view_categories_changed)
        self.session_manager.channel_setup_changed.connect(self.on_channel_setup_changed)
        self.session_manager.channel_units_changed.connect(self.on_channel_units_changed)
        self.session_manager.current_segment_idx_changed.connect(self.on_segment_idx_changed)
        self.session_manager.overlay_segment_idxs_changed.connect(self.on_overlay_segment_idxs_changed)
        self.session_manager.display_segments_changed.connect(self.on_overlay_segment_idxs_changed)
        self.session_manager.active_source_changed.connect(self.on_active_source_changed)
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

    def on_channel_units_changed(self, _units):
        self.__recalculate_and_redraw_necessary_signals(recalculate_data=False)

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

    def on_segment_idx_changed(self):
        # The gray overlay covers every selected segment for the current window, so switching
        # the current segment only needs the black trace on top of the cached gray layer.
        self.__recalculate_and_redraw_necessary_signals(recalculate_data=True, recalculate_overlay=False)

    def on_overlay_segment_idxs_changed(self, *_args):
        self.__recalculate_and_redraw_necessary_signals(recalculate_data=True, )

    def on_active_source_changed(self, _source_id: str):
        self._processed_channels_data_cache = {}
        self._overlay_channels_data_cache = {}
        self._overlay_cache_segment_idxs = ()
        self._restore_right_panel_widgets()
        self.__recalculate_and_redraw_necessary_signals(recalculate_data=True)
        self.__redraw_header()

    def __recalculate_and_redraw_necessary_signals(self, recalculate_data: bool = True,
                                                   recalculate_overlay: bool = True, ):
        group_layouts = self.signal_panel.get_visible_groups_layout()
        channel_indexes = []
        for group in group_layouts:
            channel_indexes.extend(group.visible_enabled_channels())
        if not self.session_manager.session_is_active or self.session_manager.record_data is None:
            return
        if recalculate_data:
            gui_setup = self.session_manager.gui_setup
            overlay_segment_idxs = tuple(gui_setup.overlay_segment_idxs)
            if recalculate_overlay or overlay_segment_idxs != self._overlay_cache_segment_idxs:
                self._overlay_channels_data_cache = \
                    self.session_manager.record_data.process_data_pipeline_multi_segment(
                        params=gui_setup,
                        segment_indexes=list(overlay_segment_idxs),
                        channel_indexes=channel_indexes,
                        output_number_of_dots=gui_setup.number_of_dots_to_display,
                        transformation_add_ons=self.session_manager.get_transformation_add_ons(),
                    )
                self._overlay_cache_segment_idxs = overlay_segment_idxs
                self._overlay_data_version += 1

            # An overlaid current segment is already processed, so only reprocess it when it is not.
            current_segment_data = self._overlay_channels_data_cache.get(gui_setup.current_segment_idx)
            if current_segment_data is None:
                current_segment_data = self.session_manager.record_data.process_data_pipeline(
                    params=gui_setup,
                    segment_idx=gui_setup.current_segment_idx,
                    channel_indexes=channel_indexes,
                    output_number_of_dots=gui_setup.number_of_dots_to_display,
                    transformation_add_ons=self.session_manager.get_transformation_add_ons(),
                )
            self._processed_channels_data_cache = current_segment_data

        self.signal_panel.reset_data_and_redraw(
            self._processed_channels_data_cache,
            group_layouts=group_layouts,
            visible_channels=channel_indexes,
            overlay_processed_data=self._overlay_channels_data_cache,
            overlay_data_version=self._overlay_data_version,
        )

    # ---------- Right Panel Management ----------
    def on_gui_mode_changed(self, index: int):
        mode = self.gui_mode_combo.itemData(index)
        if mode is None:
            return
        self.global_storage_manager.set_gui_mode(mode)
        self.time_settings_panel.apply_gui_mode(mode)
        self.channel_management_panel.apply_gui_mode(mode)
        self.info_panel.apply_gui_mode(mode)

    def toggle_right_panel(self):
        """Toggle the visibility of the right panel"""
        now_visible = not self.right_panel_scroll.isVisible()
        self.right_panel_scroll.setVisible(now_visible)
        self.btn_right_panel_toggle.setText(
            "Hide session panel" if now_visible else "Show session panel"
        )

        # Adjust splitter sizes based on visibility
        if now_visible:
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
        self.remove_widget_from_right_panel(widget_type, update_session=False)
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

    def _restore_right_panel_widgets(self):
        gui_setup = self.session_manager.gui_setup
        desired_widgets = list(gui_setup.right_panel_widgets) if gui_setup else []
        for current_widget in copy(self.right_panel_widgets):
            self.remove_widget_from_right_panel(current_widget, update_session=False)
        if self._workspace is not None and RightPanelWidgetEnum.RECORDING_NAVIGATION not in desired_widgets:
            desired_widgets.insert(0, RightPanelWidgetEnum.RECORDING_NAVIGATION)
        for widget_type in desired_widgets:
            self.add_widget_to_right_panel(widget_type, update_session=False)

    # ---------- Callbacks menu ----------
    def __confirm_discard_unsaved_changes(self, question: str) -> bool:
        """Ask the user before dropping unsaved session changes. True means proceed."""
        if not (self.session_manager.session_is_active
                and self.session_manager.user_session
                and not self.session_manager.user_session.changes_saved):
            return True

        result = QMessageBox.warning(
            self,
            "Session not saved",
            f"Some changes in the session was not saved. {question}",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel
        )
        return result != QMessageBox.StandardButton.Cancel

    # ---------- Workspace ----------
    def on_create_workspace(self):
        if not self.__confirm_discard_unsaved_changes("Are you sure you want to create another workspace?"):
            return
        dialog = CreateWorkspaceDialog(self, self._workspace.root.parent if self._workspace else None)
        if not dialog.exec():
            return
        parent, name = dialog.values()
        try:
            workspace = Workspace.create(parent, name)
        except (WorkspaceError, OSError) as exc:
            QMessageBox.warning(self, "Cannot create workspace", str(exc))
            return
        self.__set_workspace(workspace)
        self.__set_status(f"Workspace created: {workspace.root}")

    def on_open_workspace_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Ephyr workspace", "",
            f"Ephyr workspace ({settings.WORKSPACE_MANIFEST_FILENAME});;All files (*)",
        )
        if path:
            self.open_workspace_path(Path(path))

    def on_open_workspace_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Open Ephyr workspace folder", "",
                                                QFileDialog.Option.ShowDirsOnly)
        if path:
            self.open_workspace_path(Path(path))

    def on_open_recent_workspace(self, workspace_root: Path):
        if not Path(workspace_root).exists():
            self.global_storage_manager.update_recent_workspaces_list(workspace_root, to_delete=True)
            self.__update_recent_dirs()
            self.__set_status("Recent workspace folder does not exist")
            return
        self.open_workspace_path(Path(workspace_root))

    def open_workspace_path(self, path: Path) -> bool:
        if not self.__confirm_discard_unsaved_changes("Are you sure you want to open another workspace?"):
            return False
        try:
            workspace = Workspace.open(path)
        except Exception as exc:
            ephyr_logger().error(f"Cannot open workspace {path}", exc_info=exc)
            QMessageBox.warning(self, "Cannot open workspace", str(exc))
            return False
        self.__set_workspace(workspace)
        self.__set_status(f"Workspace opened: {workspace.root}")
        return True

    def __set_workspace(self, workspace: Workspace):
        self.__close_record()
        self._workspace = workspace
        self.global_storage_manager.update_recent_workspaces_list(workspace.root)
        self.__update_recent_dirs()
        position = self.global_storage_manager.workspace_position(workspace.manifest.uid)
        config_id, record_id = position.config_id, position.record_id
        if workspace.record(config_id, record_id) is None:
            config_id, record_id = self.__default_location(config_id)
        self._config_id = config_id
        if record_id is not None:
            self.__open_record(config_id, record_id, preferred_session=position.session_name)
        else:
            self.__show_workspace_state()

    def __default_location(self, config_id: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
        """A Config (the given one when it exists) and its last opened or first Record."""
        workspace = self._workspace
        configs = workspace.configs()
        if not configs:
            return None, None
        config = workspace.config(config_id) if config_id else None
        config = config or configs[0]
        position = self.global_storage_manager.workspace_position(workspace.manifest.uid)
        record_id = position.last_record_by_config.get(config.config_id)
        if workspace.record(config.config_id, record_id) is None:
            records = workspace.records(config.config_id)
            record_id = records[0].record_id if records else None
        return config.config_id, record_id

    def __close_record(self):
        self.session_manager.close_record()
        self._processed_channels_data_cache = {}
        self._overlay_channels_data_cache = {}
        self._overlay_cache_segment_idxs = ()
        # Memmaps of the closed Record must be released before its files can be removed (Windows).
        gc.collect()

    def __open_record(self, config_id: str, record_id: str, preferred_session: Optional[str] = None) -> bool:
        workspace = self._workspace
        previous_record_id = self.global_storage_manager.workspace_position(
            workspace.manifest.uid).last_record_by_config.get(config_id)
        self.__close_record()
        self._config_id = config_id
        try:
            record = workspace.record(config_id, record_id)
            self.session_manager.open_record(
                workspace, config_id, record_id,
                original_source_path=(
                    self.global_storage_manager.record_source_path(record.uid) if record else None),
            )
        except Exception as exc:
            ephyr_logger().error(f"Cannot open Record {record_id}", exc_info=exc)
            QMessageBox.warning(self, "Cannot open Record", f"Record '{record_id}' cannot be opened:\n\n{exc}")
            self.__close_record()
            self.__show_workspace_state()
            return False

        sessions = self.session_manager.other_session_names
        selected_session = None
        if preferred_session in sessions:
            selected_session = preferred_session
        elif len(sessions) == 1:
            selected_session = sessions[0]
        elif len(sessions) > 1:
            selected_session = SelectSessionDialog(sessions, self).get_selected_item()

        first_session = False
        if selected_session is None:
            session_name = self.__new_unique_session_name(
                default=settings.DEFAULT_SESSION_NAME if not sessions else "")
            if session_name is None:
                self.__close_record()
                self.__show_workspace_state()
                return False
            self.session_manager.new_user_session(session_name)
            selected_session = session_name
            first_session = not sessions

        self.__switch_to_session(selected_session)
        if first_session and previous_record_id and previous_record_id != record_id:
            self.__offer_settings_from_record(config_id, previous_record_id)
        self.__set_status(f"Record '{self.session_manager.record.name}' is opened")
        return True

    def __offer_settings_from_record(self, config_id: str, source_record_id: str):
        """First session of a new Record: copy settings from the Record of this Config opened before."""
        candidates = [item for item in records_with_sessions(self._workspace, config_id, None)
                      if item[0] == source_record_id]
        if not candidates:
            return
        _record_id, record_name, sessions = candidates[0]
        position = self.global_storage_manager.workspace_position(self._workspace.manifest.uid)
        session_name = position.session_name if position.session_name in sessions else sessions[0]
        answer = QMessageBox.question(
            self, "Copy settings",
            f"This is the first session of the Record. Copy GUI settings and event/period vocabularies "
            f"from Record '{record_name}' (session '{session_name}')?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.__import_settings_from(source_record_id, session_name, include_vocabularies=True)

    def __import_settings_from(self, record_id: str, session_name: str, include_vocabularies: bool):
        folder = layout.session_dir(self._workspace.record_dir(self.session_manager.config_id, record_id),
                                    session_name)
        try:
            other = UserSession.load(folder)
        except Exception as exc:
            self.__set_status(f"Cannot read session '{session_name}': {exc}")
            return
        self.session_manager.import_settings_from_session(other, include_vocabularies)
        self._restore_right_panel_widgets()
        self.__update_menu()
        self.__recalculate_and_redraw_necessary_signals(recalculate_data=True)
        self.__set_status(f"GUI settings imported from session '{session_name}'")

    def __show_workspace_state(self):
        """Refresh navigation and, without an open session, the empty-workspace page."""
        workspace = self._workspace
        self.recording_navigation_panel.set_workspace(workspace, self._config_id, self.session_manager.record_id)
        if workspace is not None:
            config = workspace.config(self._config_id) if self._config_id else None
            if not workspace.configs():
                state = StartScreenStateEnum.EMPTY_WORKSPACE
            elif config is None or not config.records:
                state = StartScreenStateEnum.EMPTY_CONFIG
            else:
                state = StartScreenStateEnum.NO_RECORD_OPEN
            self.start_screen_panel.set_state(state, workspace.name, config.name if config else "")
            if RightPanelWidgetEnum.RECORDING_NAVIGATION not in self.right_panel_widgets:
                self.add_widget_to_right_panel(RightPanelWidgetEnum.RECORDING_NAVIGATION,
                                               update_session=self.session_manager.session_is_active)
        else:
            self.start_screen_panel.set_state(StartScreenStateEnum.NO_WORKSPACE)
        self.__update_main_content_panel()
        self.__redraw_header()

    def __remember_position(self):
        if self._workspace is None:
            return
        session = self.session_manager.current_user_session
        self.global_storage_manager.remember_position(
            self._workspace.manifest.uid,
            self._config_id,
            self.session_manager.record_id,
            session.session_name if session else None,
        )

    # ---------- Config / Record / Source ----------
    def on_config_selected(self, config_id: str):
        if self._workspace is None or config_id == self._config_id:
            return
        if not self.__confirm_discard_unsaved_changes("Are you sure you want to switch to another Config?"):
            self.__show_workspace_state()
            return
        config_id, record_id = self.__default_location(config_id)
        self.__close_record()
        self._config_id = config_id
        if record_id is not None:
            self.__open_record(config_id, record_id)
        else:
            self.__show_workspace_state()

    def on_record_selected(self, record_id: str):
        if self._workspace is None or self._config_id is None or record_id == self.session_manager.record_id:
            return
        if not self.__confirm_discard_unsaved_changes("Are you sure you want to switch to another Record?"):
            self.__show_workspace_state()
            return
        self.__open_record(self._config_id, record_id)

    def on_add_requested(self, level: str, path: Optional[Path] = None):
        workspace = self._workspace
        if workspace is None:
            self.__set_status("Create or open a workspace first")
            return
        level = WorkspaceLevelEnum(level)
        if level is WorkspaceLevelEnum.SOURCE:
            if not self.session_manager.session_is_active:
                self.__set_status("Open a Record to add a source to it")
                return
            new_ids = self.workspace_actions.add_source(workspace, self.session_manager.config_id,
                                                        self.session_manager.record_id, path)
            if new_ids:
                self.session_manager.set_active_source(new_ids[0])
                self.__show_workspace_state()
                self.__set_status(f"Sources added: {', '.join(new_ids)}")
            return

        if level is WorkspaceLevelEnum.RECORD:
            if self._config_id is None:
                self.__set_status("Add a Config first")
                return
            location = self.workspace_actions.add_record(workspace, self._config_id, path)
        else:
            location = self.workspace_actions.add_config(workspace, path)
        if location is None:
            self.__show_workspace_state()
            return
        if not self.__confirm_discard_unsaved_changes("The new Record is ready. Open it now?"):
            self.__show_workspace_state()
            return
        self.__open_record(location.config_id, location.record_id)

    def on_remove_requested(self, level: str):
        workspace = self._workspace
        if workspace is None:
            return
        level = WorkspaceLevelEnum(level)
        config_id = self._config_id
        record_id = self.session_manager.record_id
        actions = self.workspace_actions
        try:
            if level is WorkspaceLevelEnum.CONFIG and config_id:
                if not actions.confirm_remove_config(workspace, config_id):
                    return
                self.__close_record()
                workspace.remove_config(config_id)
                self._config_id = None
            elif level is WorkspaceLevelEnum.RECORD and config_id and record_id:
                if not actions.confirm_remove_record(workspace, config_id, record_id):
                    return
                self.__close_record()
                workspace.remove_record(config_id, record_id)
            elif level is WorkspaceLevelEnum.SOURCE and record_id:
                source_id = self.session_manager.active_source_id
                if not actions.confirm_remove_source(workspace, config_id, record_id, source_id):
                    return
                self.session_manager.set_active_source(workspace.config(config_id).main_source_id)
                gc.collect()
                workspace.remove_source(config_id, record_id, source_id)
                self.session_manager.save_user_session()
                self.__show_workspace_state()
                self.__set_status(f"Source '{source_id}' removed")
                return
            else:
                return
        except (WorkspaceError, OSError) as exc:
            QMessageBox.warning(self, "Cannot remove", str(exc))
            return
        self.__set_status(f"{level.value.capitalize()} removed")
        config_id, next_record_id = self.__default_location(self._config_id)
        self._config_id = config_id
        if next_record_id is not None:
            self.__open_record(config_id, next_record_id)
        else:
            self.__show_workspace_state()

    def on_rename_requested(self, level: str):
        workspace = self._workspace
        if workspace is None:
            return
        level = WorkspaceLevelEnum(level)
        actions = self.workspace_actions
        if level is WorkspaceLevelEnum.CONFIG and self._config_id:
            renamed = actions.rename_config(workspace, self._config_id)
        elif level is WorkspaceLevelEnum.RECORD and self.session_manager.record_id:
            renamed = actions.rename_record(workspace, self._config_id, self.session_manager.record_id)
        elif level is WorkspaceLevelEnum.SOURCE and self.session_manager.active_source_id:
            renamed = actions.rename_source(workspace, self._config_id, self.session_manager.active_source_id)
        else:
            return
        if renamed:
            if self.session_manager.session_is_active:
                self.session_manager.source_view.spec.name = (
                    workspace.config(self._config_id).source(self.session_manager.active_source_id).name)
            self.__show_workspace_state()

    # ---------- Drag and drop ----------
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        if not paths:
            return
        event.acceptProposedAction()
        path = paths[0]
        if find_workspace_root(path) is not None:
            self.open_workspace_path(path)
        elif self._workspace is not None:
            self.on_add_requested(WorkspaceLevelEnum.CONFIG, path)
        else:
            self.__set_status("Drop a workspace folder or workspace.ephyr; recordings are added to an open workspace")

    # ---------- Sessions ----------
    def on_open_another_session(self, session_name: str):
        if not self.__confirm_discard_unsaved_changes("Are you sure you want to switch to another session?"):
            return

        try:
            self.__switch_to_session(session_name)
        except Exception as e:
            self.__set_status(repr(e))
        else:
            self.__set_status("Session was switched to " + self.session_manager.user_session.session_name)

    def on_new_session(self):
        if self.session_manager.record_dir is None:
            self.__set_status("Warning: open a Record first")
            return
        if not self.__confirm_discard_unsaved_changes("Are you sure you want to start a new session?"):
            return
        session_name = self.__new_unique_session_name()
        if session_name is None:
            return

        self.session_manager.new_user_session(session_name)
        self.__switch_to_session(session_name)

    def on_save_session(self):
        if self.session_manager.session_is_active:
            self.session_manager.save_user_session()
            self.__set_status("Session was saved successfully")

    def __choose_session_folder(self, title: str) -> Optional[Path]:
        path = QFileDialog.getExistingDirectory(self, title, str(self.session_manager.sessions_folder or ""),
                                                QFileDialog.Option.ShowDirsOnly)
        return Path(path) if path else None

    def on_import_session(self):
        if not self.session_manager.session_is_active:
            self.__set_status("Warning: there is no active Record to import to")
            return
        folder = self.__choose_session_folder("Select a session folder")
        if folder is None:
            return
        try:
            session_to_import = UserSession.load(folder)
        except Exception as e:
            self.__set_status(f"Corrupted session folder: {e}")
            return
        while self.session_manager.session_name_already_exists(session_to_import.session_name):
            new_session_name = self.__new_unique_session_name()
            if new_session_name is None:
                return
            session_to_import.session_name = new_session_name

        self.session_manager.import_new_session(session_to_import)
        self.__update_sessions()
        self.__set_status("Imported successfully as " + session_to_import.session_name)

    def __load_annotations_session(self, file_path: Path) -> Optional[UserSession]:
        folder = file_path if file_path.is_dir() else file_path.parent
        try:
            return UserSession.load(folder)
        except Exception as e:
            self.__set_status(f"Corrupted session folder: {e}")
            return None

    def on_import_events(self):
        if not self.session_manager.session_is_active:
            self.__set_status("Warning: there is no active Record to import to")
            return
        file_to_import, _ = QFileDialog.getOpenFileName(
            self,
            "Select events source",
            str(self.session_manager.sessions_folder or ""),
            "Session or legacy events (events.csv settings.json *.mat);;MAT files (*.mat);;All files (*)",
        )
        if not file_to_import:
            return

        file_path = Path(file_to_import)
        debug_info: Dict[str, str] = {}
        try:
            if file_path.suffix.lower() == ".mat":
                imported_vocabulary, imported_events, debug_info = import_legacy_events_from_mat(
                    file_path, self.session_manager.source_view)
            else:
                session_to_import = self.__load_annotations_session(file_path)
                if session_to_import is None:
                    return
                imported_vocabulary = session_to_import.events_vocabulary
                imported_events = session_to_import.events
        except LegacyMatEventsImportError as e:
            self.__set_status(f"Import error (.mat): {e}")
            return
        except Exception as e:
            self.__set_status(f"Import error: {e}")
            return

        self.session_manager.import_vocabulary_and_events(imported_vocabulary, imported_events)
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

    def on_import_periods(self):
        if not self.session_manager.session_is_active:
            self.__set_status("Warning: there is no active Record to import to")
            return
        file_to_import, _ = QFileDialog.getOpenFileName(
            self, "Select periods of a session", str(self.session_manager.sessions_folder or ""),
            "Session files (periods.csv settings.json);;All files (*)",
        )
        if not file_to_import:
            return
        session_to_import = self.__load_annotations_session(Path(file_to_import))
        if session_to_import is None:
            return

        self.session_manager.import_vocabulary_and_periods(
            session_to_import.periods_vocabulary,
            session_to_import.periods,
        )
        self.__set_status(
            f"Imported periods: {len(session_to_import.periods)}; "
            f"vocabulary entries: {len(session_to_import.periods_vocabulary)}"
        )

    def on_import_settings(self):
        if not self.session_manager.session_is_active:
            self.__set_status("Warning: there is no active Record to import to")
            return
        config_id = self.session_manager.config_id
        records = records_with_sessions(self._workspace, config_id, self.session_manager.record_id)
        if not records:
            self.__set_status("Other Records of this Config have no sessions to import settings from")
            return
        position = self.global_storage_manager.workspace_position(self._workspace.manifest.uid)
        previous = position.last_record_by_config.get(config_id)
        dialog = ImportSettingsDialog(records, self, preferred=(previous, "") if previous else None)
        if not dialog.exec():
            return
        record_id, session_name, include_vocabularies = dialog.selection()
        if not session_name:
            return
        self.__import_settings_from(record_id, session_name, include_vocabularies)

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
            folder = str(layout.session_dir(self.session_manager.record_dir,
                                            self.session_manager.user_session.session_name))
            if os.name == 'nt':  # Windows
                subprocess.run(['explorer', folder])
            elif os.name == 'posix':  # macOS or Linux
                subprocess.run(['open', folder])  # For macOS
                # For Linux, you might need 'xdg-open' or a specific file manager command
                # subprocess.run(['xdg-open', folder_path])
        else:
            self.__set_status("Warning: ephyr session is not active")

    def closeEvent(self, event):
        if self.__confirm_discard_unsaved_changes("Are you sure you want to exit?"):
            event.accept()
        else:
            event.ignore()

    def on_exit(self):
        if not self.__confirm_discard_unsaved_changes("Are you sure you want to exit?"):
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

    def on_view_channel_names(self, checked: bool, *args, **kwargs):
        if self.session_manager.session_is_active:
            self.session_manager.set_channel_names_shown(checked)

    def on_view_channel_info(self, checked: bool, *args, **kwargs):
        if self.session_manager.session_is_active:
            self.session_manager.set_channel_infos_shown(checked)

    def on_view_events(self, checked: bool, *args, **kwargs):
        if self.session_manager.session_is_active:
            self.session_manager.set_events_shown(checked)

    def on_view_periods(self, checked: bool, *args, **kwargs):
        if self.session_manager.session_is_active:
            self.session_manager.set_periods_shown(checked)

    def on_view_recording_navigation_panel(self, checked: bool, *args, **kwargs):
        if checked:
            self.add_widget_to_right_panel(RightPanelWidgetEnum.RECORDING_NAVIGATION)
        else:
            self.remove_widget_from_right_panel(RightPanelWidgetEnum.RECORDING_NAVIGATION)

    def on_view_time_settings_panel(self, checked: bool, *args, **kwargs):
        if checked:
            self.add_widget_to_right_panel(RightPanelWidgetEnum.TIME_SETTINGS)
        else:
            self.remove_widget_from_right_panel(RightPanelWidgetEnum.TIME_SETTINGS)

    def on_view_channel_management_panel(self, checked: bool, *args, **kwargs):
        if checked:
            self.add_widget_to_right_panel(RightPanelWidgetEnum.CHANNEL_MANAGEMENT)
        else:
            self.remove_widget_from_right_panel(RightPanelWidgetEnum.CHANNEL_MANAGEMENT)

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
        self.__set_status("Select two points on EEG panel to remove invalid mark for events (right click to cancel)")

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

    def on_ephyr_guide(self):
        QDesktopServices.openUrl(QUrl(settings.DOCUMENTATION_LINK))

    def on_about(self):
        AboutDialog(self).exec()

    def on_hotkeys(self):
        HotkeysDialog(self).exec()

    def on_debug(self):
        capture_widget_to_file(self, self, "main_window_full")
        capture_widget_to_file(self, self.right_panel_container, "right_panel")
        self.__set_status("DEBUG DONE")

    def on_scalebar(self):
        self.signal_panel.toggle_scalebar()
        self._sync_toolbar_modes()
        self.signal_panel.setFocus()

    def on_zoom_to_area(self):
        self.signal_panel.toggle_zoom_to_area()
        self._sync_toolbar_modes()
        self.signal_panel.setFocus()

    def _sync_toolbar_modes(self):
        self.btn_scalebar.setChecked(self.signal_panel.scalebar_is_active())
        self.btn_zoom_to_area.setChecked(self.signal_panel.zoom_to_area_is_active())

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
            current_segment_idx=gui_setup.current_segment_idx,
            start_point=gui_setup.start_point,
            duration_ms=gui_setup.duration_ms,
            groups_layout=self.signal_panel.get_visible_groups_layout(),
            channels_setup=gui_setup.channels_setup,
            channel_units=self.signal_panel.signal_widget.channel_units,
        )
        result = ScreenshotExportDialog.run_export(self, context)
        self.__set_status(result.message)

    def __switch_to_session(self, selected_session: str):
        self.session_manager.switch_sessions(selected_session)
        self.__update_main_content_panel()
        self.__recalculate_and_redraw_necessary_signals(recalculate_data=True, )
        self.__update_recent_dirs()
        self.__update_sessions()
        self.__update_menu()
        self._restore_right_panel_widgets()
        self.__show_workspace_state()
        self.__remember_position()

    def __update_recent_dirs(self):
        self.menu_open_recent.clear()
        recent_workspaces = list(self.global_storage_manager.recent_workspaces)
        for recent in recent_workspaces:
            act_open_recent = QAction(str(recent), self)
            act_open_recent.triggered.connect(partial(self.on_open_recent_workspace, recent))
            self.menu_open_recent.addAction(act_open_recent)
        if hasattr(self, "start_screen_panel"):
            self.start_screen_panel.set_recent_workspaces(recent_workspaces)

    def __update_sessions(self):
        self.menu_sessions.clear()
        current = self.session_manager.current_user_session
        for session_name in self.session_manager.other_session_names:
            if current is not None and session_name == current.session_name:
                continue
            act_open_session = QAction(session_name, self)
            act_open_session.triggered.connect(partial(self.on_open_another_session, session_name))
            self.menu_sessions.addAction(act_open_session)

    def __update_menu(self):
        self.view_traces.setChecked(self.session_manager.gui_setup.traces_are_shown)
        self.view_channel_names.setChecked(self.session_manager.gui_setup.channel_names_are_shown)
        self.view_channel_info.setChecked(self.session_manager.gui_setup.channel_infos_are_shown)
        self.view_events.setChecked(self.session_manager.gui_setup.events_are_shown)
        self.view_periods.setChecked(self.session_manager.gui_setup.periods_are_shown)

    def __redraw_header(self):
        workspace = self._workspace
        if workspace is None:
            self.current_session_label.setText("No workspace")
            return
        parts = [f"Workspace: {workspace.name}"]
        config = workspace.config(self._config_id) if self._config_id else None
        if config is not None:
            parts.append(f"Config: {config.name}")
        record = self.session_manager.record
        if record is not None:
            parts.append(f"Record: {record.name}")
        view = self.session_manager.source_view
        # if view is not None and config is not None and len(record.sources) > 1:
        #     parts.append(f"Source: {view.source_name}")
        session = self.session_manager.current_user_session
        if session is not None:
            parts.insert(0, f"Session: {session.session_name}")
        self.current_session_label.setText("  |  ".join(parts))

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

    def __new_unique_session_name(self, default: str = "") -> Optional[str]:
        while True:
            dialog = SessionNameDialog(self)
            dialog.line_edit.setText(default)
            if not dialog.exec():
                return None
            session_name = dialog.line_edit.text().strip()
            if not is_valid_session_name(session_name):
                QMessageBox.warning(self, "Warning",
                                    "Session name must not be empty or contain any of < > : \" / \\ | ? *")
            elif self.session_manager.session_name_already_exists(session_name):
                QMessageBox.warning(self, "Warning",
                                    f"Session with the name {session_name} already exists.")
            else:
                return session_name

    def _add_labeled_menu_section(self, menu, title: str) -> None:
        """Group title that stays visible when the style draws addSection() as a plain line."""
        if menu.style().styleHint(QStyle.StyleHint.SH_Menu_SupportsSections):
            menu.addSection(title)
            return
        menu.addSeparator()
        title_action = QAction(title, self)
        title_action.setEnabled(False)
        menu.addAction(title_action)

    def __get_panel_by_type(self, widget_type: RightPanelWidgetEnum):
        if widget_type == RightPanelWidgetEnum.RECORDING_NAVIGATION:
            return self.recording_navigation_panel
        elif widget_type == RightPanelWidgetEnum.TIME_SETTINGS:
            return self.time_settings_panel
        elif widget_type == RightPanelWidgetEnum.CHANNEL_MANAGEMENT:
            return self.channel_management_panel
        elif widget_type == RightPanelWidgetEnum.LOGS:
            return self.logs_panel
        elif widget_type == RightPanelWidgetEnum.INFORMATION:
            return self.info_panel
        elif widget_type == RightPanelWidgetEnum.ANALYSIS:
            return self.analysis_panel
        else:
            raise ValueError("Unknown widget_type")

    def __set_panel_checked_by_type(self, widget_type: RightPanelWidgetEnum, checked: bool):
        if widget_type == RightPanelWidgetEnum.RECORDING_NAVIGATION:
            self.view_recording_navigation_panel.setChecked(checked)
        elif widget_type == RightPanelWidgetEnum.TIME_SETTINGS:
            self.view_time_settings_panel.setChecked(checked)
        elif widget_type == RightPanelWidgetEnum.CHANNEL_MANAGEMENT:
            self.view_channel_management_panel.setChecked(checked)
        elif widget_type == RightPanelWidgetEnum.LOGS:
            self.view_logs_panel.setChecked(checked)
        elif widget_type == RightPanelWidgetEnum.INFORMATION:
            self.view_info_panel.setChecked(checked)
        elif widget_type == RightPanelWidgetEnum.ANALYSIS:
            self.view_analysis_panel.setChecked(checked)
        else:
            raise ValueError("Unknown widget_type")

    def __get_right_panel_widget_position(self, widget_type: RightPanelWidgetEnum, right_panel_widgets: List[RightPanelWidgetEnum]):
        # Index 0 is reserved for the Session panel selector at the top of the right panel.
        idx = 1
        for widget in RightPanelWidgetEnum.widgets_order():
            if widget == widget_type:
                return idx
            elif widget in right_panel_widgets:
                idx += 1
