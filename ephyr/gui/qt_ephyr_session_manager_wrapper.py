# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

import json
from PyQt6.QtCore import QObject, pyqtSignal
from typing import List, Optional, Dict, Tuple
from pathlib import Path

from ephyr.core.add_ons.utils import load_installed_add_ons, load_dev_add_ons
from ephyr import settings
from ephyr.core.conversions.filters import ensure_filters_list

from ephyr.core.header import Header, VoltageUnitEnum
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

from ephyr.gui.commands.base import BaseCommand
from ephyr.gui.commands.events import (
    AddEventCommand,
    AddEventsCommand,
    RemoveEventsCommand,
    SetEventsBadFlagCommand,
    AddEventVocabularyCommand,
    SetEventVocabularyNameCommand,
    SetEventVocabularyColorCommand,
    RemoveEventVocabularyCommand,
    ImportVocabularyAndEventsCommand,
)
from ephyr.gui.commands.periods import (
    AddPeriodCommand,
    RemovePeriodsCommand,
    AddPeriodVocabularyCommand,
    SetPeriodVocabularyNameCommand,
    SetPeriodVocabularyColorCommand,
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
    events_are_shown_changed = pyqtSignal(bool)
    periods_are_shown_changed = pyqtSignal(bool)
    cut_traces_changed = pyqtSignal(bool)

    # Signals for numerical parameters
    start_point_changed = pyqtSignal(int)
    duration_ms_changed = pyqtSignal(int)
    time_step_ms_changed = pyqtSignal(int)
    autoscroll_step_interval_ms_changed = pyqtSignal(int)
    number_of_dots_to_display_changed = pyqtSignal(int)
    current_sweep_idx_changed = pyqtSignal(int)

    # Signals for strings
    experiment_description_changed = pyqtSignal(str)
    channels_mapping_img_changed = pyqtSignal(str)

    # Signals for channel groups and channels setup
    channels_groups_changed = pyqtSignal(list)
    channel_setup_changed = pyqtSignal()
    header_units_changed = pyqtSignal(list)

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
        self._undo_stack: List[BaseCommand] = []
        self._redo_stack: List[BaseCommand] = []
        self._runtime_add_ons: Dict[str, BaseAddOn] = {}

    @property
    def header(self) -> Optional[Header]:
        """Get current GUI setup"""
        if self._session_manager.experiment_data:
            return self._session_manager.experiment_data.header

        return None

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
        if not self._session_manager.current_user_session or not self._session_manager.ephyr_experiment_folder:
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
        if self.gui_setup and self.header and self.header.sample_rate > 0:
            visible_points = int((self.gui_setup.duration_ms / 1000.0) * self.header.sample_rate)
        max_start_point = max(0, self._current_sweep_points - max(0, visible_points))
        start_point = min(start_point, max_start_point)
        start_point = max(0, start_point)
        if self._session_manager.current_user_session.gui_setup.start_point != start_point:
            self._session_manager.current_user_session.gui_setup.start_point = start_point
            self.start_point_changed.emit(start_point)
            return True
        
        return False

    @user_session_modification
    def set_duration_ms(self, duration_ms: int):
        duration_ms = int(min(duration_ms, self._current_sweep_duration_ms))
        duration_ms = max(1, duration_ms)
        if self._session_manager.current_user_session.gui_setup.duration_ms != duration_ms: 
            self._session_manager.current_user_session.gui_setup.duration_ms = duration_ms
            self.duration_ms_changed.emit(duration_ms)
            return True
        
        return False

    @user_session_modification
    def set_time_step_ms(self, time_step_ms: int):
        self._session_manager.current_user_session.gui_setup.time_step_ms = time_step_ms
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
    def set_current_sweep_idx(self, sweep_idx: int):
        if not self.header:
            return
        sweep_idx = max(0, min(int(sweep_idx), self.header.number_of_sweeps - 1))
        self._session_manager.current_user_session.gui_setup.current_sweep_idx = sweep_idx
        self.set_start_point(self.gui_setup.start_point)
        self.set_duration_ms(self.gui_setup.duration_ms)
        self.current_sweep_idx_changed.emit(sweep_idx)

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
        header = self.header
        if not session or not header:
            return
        session.set_channel_setup(
            channel_idx=channel_idx,
            scale=scale,
            y_offset=y_offset,
            color=color,
            info=info,
            header=header,
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
        header = self.header
        if not session or not header:
            return
        session.set_channels_setup(
            channel_indexes=channel_indexes,
            scale=scale,
            y_offset=y_offset,
            color=color,
            info=info,
            header=header,
        )
        self.channel_setup_changed.emit()

    def set_header_channel_units(self, channel_indexes: List[int], unit: VoltageUnitEnum) -> bool:
        header = self.header
        if header is None or not channel_indexes:
            return False

        target_unit = VoltageUnitEnum.normalize(unit.value if isinstance(unit, VoltageUnitEnum) else str(unit)).value
        units = list(header.channel_info.units or [])
        if len(units) < header.number_of_channels:
            units.extend([VoltageUnitEnum.MICROVOLT.value] * (header.number_of_channels - len(units)))

        changed = False
        for channel_idx in channel_indexes:
            if not (0 <= int(channel_idx) < header.number_of_channels):
                continue
            channel_idx = int(channel_idx)
            if units[channel_idx] != target_unit:
                units[channel_idx] = target_unit
                changed = True

        if not changed:
            return False

        header.channel_info.units = units
        if self._session_manager.ephyr_experiment_folder:
            header_path = Path(self._session_manager.ephyr_experiment_folder) / settings.HEADER_FILENAME
            with open(header_path, "w", encoding="utf-8") as file:
                json.dump(header.model_dump(), file, indent=2)

        self.header_units_changed.emit(list(units))
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
        for group in groups:
            had_channels = any(idx in moved for idx in group.channel_indexes)
            group.channel_indexes = [idx for idx in group.channel_indexes if idx not in moved]
            group.enabled_indexes = {idx for idx in group.enabled_indexes if idx not in moved}
            if had_channels:
                self._reset_group_channels_layout(group)
        target = groups[target_group_idx]
        for idx in channel_indexes:
            if idx not in target.channel_indexes:
                target.channel_indexes.append(idx)
            target.enabled_indexes.add(idx)
        self._reset_group_channels_layout(target)
        self.channels_groups_changed.emit(groups)

    @staticmethod
    def _reset_group_channels_layout(group: ChannelGroup):
        """Drop any custom channel layout so it can never index out of range."""
        group.channels_layout.enable_custom_layout = False
        group.channels_layout.layout_table = None
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
    def set_channels_mapping_img(self, channels_mapping_img: str):
        self._session_manager.current_user_session.gui_setup.channels_mapping_img = channels_mapping_img
        self.channels_mapping_img_changed.emit(channels_mapping_img)

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
    def remove_period_vocabulary(self, period_vocabulary_id: int):
        """Remove an period vocabulary entry (with undo support)."""
        cmd = RemovePeriodVocabularyCommand(period_vocabulary_id)
        self._execute_new_command(cmd)

    # ---- Events helpers ----
    @user_session_modification
    def add_event(self, event_name_id: int, sweep_idx: int, time_ms: float):
        """Create a new event in the current user session (with undo support)."""
        cmd = AddEventCommand(event_name_id, sweep_idx, time_ms)
        self._execute_new_command(cmd)

    @user_session_modification
    def add_events(self, events_specs: List[Tuple[int, int, float]]):
        """Create multiple events in the current user session (with undo support).

        events_specs: list of (event_name_id, sweep_idx, time_ms)
        """
        if not events_specs:
            return
        cmd = AddEventsCommand(events_specs)
        self._execute_new_command(cmd)

    @user_session_modification
    def remove_events(self, events: List[Event]):
        if not events:
            return

        cmd = RemoveEventsCommand(events)
        self._execute_new_command(cmd)

    @user_session_modification
    def set_events_bad_flag(self, events: List[Event], is_bad: bool):
        if not events:
            return

        cmd = SetEventsBadFlagCommand(events, is_bad)
        self._execute_new_command(cmd)

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
    def add_period(self, 
        period_name_id: int,
        start_sweep_idx: int,
        start_time_ms: float,
        end_sweep_idx: int,
        end_time_ms: float,):
        """Create a new period in the current user session (with undo support)."""
        cmd = AddPeriodCommand(period_name_id, start_sweep_idx, start_time_ms, end_sweep_idx, end_time_ms)
        self._execute_new_command(cmd)

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
        self._session_manager.current_user_session.gui_setup = gui_setup.model_copy(deep=True)
        self.session_loaded.emit()

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
    def new_user_session(self, session_filename: str):
        self._session_manager.new_user_session(session_filename)
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

    def switch_sessions(self, session_filename: str):
        self._session_manager.switch_sessions(session_filename)
        self._clear_undo_redo_history()
        self.refresh_runtime_add_ons()
        self.session_loaded.emit()

    def save_user_session(self):
        self._session_manager.save_user_session()
        if self._session_manager.current_user_session:
            self._session_manager.current_user_session.changes_saved = True
        self.session_saved.emit()

    def init_from_folder(self, ephyr_experiment_folder: Path):
        self._session_manager.init_from_folder(ephyr_experiment_folder)
        self._clear_undo_redo_history()

    def session_name_already_exists(self, session_name: str):
        return self._session_manager.session_name_already_exists(session_name)

    def session_filename_already_exists(self, session_filename: str):
        return self._session_manager.session_filename_already_exists(session_filename)

    # Property forwarding
    @property
    def session_is_active(self):
        return self._session_manager.session_is_active

    @property
    def other_session_filenames(self):
        return self._session_manager.other_session_filenames

    @property
    def user_session(self):
        return self._session_manager.user_session

    @property
    def experiment_data(self):
        return self._session_manager.experiment_data

    @property
    def ephyr_experiment_folder(self):
        return self._session_manager.ephyr_experiment_folder

    @property
    def _current_sweep_points(self) -> int:
        if not self.header or not self.gui_setup:
            return 0
        points_per_sweep = list(self.header.number_of_points_per_sweep)
        sweep_idx = max(0, min(int(self.gui_setup.current_sweep_idx), len(points_per_sweep) - 1))
        return int(points_per_sweep[sweep_idx])

    @property
    def _current_sweep_duration_ms(self) -> float:
        if not self.header:
            return 0.0
        return (self.header.sample_interval_microseconds / 10 ** 3) * self._current_sweep_points

    def _execute_new_command(self, cmd: BaseCommand) -> None:
        cmd.do(self)
        self._undo_stack.append(cmd)
        if len(self._undo_stack) > settings.MAX_UNDO_HISTORY_SIZE:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def _clear_undo_redo_history(self) -> None:
        self._undo_stack.clear()
        self._redo_stack.clear()
