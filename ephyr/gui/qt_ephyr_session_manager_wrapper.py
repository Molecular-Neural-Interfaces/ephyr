# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

from PyQt6.QtCore import QObject, pyqtSignal
from typing import List, Optional, Dict, Tuple
from pathlib import Path

from ephyr.core.add_ons.utils import load_installed_add_ons, load_dev_add_ons
from ephyr import settings
from ephyr.core.conversions.filters import ensure_filters_list

from ephyr.core.units import canonical_unit_label
from ephyr.core.source_view import NavigationModeEnum, SourceView
from ephyr.core.workspace import Workspace
from ephyr.core.ephyr_session import (
    EphyrSessionManager,
    GuiSetup,
    AddOnSetup,
    RightPanelWidgetEnum,
    UserSession,
    Event,
    Period,
    ChannelGroup,
    ChannelsLayout,
    GroupLayout,
    EventVocabularyEntry,
    PeriodVocabularyEntry,
)
from ephyr.core.add_ons.base import BaseAddOn
from ephyr.logger import ephyr_logger, set_log_record, set_log_session_name

from ephyr.gui.commands.base import BaseCommand
from ephyr.gui.commands.events import (
    AddEventCommand,
    AddEventsCommand,
    RemoveEventsCommand,
    SetEventsBadFlagCommand,
    AddEventVocabularyCommand,
    SetEventVocabularyNameCommand,
    SetEventVocabularyColorCommand,
    SetEventVocabularyVisibilityCommand,
    RemoveEventVocabularyCommand,
    ImportVocabularyAndEventsCommand,
)
from ephyr.gui.commands.periods import (
    AddPeriodCommand,
    RemovePeriodsCommand,
    AddPeriodVocabularyCommand,
    SetPeriodVocabularyNameCommand,
    SetPeriodVocabularyColorCommand,
    SetPeriodVocabularyVisibilityCommand,
    RemovePeriodVocabularyCommand,
    ImportVocabularyAndPeriodsCommand,
)


def user_session_modification(func):
    def wrapper(self, *args, **kwargs):
        if self._session_manager.current_user_session:
            self._session_manager.current_user_session.changes_saved = False
            return func(self, *args, **kwargs)
        else:
            return None

    return wrapper


class QtEphyrSessionManagerWrapper(QObject):
    # Signals for RightPanelWidgetEnum list
    right_panel_widgets_changed = pyqtSignal(list)

    # Signal for channel-group filters changes
    filters_changed = pyqtSignal()

    # Signals for boolean flags
    traces_are_shown_changed = pyqtSignal(bool)
    channel_names_are_shown_changed = pyqtSignal(bool)
    channel_infos_are_shown_changed = pyqtSignal(bool)
    events_are_shown_changed = pyqtSignal(bool)
    periods_are_shown_changed = pyqtSignal(bool)
    cut_traces_changed = pyqtSignal(bool)

    # Signals for numerical parameters
    start_point_changed = pyqtSignal(int)
    duration_ms_changed = pyqtSignal(int)
    time_step_ms_changed = pyqtSignal(int)
    autoscroll_step_interval_ms_changed = pyqtSignal(int)
    number_of_dots_to_display_changed = pyqtSignal(int)
    current_segment_idx_changed = pyqtSignal(int)
    overlay_segment_idxs_changed = pyqtSignal(list)
    # Navigation mode, period label or pre/post window changed and display segments were rebuilt.
    display_segments_changed = pyqtSignal()
    active_source_changed = pyqtSignal(str)

    # Signals for strings
    experiment_description_changed = pyqtSignal(str)
    visual_attachment_changed = pyqtSignal(str)

    # Signals for channel groups and channels setup
    channels_groups_changed = pyqtSignal(list)
    channel_setup_changed = pyqtSignal()
    channel_units_changed = pyqtSignal(list)

    # Session management signals
    session_saved = pyqtSignal()
    session_loaded = pyqtSignal()

    # Event signals
    events_vocabulary_changed = pyqtSignal(dict)
    events_changed = pyqtSignal(list)
    # Period signals
    periods_vocabulary_changed = pyqtSignal(dict)
    periods_changed = pyqtSignal(list)
    add_ons_changed = pyqtSignal(dict)
    add_ons_run = pyqtSignal(str)

    def __init__(self, session_manager: EphyrSessionManager):
        super().__init__()
        self._session_manager = session_manager
        self._original_source_path: Optional[Path] = None
        self._undo_stack: List[BaseCommand] = []
        self._redo_stack: List[BaseCommand] = []
        self._runtime_add_ons: Dict[str, BaseAddOn] = {}
        self.periods_changed.connect(self._on_periods_changed)

    @property
    def source_view(self) -> Optional[SourceView]:
        """Active source of the open Record."""
        return self._session_manager.source_view

    def channel_unit_display(self, channel_idx: int) -> str:
        view = self.source_view
        return view.channel_unit_display(channel_idx) if view else ""

    def default_scale_for_channel(self, _channel_idx: int) -> float:
        return float(settings.DEFAULT_SCALE)

    def default_scale_for_group(self, _channel_indexes: List[int]) -> float:
        return float(settings.DEFAULT_SCALE)

    @property
    def gui_setup(self) -> Optional[GuiSetup]:
        if self._session_manager.current_user_session:
            return self._session_manager.current_user_session.gui_setup
        return None

    @property
    def current_user_session(self) -> Optional[UserSession]:
        return self._session_manager.current_user_session

    @property
    def events_vocabulary(self) -> Dict[int, EventVocabularyEntry]:
        if self._session_manager.current_user_session:
            return self._session_manager.current_user_session.events_vocabulary

        return {}

    @property
    def events_vocabulary_names(self) -> Dict[int, str]:
        return {idx: entry.name for idx, entry in self.events_vocabulary.items()}

    @property
    def events_vocabulary_colors(self) -> Dict[int, str]:
        return {idx: entry.color for idx, entry in self.events_vocabulary.items()}

    @property
    def events(self) -> List[Event]:
        if self._session_manager.current_user_session:
            return self._session_manager.current_user_session.events

        return []

    @property
    def periods_vocabulary(self) -> Dict[int, PeriodVocabularyEntry]:
        if self._session_manager.current_user_session:
            return self._session_manager.current_user_session.periods_vocabulary

        return {}

    @property
    def periods_vocabulary_names(self) -> Dict[int, str]:
        return {idx: entry.name for idx, entry in self.periods_vocabulary.items()}

    @property
    def periods_vocabulary_colors(self) -> Dict[int, str]:
        return {idx: entry.color for idx, entry in self.periods_vocabulary.items()}

    @property
    def periods(self) -> List[Period]:
        if self._session_manager.current_user_session:
            return self._session_manager.current_user_session.periods

        return []

    @property
    def channel_groups(self) -> List[ChannelGroup]:
        if self.gui_setup:
            return self.gui_setup.channels_groups
        return []

    @user_session_modification
    def set_right_panel_widgets(self, widgets: List[RightPanelWidgetEnum]):
        self._session_manager.current_user_session.gui_setup.right_panel_widgets = widgets
        self.right_panel_widgets_changed.emit(widgets)

    @user_session_modification
    def set_traces_shown(self, shown: bool):
        self._session_manager.current_user_session.gui_setup.traces_are_shown = shown
        self.traces_are_shown_changed.emit(shown)

    @user_session_modification
    def set_channel_names_shown(self, shown: bool):
        self._session_manager.current_user_session.gui_setup.channel_names_are_shown = shown
        self.channel_names_are_shown_changed.emit(shown)

    @user_session_modification
    def set_channel_infos_shown(self, shown: bool):
        self._session_manager.current_user_session.gui_setup.channel_infos_are_shown = shown
        self.channel_infos_are_shown_changed.emit(shown)

    @user_session_modification
    def set_add_on(
            self,
            module_name: str,
            *,
            view_enabled: bool = False,
            transform_enabled: bool = False,
    ):
        if module_name not in self._runtime_add_ons:
            self.refresh_runtime_add_ons()
        if module_name not in self._runtime_add_ons:
            return

        self._session_manager.current_user_session.gui_setup.add_ons[module_name] = AddOnSetup(
            view_enabled=bool(view_enabled),
            transform_enabled=bool(transform_enabled),
        )
        self.add_ons_changed.emit(dict(self._session_manager.current_user_session.gui_setup.add_ons))

    @user_session_modification
    def pop_add_on(self, module_name: str):
        self._session_manager.current_user_session.gui_setup.add_ons.pop(module_name, None)
        self.add_ons_changed.emit(dict(self._session_manager.current_user_session.gui_setup.add_ons))

    @user_session_modification
    def remove_add_on(self, module_name: str):
        self.pop_add_on(module_name)

    def notify_add_on_run(self, module_name: str):
        self.add_ons_run.emit(module_name)

    def refresh_runtime_add_ons(self):
        self._runtime_add_ons = load_installed_add_ons() | load_dev_add_ons()
        self._sync_add_on_setups_with_runtime()

    def _sync_add_on_setups_with_runtime(self):
        if not self._session_manager.current_user_session or not self._session_manager.record_dir:
            return
        add_on_setups = self._session_manager.current_user_session.gui_setup.add_ons
        setups: Dict[str, AddOnSetup] = {}
        for key, setup in list(add_on_setups.items()):
            if key not in setups:
                setups[key] = setup
        self._session_manager.current_user_session.gui_setup.add_ons = setups
        add_on_setups = self._session_manager.current_user_session.gui_setup.add_ons
        current_keys = set(add_on_setups.keys())
        runtime_keys = set(self._runtime_add_ons.keys())
        for module_name in runtime_keys - current_keys:
            add_on_setups[module_name] = AddOnSetup(view_enabled=False, transform_enabled=False)
        for module_name in current_keys - runtime_keys:
            add_on_setups.pop(module_name, None)
        self.add_ons_changed.emit(dict(add_on_setups))

    def get_runtime_add_on(self, module_name: str) -> Optional[BaseAddOn]:
        return self._runtime_add_ons.get(module_name)

    def get_all_add_ons(self) -> Dict[str, BaseAddOn]:
        return dict(self._runtime_add_ons)

    def get_viewable_add_ons(self) -> Dict[str, BaseAddOn]:
        return self.__get_add_ons(lambda add_on: add_on.VIEWABLE == False, 
                                  lambda setup: not setup.view_enabled)

    def get_transformation_add_ons(self) -> Dict[str, BaseAddOn]:
        return self.__get_add_ons(lambda add_on: add_on.TRANSFORMATION == False, 
                                  lambda setup: not setup.transform_enabled)

    def __get_add_ons(self, filter_by_add_on_field, filter_by_setup_func):
        add_ons = []
        for module_name, setup in (self.gui_setup.add_ons or {}).items():
            add_on_obj = self._runtime_add_ons.get(module_name)
            if add_on_obj is None or filter_by_add_on_field(add_on_obj) or filter_by_setup_func(setup):
                continue
            add_ons.append(add_on_obj)

        return add_ons

    def has_runtime_add_on(self, module_name: str) -> bool:
        return module_name in self._runtime_add_ons

    def has_runtime_distribution(self, distribution_name: str) -> bool:
        distribution_name = (distribution_name or "").strip()
        if not distribution_name:
            return False
        return any(
            getattr(add_on, "_ephyr_distribution_name", None) == distribution_name
            for add_on in self._runtime_add_ons.values()
        )

    def runtime_add_on_distribution_name(self, module_name: str) -> Optional[str]:
        add_on = self._runtime_add_ons.get(module_name)
        if add_on is None:
            return None
        return getattr(add_on, "_ephyr_distribution_name", None)

    def runtime_add_on_names_for_distribution(self, distribution_name: str) -> List[str]:
        distribution_name = (distribution_name or "").strip()
        if not distribution_name:
            return []
        return sorted(
            module_name
            for module_name, add_on in self._runtime_add_ons.items()
            if getattr(add_on, "_ephyr_distribution_name", None) == distribution_name
        )

    @user_session_modification
    def set_add_on_view_enabled(self, module_name: str, enabled: bool):
        setup = self._session_manager.current_user_session.gui_setup.add_ons.get(module_name)
        if setup is None:
            return
        setup.view_enabled = bool(enabled)
        self.add_ons_changed.emit(dict(self._session_manager.current_user_session.gui_setup.add_ons))

    @user_session_modification
    def set_add_on_transform_enabled(self, module_name: str, enabled: bool):
        setup = self._session_manager.current_user_session.gui_setup.add_ons.get(module_name)
        if setup is None:
            return
        setup.transform_enabled = bool(enabled)
        self.add_ons_changed.emit(dict(self._session_manager.current_user_session.gui_setup.add_ons))

    @user_session_modification
    def set_events_shown(self, shown: bool):
        self._session_manager.current_user_session.gui_setup.events_are_shown = shown
        self.events_are_shown_changed.emit(shown)

    @user_session_modification
    def set_periods_shown(self, shown: bool):
        self._session_manager.current_user_session.gui_setup.periods_are_shown = shown
        self.periods_are_shown_changed.emit(shown)

    @user_session_modification
    def set_cut_traces(self, group_idx: int, cut_traces: bool):
        session = self._session_manager.current_user_session
        if not session:
            return
        groups = session.gui_setup.channels_groups
        if not (0 <= group_idx < len(groups)):
            return
        cut_traces = bool(cut_traces)
        if groups[group_idx].cut_traces != cut_traces:
            groups[group_idx].cut_traces = cut_traces
            self.cut_traces_changed.emit(cut_traces)

    @user_session_modification
    def set_start_point(self, start_point: int) -> bool:
        visible_points = 0
        if self.gui_setup and self.source_view and self.source_view.sample_rate > 0:
            visible_points = int((self.gui_setup.duration_ms / 1000.0) * self.source_view.sample_rate)
        max_start_point = max(0, self._current_segment_points - max(0, visible_points))
        start_point = min(start_point, max_start_point)
        start_point = max(0, start_point)
        if self._session_manager.current_user_session.gui_setup.start_point != start_point:
            self._session_manager.current_user_session.gui_setup.start_point = start_point
            self.start_point_changed.emit(start_point)
            return True
        
        return False

    @user_session_modification
    def set_duration_ms(self, duration_ms: int):
        duration_ms = int(min(duration_ms, self._current_segment_duration_ms))
        duration_ms = max(1, duration_ms)
        if self._session_manager.current_user_session.gui_setup.duration_ms != duration_ms: 
            self._session_manager.current_user_session.gui_setup.duration_ms = duration_ms
            self.duration_ms_changed.emit(duration_ms)
            return True
        
        return False

    def set_time_step_ms(self, time_step_ms: int):
        self._write_time_step_ms(time_step_ms, mark_modified=True)

    def set_beginner_time_step_ms(self, time_step_ms: int):
        """Apply the Beginner-mode timebar step without marking the session unsaved."""
        self._write_time_step_ms(time_step_ms, mark_modified=False)

    def _write_time_step_ms(self, time_step_ms: int, mark_modified: bool):
        session = self._session_manager.current_user_session
        if session is None:
            return
        time_step_ms = max(settings.MIN_TIME_STEP, int(time_step_ms))
        if int(session.gui_setup.time_step_ms) == time_step_ms:
            return
        if mark_modified:
            session.changes_saved = False
        session.gui_setup.time_step_ms = time_step_ms
        self.time_step_ms_changed.emit(time_step_ms)

    @user_session_modification
    def set_autoscroll_step_interval_ms(self, interval_ms: int):
        interval_ms = max(10, int(interval_ms))
        self._session_manager.current_user_session.gui_setup.autoscroll_step_interval_ms = interval_ms
        self.autoscroll_step_interval_ms_changed.emit(interval_ms)

    @user_session_modification
    def set_number_of_dots_to_display(self, number_of_dots_to_display: int):
        self._session_manager.current_user_session.gui_setup.number_of_dots_to_display = number_of_dots_to_display
        self.number_of_dots_to_display_changed.emit(number_of_dots_to_display)

    @user_session_modification
    def set_current_segment_idx(self, segment_idx: int):
        view = self.source_view
        if not view:
            return
        segment_idx = max(0, min(int(segment_idx), view.number_of_segments - 1))
        self._session_manager.current_user_session.gui_setup.current_segment_idx = segment_idx
        self.set_start_point(self.gui_setup.start_point)
        self.set_duration_ms(self.gui_setup.duration_ms)
        self.current_segment_idx_changed.emit(segment_idx)

    @property
    def overlay_segment_idxs(self) -> List[int]:
        if self.gui_setup:
            return list(self.gui_setup.overlay_segment_idxs)
        return []

    @user_session_modification
    def set_overlay_segment_idxs(self, segment_idxs: List[int]):
        view = self.source_view
        if not view:
            return
        normalized = sorted({
            int(segment_idx) for segment_idx in (segment_idxs or [])
            if 0 <= int(segment_idx) < view.number_of_segments
        })
        if self.gui_setup.overlay_segment_idxs == normalized:
            return
        self._session_manager.current_user_session.gui_setup.overlay_segment_idxs = normalized
        ephyr_logger().info(
            f"Overlay segments set to {[idx + 1 for idx in normalized]}" if normalized
            else "Overlay segments disabled"
        )
        self.overlay_segment_idxs_changed.emit(normalized)

    # ---- Navigation over segments ----
    @property
    def current_segment_idx(self) -> int:
        return int(self.gui_setup.current_segment_idx) if self.gui_setup else 0

    def time_of_local_ms(self, local_ms: float, segment_idx: Optional[int] = None) -> Optional[float]:
        """Record time (ms) of a position inside a display segment (the current one by default)."""
        view = self.source_view
        if view is None or view.number_of_segments == 0:
            return None
        idx = self.current_segment_idx if segment_idx is None else int(segment_idx)
        return view.time_of_local_ms(idx, float(local_ms))

    def local_ms_of_time(self, t_ms: float, segment_idx: Optional[int] = None,
                         snap: Optional[str] = None) -> Optional[float]:
        """Position of Record time inside a display segment, None when it is not shown there."""
        view = self.source_view
        if view is None:
            return None
        idx = self.current_segment_idx if segment_idx is None else int(segment_idx)
        return view.local_ms_of_time(idx, float(t_ms), snap=snap)

    def _apply_display_segments(self):
        self._session_manager.rebuild_display_segments()
        if self.gui_setup is not None:
            self.set_start_point(self.gui_setup.start_point)
            self.set_duration_ms(self.gui_setup.duration_ms)
        self.display_segments_changed.emit()
        if self.gui_setup is not None:
            self.current_segment_idx_changed.emit(self.gui_setup.current_segment_idx)
            self.overlay_segment_idxs_changed.emit(list(self.gui_setup.overlay_segment_idxs))

    def _on_periods_changed(self, _periods):
        gui_setup = self.gui_setup
        if gui_setup is not None and gui_setup.navigation_mode is NavigationModeEnum.PERIOD_LABEL:
            self._apply_display_segments()

    @user_session_modification
    def set_navigation(self, mode: NavigationModeEnum, *, period_label_id: Optional[int] = None,
                       pre_ms: Optional[float] = None, post_ms: Optional[float] = None):
        gui_setup = self.gui_setup
        mode = NavigationModeEnum(mode)
        changed = gui_setup.navigation_mode is not mode
        gui_setup.navigation_mode = mode
        if period_label_id is not None and period_label_id != gui_setup.period_label_id:
            gui_setup.period_label_id = int(period_label_id)
            changed = True
        if pre_ms is not None and float(pre_ms) != gui_setup.pre_ms:
            gui_setup.pre_ms = max(0.0, float(pre_ms))
            changed = True
        if post_ms is not None and float(post_ms) != gui_setup.post_ms:
            gui_setup.post_ms = max(0.0, float(post_ms))
            changed = True
        if not changed:
            return
        gui_setup.current_segment_idx = 0
        gui_setup.overlay_segment_idxs = []
        gui_setup.start_point = 0
        ephyr_logger().info(f"Navigation mode: {mode.value}")
        self._apply_display_segments()

    @property
    def active_source_id(self) -> Optional[str]:
        view = self.source_view
        return view.source_id if view is not None else None

    def available_source_ids(self) -> List[str]:
        return self._session_manager.available_source_ids()

    @user_session_modification
    def set_active_source(self, source_id: str):
        if source_id == self.active_source_id:
            return
        self._session_manager.switch_source(source_id)
        ephyr_logger().info(f"Active source: {source_id}")
        self.refresh_runtime_add_ons()
        self.active_source_changed.emit(source_id)
        self.session_loaded.emit()

    @user_session_modification
    def set_channels_groups(self, groups: List[ChannelGroup]):
        session = self._session_manager.current_user_session
        if not session:
            return
        session.gui_setup.channels_groups = [group.model_copy(deep=True) for group in groups]
        self.channels_groups_changed.emit(session.gui_setup.channels_groups)

    @user_session_modification
    def set_channel_setup(
            self,
            channel_idx: int,
            *,
            scale: float,
            y_offset: float,
            color: str,
            info: Optional[str] = None,
    ):
        session = self._session_manager.current_user_session
        view = self.source_view
        if not session or not view:
            return
        session.set_channel_setup(
            channel_idx=channel_idx,
            scale=scale,
            y_offset=y_offset,
            color=color,
            info=info,
            number_of_channels=view.number_of_channels,
        )
        self.channel_setup_changed.emit()

    @user_session_modification
    def set_channels_setup(
            self,
            channel_indexes: List[int],
            *,
            scale: float,
            y_offset: float,
            color: str,
            info: Optional[str] = None,
    ):
        session = self._session_manager.current_user_session
        view = self.source_view
        if not session or not view:
            return
        session.set_channels_setup(
            channel_indexes=channel_indexes,
            scale=scale,
            y_offset=y_offset,
            color=color,
            info=info,
            number_of_channels=view.number_of_channels,
        )
        self.channel_setup_changed.emit()

    def set_channel_units(self, channel_indexes: List[int], unit: str) -> bool:
        """Relabel channels of the active source with a new unit in the Config of the Record.

        Stored samples and their numeric values stay unchanged; the label applies to every Record of the Config.
        """
        view = self.source_view
        manager = self._session_manager
        if view is None or not channel_indexes or manager.config is None:
            return False

        target_unit = canonical_unit_label(unit)
        config = manager.config
        spec = config.source(view.source_id)
        changed = False
        for channel_idx in channel_indexes:
            channel_idx = int(channel_idx)
            if not (0 <= channel_idx < view.number_of_channels):
                continue
            if spec.signature.channels[channel_idx].units != target_unit:
                spec.signature.channels[channel_idx].units = target_unit
                view.channel_info.units[channel_idx] = target_unit
                changed = True

        if not changed:
            return False

        manager.workspace.save_config(config)
        self.channel_units_changed.emit(list(view.channel_info.units))
        return True

    @user_session_modification
    def remove_channel_group(self, group_idx: int) -> bool:
        session = self._session_manager.current_user_session
        if not session:
            return False
        groups = session.gui_setup.channels_groups
        if not (0 <= group_idx < len(groups)):
            return False
        if groups[group_idx].channel_indexes:
            return False
        del groups[group_idx]
        self.channels_groups_changed.emit(groups)
        return True

    @user_session_modification
    def add_channel_group(self, name: str = "New group") -> int:
        session = self._session_manager.current_user_session
        if not session:
            return -1
        group = ChannelGroup(
            name=name.strip() or "New group",
            channel_indexes=[],
            enabled_indexes=set(),
            filters=ensure_filters_list([]),
            channels_layout=ChannelsLayout(rows_num_to_show=settings.DEFAULT_VISIBLE_CHANNELS_NUM),
        )
        session.gui_setup.channels_groups.append(group)
        self.channels_groups_changed.emit(session.gui_setup.channels_groups)
        return len(session.gui_setup.channels_groups) - 1

    @user_session_modification
    def set_channel_group_field(self, group_idx: int, **kwargs):
        session = self._session_manager.current_user_session
        if not session:
            return
        groups = session.gui_setup.channels_groups
        if not (0 <= group_idx < len(groups)):
            return
        group = groups[group_idx]
        for key, value in kwargs.items():
            if hasattr(group, key):
                setattr(group, key, value)
        self.channels_groups_changed.emit(groups)

    @user_session_modification
    def set_channel_group_filters(self, group_idx: int, filters: list):
        session = self._session_manager.current_user_session
        if not session:
            return
        groups = session.gui_setup.channels_groups
        if not (0 <= group_idx < len(groups)):
            return
        groups[group_idx].filters = list(filters or [])
        self.filters_changed.emit()

    @user_session_modification
    def move_channels_to_group(self, channel_indexes: List[int], target_group_idx: int):
        session = self._session_manager.current_user_session
        if not session:
            return
        groups = session.gui_setup.channels_groups
        if not (0 <= target_group_idx < len(groups)):
            return
        moved = set(channel_indexes)
        if not moved:
            return
        source_group_names = sorted({
            group.name for group in groups if any(idx in moved for idx in group.channel_indexes)
        })
        for group in groups:
            had_channels = any(idx in moved for idx in group.channel_indexes)
            group.channel_indexes = [idx for idx in group.channel_indexes if idx not in moved]
            group.enabled_indexes = {idx for idx in group.enabled_indexes if idx not in moved}
            if had_channels:
                self._reset_group_channels_layout(group)
        target = groups[target_group_idx]
        ephyr_logger().info(
            f"Channels {sorted(moved)} moved from group(s) {source_group_names or ['none']} "
            f"to group #{target_group_idx} '{target.name}'"
        )
        for idx in channel_indexes:
            if idx not in target.channel_indexes:
                target.channel_indexes.append(idx)
            target.enabled_indexes.add(idx)
        self._reset_group_channels_layout(target)
        self.channels_groups_changed.emit(groups)

    @staticmethod
    def _reset_group_channels_layout(group: ChannelGroup):
        """Reset layout and visible rows after a group's channel membership changes."""
        group.channels_layout.enable_custom_layout = False
        group.channels_layout.layout_table = None
        group.channels_layout.rows_num_to_show = settings.DEFAULT_VISIBLE_CHANNELS_NUM
        group.clamp_layout()

    @user_session_modification
    def set_channels_layout(self, group_idx: int, channels_layout: ChannelsLayout):
        session = self._session_manager.current_user_session
        if not session:
            return
        groups = session.gui_setup.channels_groups
        if not (0 <= group_idx < len(groups)):
            return
        groups[group_idx].channels_layout = channels_layout.model_copy(deep=True)
        groups[group_idx].clamp_layout()
        self.channels_groups_changed.emit(groups)

    @user_session_modification
    def set_group_layouts(self, group_layouts: List[GroupLayout]):
        """Apply a GroupLayout for every group (index-aligned)."""
        session = self._session_manager.current_user_session
        if not session:
            return
        groups = session.gui_setup.channels_groups
        for group, group_layout in zip(groups, group_layouts):
            group.group_layout = group_layout.model_copy(deep=True)
        self.channels_groups_changed.emit(groups)

    @user_session_modification
    def set_group_cur_position(self, group_idx: int, *, cur_row_idx: int, cur_column_idx: int):
        """Lightweight navigation update for the per-group minimap."""
        session = self._session_manager.current_user_session
        if not session:
            return
        groups = session.gui_setup.channels_groups
        if not (0 <= group_idx < len(groups)):
            return
        layout = groups[group_idx].channels_layout
        layout.cur_row_idx = int(cur_row_idx)
        layout.cur_column_idx = int(cur_column_idx)
        groups[group_idx].clamp_layout()
        self.channels_groups_changed.emit(groups)

    @user_session_modification
    def set_experiment_description(self, experiment_description: str):
        self._session_manager.current_user_session.experiment_description = experiment_description
        self.experiment_description_changed.emit(experiment_description)

    @user_session_modification
    def set_visual_attachment(self, visual_attachment: str):
        self._session_manager.current_user_session.gui_setup.visual_attachment = visual_attachment
        self.visual_attachment_changed.emit(visual_attachment)

    @user_session_modification
    def add_event_vocabulary(self, name: Optional[str] = None) -> int:
        """Add a new event vocabulary entry (with undo support)."""
        cmd = AddEventVocabularyCommand(name)
        self._execute_new_command(cmd)
        # Return the newly added ID (command stores it after execution)
        added_id = cmd.get_added_id()
        if added_id is not None:
            return added_id
        # Fallback: get max ID from current vocabulary
        return max(self.events_vocabulary.keys(), default=-1)

    @user_session_modification
    def set_event_vocabulary_name(self, event_vocabulary_id: int, name: str):
        """Rename an event vocabulary entry (with undo support)."""
        cmd = SetEventVocabularyNameCommand(event_vocabulary_id, name)
        self._execute_new_command(cmd)

    @user_session_modification
    def set_event_vocabulary_color(self, event_vocabulary_id: int, color: str):
        cmd = SetEventVocabularyColorCommand(event_vocabulary_id, color)
        self._execute_new_command(cmd)

    @user_session_modification
    def set_event_vocabulary_visibility(self, event_vocabulary_id: int, is_visible: bool):
        cmd = SetEventVocabularyVisibilityCommand(event_vocabulary_id, is_visible)
        self._execute_new_command(cmd)

    @user_session_modification
    def remove_event_vocabulary(self, event_vocabulary_id: int):
        """Remove an event vocabulary entry (with undo support)."""
        cmd = RemoveEventVocabularyCommand(event_vocabulary_id)
        self._execute_new_command(cmd)

    # ---- Periods vocabulary helpers ----
    @user_session_modification
    def add_period_vocabulary(self, name: Optional[str] = None) -> int:
        """Add a new period vocabulary entry (with undo support)."""
        cmd = AddPeriodVocabularyCommand(name)
        self._execute_new_command(cmd)
        # Return the newly added ID (command stores it after execution)
        added_id = cmd.get_added_id()
        if added_id is not None:
            return added_id
        # Fallback: get max ID from current vocabulary
        return max(self.periods_vocabulary.keys(), default=-1)

    @user_session_modification
    def set_period_vocabulary_name(self, period_vocabulary_id: int, name: str):
        """Rename an period vocabulary entry (with undo support)."""
        cmd = SetPeriodVocabularyNameCommand(period_vocabulary_id, name)
        self._execute_new_command(cmd)

    @user_session_modification
    def set_period_vocabulary_color(self, period_vocabulary_id: int, color: str):
        cmd = SetPeriodVocabularyColorCommand(period_vocabulary_id, color)
        self._execute_new_command(cmd)

    @user_session_modification
    def set_period_vocabulary_visibility(self, period_vocabulary_id: int, is_visible: bool):
        cmd = SetPeriodVocabularyVisibilityCommand(period_vocabulary_id, is_visible)
        self._execute_new_command(cmd)

    @user_session_modification
    def remove_period_vocabulary(self, period_vocabulary_id: int):
        """Remove an period vocabulary entry (with undo support)."""
        cmd = RemovePeriodVocabularyCommand(period_vocabulary_id)
        self._execute_new_command(cmd)

    # ---- Events helpers ----
    def _event_name(self, event_name_id: int) -> str:
        session = self._session_manager.current_user_session
        if not session:
            return str(event_name_id)
        return session.get_event_vocabulary_name(event_name_id) or str(event_name_id)

    def _period_name(self, period_name_id: int) -> str:
        session = self._session_manager.current_user_session
        if not session:
            return str(period_name_id)
        return session.get_period_vocabulary_name(period_name_id) or str(period_name_id)

    def _event_names_summary(self, events: List[Event]) -> str:
        counts: Dict[str, int] = {}
        for event in events:
            name = self._event_name(event.event_name_id)
            counts[name] = counts.get(name, 0) + 1
        return ", ".join(f"{name} x{count}" for name, count in sorted(counts.items()))

    @user_session_modification
    def add_event(self, event_name_id: int, t_ms: float):
        """Create a new event at Record time `t_ms` in the current user session (with undo support)."""
        cmd = AddEventCommand(event_name_id, t_ms)
        self._execute_new_command(cmd)
        ephyr_logger().info(
            f"Event '{self._event_name(event_name_id)}' added: t_ms={t_ms:.3f} is_bad=False"
        )

    @user_session_modification
    def add_events(self, events_specs: List[Tuple[int, float]]):
        """Create multiple events in the current user session (with undo support).

        events_specs: list of (event_name_id, t_ms)
        """
        if not events_specs:
            return
        cmd = AddEventsCommand(events_specs)
        self._execute_new_command(cmd)
        for event_name_id, t_ms in events_specs:
            ephyr_logger().info(
                f"Event '{self._event_name(event_name_id)}' added: t_ms={t_ms:.3f} is_bad=False"
            )

    @user_session_modification
    def remove_events(self, events: List[Event]):
        if not events:
            return

        cmd = RemoveEventsCommand(events)
        self._execute_new_command(cmd)
        ephyr_logger().info(f"Events removed: {self._event_names_summary(events)}")

    @user_session_modification
    def set_events_bad_flag(self, events: List[Event], is_bad: bool):
        if not events:
            return

        cmd = SetEventsBadFlagCommand(events, is_bad)
        self._execute_new_command(cmd)
        ephyr_logger().info(
            f"Events marked as is_bad={is_bad}: {self._event_names_summary(events)}"
        )

    @user_session_modification
    def import_vocabulary_and_events(
        self,
        imported_vocabulary: Dict[int, EventVocabularyEntry],
        imported_events: List[Event],
    ):
        cmd = ImportVocabularyAndEventsCommand(imported_vocabulary, imported_events)
        self._execute_new_command(cmd)

    # ---- Periods helpers ----
    @user_session_modification
    def add_period(self, period_name_id: int, start_t_ms: float, end_t_ms: float):
        """Create a new period in Record time in the current user session (with undo support)."""
        cmd = AddPeriodCommand(period_name_id, start_t_ms, end_t_ms)
        self._execute_new_command(cmd)
        ephyr_logger().info(
            f"Period '{self._period_name(period_name_id)}' added: "
            f"start_t_ms={start_t_ms:.3f} end_t_ms={end_t_ms:.3f}"
        )

    @user_session_modification
    def remove_periods(self, periods: List[Period]):
        if not periods:
            return

        cmd = RemovePeriodsCommand(periods)
        self._execute_new_command(cmd)

    @user_session_modification
    def import_vocabulary_and_periods(
        self,
        imported_vocabulary: Dict[int, PeriodVocabularyEntry],
        imported_periods: List[Period],
    ):
        cmd = ImportVocabularyAndPeriodsCommand(imported_vocabulary, imported_periods)
        self._execute_new_command(cmd)

    @user_session_modification
    def replace_gui_setup(self, gui_setup: GuiSetup):
        session = self._session_manager.current_user_session
        session.gui_setup = gui_setup.model_copy(deep=True)
        source_id = session.gui_setup.active_source_id
        if source_id not in self.available_source_ids():
            source_id = self._session_manager.config.main_source_id
            session.gui_setup.active_source_id = source_id
        self._session_manager.load_source(source_id)
        self._session_manager.rebuild_display_segments()
        self.set_start_point(session.gui_setup.start_point)
        self.set_duration_ms(session.gui_setup.duration_ms)
        self.refresh_runtime_add_ons()
        self.session_loaded.emit()

    @user_session_modification
    def import_settings_from_session(self, other: UserSession, include_vocabularies: bool = True):
        """GUI settings of a session of another Record of the same Config, optionally with its vocabularies."""
        session = self._session_manager.current_user_session
        period_map: Dict[int, int] = {}
        if include_vocabularies:
            _event_map, period_map = session.merge_vocabularies(other)
            self.events_vocabulary_changed.emit(dict(session.events_vocabulary))
            self.periods_vocabulary_changed.emit(dict(session.periods_vocabulary))
        new_setup = other.gui_setup.transferable_copy(session.gui_setup)
        label_id = other.gui_setup.period_label_id
        if label_id is not None:
            if label_id in period_map:
                new_setup.period_label_id = period_map[label_id]
            else:
                name = other.get_period_vocabulary_name(label_id)
                new_setup.period_label_id = next(
                    (vid for vid, entry in session.periods_vocabulary.items() if entry.name == name), None
                )
        if new_setup.navigation_mode is NavigationModeEnum.PERIOD_LABEL and new_setup.period_label_id is None:
            new_setup.navigation_mode = NavigationModeEnum.SEGMENT
        ephyr_logger().info(f"GUI settings imported from session '{other.session_name}'")
        self.replace_gui_setup(new_setup)

    # ---- Undo / Redo API ----
    def can_undo(self) -> bool:
        """Check if undo is available."""
        return bool(self._undo_stack)

    def can_redo(self) -> bool:
        """Check if redo is available."""
        return bool(self._redo_stack)

    def undo(self) -> Optional[str]:
        """Undo last command. Returns short description for status bar."""
        if not self._undo_stack:
            return None

        cmd = self._undo_stack.pop()
        cmd.undo(self)
        self._redo_stack.append(cmd)
        # Limit redo stack size
        if len(self._redo_stack) > settings.MAX_UNDO_HISTORY_SIZE:
            self._redo_stack.pop(0)

        # Mark session modified if present
        if self._session_manager.current_user_session:
            self._session_manager.current_user_session.changes_saved = False

        return f"Undo: {cmd.description}"

    def redo(self) -> Optional[str]:
        """Redo last undone command. Returns short description for status bar."""
        if not self._redo_stack:
            return None

        cmd = self._redo_stack.pop()
        cmd.do(self)
        self._undo_stack.append(cmd)
        # Limit undo stack size
        if len(self._undo_stack) > settings.MAX_UNDO_HISTORY_SIZE:
            self._undo_stack.pop(0)

        # Mark session modified if present
        if self._session_manager.current_user_session:
            self._session_manager.current_user_session.changes_saved = False

        return f"Redo: {cmd.description}"

    # Session management methods
    def new_user_session(self, session_name: str):
        self._session_manager.new_user_session(session_name)
        self._sync_logging_context()
        self._clear_undo_redo_history()
        self.refresh_runtime_add_ons()
        self.session_loaded.emit()

    def export_current_session(self, destination_path):
        return self._session_manager.export_current_session(destination_path)

    def import_new_session(self, session_to_import):
        self._session_manager.import_new_session(session_to_import)
        self._clear_undo_redo_history()
        self.refresh_runtime_add_ons()
        self.session_loaded.emit()

    def switch_sessions(self, session_name: str):
        try:
            self._session_manager.switch_sessions(session_name)
        finally:
            self._sync_logging_context()
        self._clear_undo_redo_history()
        self.refresh_runtime_add_ons()
        self.session_loaded.emit()

    def save_user_session(self):
        self._session_manager.save_user_session()
        if self._session_manager.current_user_session:
            self._session_manager.current_user_session.changes_saved = True
        self.session_saved.emit()

    def open_record(self, workspace: Workspace, config_id: str, record_id: str,
                    original_source_path: Optional[Path] = None):
        try:
            self._session_manager.open_record(workspace, config_id, record_id)
            self._original_source_path = original_source_path
        finally:
            self._sync_logging_context()
        self._clear_undo_redo_history()

    def close_record(self):
        self._original_source_path = None
        self._session_manager.close_record()
        self._sync_logging_context()
        self._clear_undo_redo_history()

    def _sync_logging_context(self) -> None:
        session = self._session_manager.current_user_session
        set_log_session_name(session.session_name if session else None)
        set_log_record(self._session_manager.record_dir)

    def session_name_already_exists(self, session_name: str):
        return self._session_manager.session_name_already_exists(session_name)

    # Property forwarding
    @property
    def session_is_active(self):
        return self._session_manager.session_is_active

    @property
    def other_session_names(self) -> List[str]:
        return self._session_manager.other_session_names

    @property
    def user_session(self):
        return self._session_manager.user_session

    @property
    def record_data(self):
        return self._session_manager.record_data

    @property
    def workspace(self) -> Optional[Workspace]:
        return self._session_manager.workspace

    @property
    def config(self):
        return self._session_manager.config

    @property
    def record(self):
        return self._session_manager.record

    @property
    def config_id(self) -> Optional[str]:
        return self._session_manager.config_id

    @property
    def record_id(self) -> Optional[str]:
        return self._session_manager.record_id

    @property
    def record_dir(self) -> Optional[Path]:
        return self._session_manager.record_dir

    @property
    def original_source_path(self) -> Optional[Path]:
        """Last known location of the Record's original recording on this machine (not stored in the workspace)."""
        return self._original_source_path

    @property
    def sessions_folder(self) -> Optional[Path]:
        return self._session_manager.sessions_folder if self._session_manager.record_dir else None

    @property
    def add_ons_data_folder(self) -> Optional[Path]:
        return self._session_manager.add_ons_data_folder if self._session_manager.record_dir else None

    @property
    def _current_segment_points(self) -> int:
        view = self.source_view
        if not view or not self.gui_setup or view.number_of_segments == 0:
            return 0
        idx = max(0, min(int(self.gui_setup.current_segment_idx), view.number_of_segments - 1))
        return int(view.display_segments[idx].number_of_samples)

    @property
    def _current_segment_duration_ms(self) -> float:
        view = self.source_view
        if not view:
            return 0.0
        return self._current_segment_points * 1000.0 / view.sample_rate

    def _execute_new_command(self, cmd: BaseCommand) -> None:
        cmd.do(self)
        self._undo_stack.append(cmd)
        if len(self._undo_stack) > settings.MAX_UNDO_HISTORY_SIZE:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def _clear_undo_redo_history(self) -> None:
        self._undo_stack.clear()
        self._redo_stack.clear()
