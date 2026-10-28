# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

import json
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Optional, List, Dict, Tuple, Set

import numpy as np
from pydantic import BaseModel, Field, model_validator
from ephyr.core.add_ons.base import BaseAddOn, required_sample_rate_for_transformations
from ephyr.logger import ephyr_logger

from ephyr import settings
from ephyr.core import layout
from ephyr.core.annotations_io import (
    EventRow,
    PeriodRow,
    read_events,
    read_periods,
    write_events,
    write_periods,
)
from ephyr.core.conversions.filters import (
    FilterConfig,
    required_sample_rate_for_filters,
    ensure_filters_list,
)
from ephyr.core.exceptions import BrokenSessionFileError, SessionAlreadyExistsError
from ephyr.core.manifests import ConfigManifest, RecordManifest
from ephyr.core.source_view import (
    NavigationModeEnum,
    SourceView,
    continuous_display_segments,
    period_display_segments,
    physical_display_segments,
)
from ephyr.core.workspace import Workspace


class RightPanelWidgetEnum(Enum):
    RECORDING_NAVIGATION = "recording_navigation"
    TIME_SETTINGS = "time_settings"
    CHANNEL_MANAGEMENT = "channel_management"
    INFORMATION = "information"
    LOGS = "logs"
    ANALYSIS = "analysis"
    # Legacy
    SIGNAL_SETTINGS = "signal_settings"

    @staticmethod
    def widgets_order():
        return [
            RightPanelWidgetEnum.RECORDING_NAVIGATION,
            RightPanelWidgetEnum.TIME_SETTINGS,
            RightPanelWidgetEnum.INFORMATION,
            RightPanelWidgetEnum.CHANNEL_MANAGEMENT,
            RightPanelWidgetEnum.ANALYSIS,
            RightPanelWidgetEnum.LOGS,
        ]

    @staticmethod
    def default_widgets():
        return [
            RightPanelWidgetEnum.RECORDING_NAVIGATION,
            RightPanelWidgetEnum.TIME_SETTINGS,
            RightPanelWidgetEnum.INFORMATION,
            RightPanelWidgetEnum.CHANNEL_MANAGEMENT,
            RightPanelWidgetEnum.ANALYSIS,
        ]


class EventsTableFormat(Enum):
    DICT = "dict"
    MARKDOWN = "markdown"


class EventTableRow(BaseModel):
    name: str
    t_ms: float
    segment_idx: Optional[int]
    time_in_segment_ms: Optional[float]
    is_bad: bool
    periods: List[str]


class ChannelSetup(BaseModel):
    scale: float = settings.DEFAULT_SCALE
    y_offset: float = 0.0
    color: str = "#000000"
    info: str = ""


class AddOnSetup(BaseModel):
    view_enabled: bool = False
    transform_enabled: bool = False


class GroupLayout(BaseModel):
    """Placement of a channel group relative to the other groups on screen."""
    layout_row_idx: int = 0
    layout_column_idx: int = 0
    height_ratio: int = 1
    width_ratio: int = 1

    @model_validator(mode="before")
    @classmethod
    def _migrate_float_ratios(cls, value):
        if not isinstance(value, dict):
            return value
        migrated = dict(value)
        for field_name in ("height_ratio", "width_ratio"):
            if field_name in migrated:
                migrated[field_name] = max(1, int(float(migrated[field_name]) + 0.5))
        return migrated


class ChannelsLayout(BaseModel):
    """Grid layout of channels inside a single channel group."""
    columns_num: int = 1
    columns_num_to_show: int = 1
    cur_column_idx: int = 0
    rows_num: Optional[int] = None
    rows_num_to_show: int = settings.DEFAULT_VISIBLE_CHANNELS_NUM
    cur_row_idx: int = 0
    enable_custom_layout: bool = False
    draw_borders: bool = False
    layout_table: Optional[List[List[int]]] = None


class ChannelGroup(BaseModel):
    channel_indexes: List[int]
    enabled_indexes: Set[int]
    filters: List[FilterConfig] = Field(default_factory=lambda: ensure_filters_list([]))
    name: str = "Default"
    is_shown: bool = True
    is_auxiliary: bool = False
    cut_traces: bool = False
    group_layout: GroupLayout = Field(default_factory=GroupLayout)
    channels_layout: ChannelsLayout = Field(default_factory=ChannelsLayout)

    def effective_grid(self) -> Tuple[int, int, List[List[int]]]:
        """Return (rows_num, columns_num, table) of channel indexes (-1 = empty).

        When custom layout is disabled the group is rendered as a single column
        holding every channel (enabled or not), matching the classic view.
        """
        layout = self.channels_layout
        if layout.enable_custom_layout and layout.layout_table:
            table = layout.layout_table
            rows = len(table)
            cols = len(table[0]) if table and table[0] else 0
            return rows, cols, table
        table = [[ch] for ch in self.channel_indexes]
        return len(self.channel_indexes), 1, table

    def grid_dims(self) -> Tuple[int, int]:
        rows, cols, _table = self.effective_grid()
        return rows, cols

    def visible_window(self) -> Tuple[int, int, int, int, int, int]:
        """Return (rows_to_show, cols_to_show, cur_row, cur_col, rows_num, cols_num)."""
        rows_num, cols_num, _table = self.effective_grid()
        layout = self.channels_layout
        rows_to_show = min(max(1, int(layout.rows_num_to_show)), max(1, rows_num))
        cols_to_show = min(max(1, int(layout.columns_num_to_show)), max(1, cols_num))
        cur_row = min(max(0, int(layout.cur_row_idx)), max(0, rows_num - rows_to_show))
        cur_col = min(max(0, int(layout.cur_column_idx)), max(0, cols_num - cols_to_show))
        return rows_to_show, cols_to_show, cur_row, cur_col, rows_num, cols_num

    def visible_cells(self) -> List[Tuple[int, int, int]]:
        """Return (row_offset, col_offset, channel_idx) for the visible window.

        row_offset/col_offset are relative to the top-left of the visible window
        (0..rows_to_show-1 / 0..cols_to_show-1). Empty cells (-1) are skipped.
        """
        rows_num, cols_num, table = self.effective_grid()
        if rows_num == 0 or cols_num == 0:
            return []
        layout = self.channels_layout
        rows_to_show = min(max(1, int(layout.rows_num_to_show)), rows_num)
        cols_to_show = min(max(1, int(layout.columns_num_to_show)), cols_num)
        cur_row = min(max(0, int(layout.cur_row_idx)), max(0, rows_num - rows_to_show))
        cur_col = min(max(0, int(layout.cur_column_idx)), max(0, cols_num - cols_to_show))
        cells: List[Tuple[int, int, int]] = []
        for r_off in range(rows_to_show):
            r = cur_row + r_off
            if r >= rows_num:
                break
            row = table[r]
            for c_off in range(cols_to_show):
                c = cur_col + c_off
                if c >= len(row):
                    continue
                channel_idx = row[c]
                if channel_idx is None or channel_idx < 0:
                    continue
                cells.append((r_off, c_off, channel_idx))
        return cells

    def visible_enabled_channels(self) -> List[int]:
        """Channels that must actually be processed/drawn (enabled and in view)."""
        if self.is_auxiliary:
            return [ch for ch in self.channel_indexes if ch in self.enabled_indexes]
        return [ch for _r, _c, ch in self.visible_cells() if ch in self.enabled_indexes]

    def visible_channels(self) -> List[int]:
        return self.visible_enabled_channels()

    def clamp_layout(self) -> None:
        """Clamp the current window/position fields to the valid grid ranges."""
        rows_num, cols_num, _table = self.effective_grid()
        layout = self.channels_layout
        layout.rows_num_to_show = min(max(1, int(layout.rows_num_to_show)), max(1, rows_num))
        layout.columns_num_to_show = min(max(1, int(layout.columns_num_to_show)), max(1, cols_num))
        layout.cur_row_idx = min(max(0, int(layout.cur_row_idx)),
                                 max(0, rows_num - layout.rows_num_to_show))
        layout.cur_column_idx = min(max(0, int(layout.cur_column_idx)),
                                    max(0, cols_num - layout.columns_num_to_show))


class SourceGuiSetup(BaseModel):
    """Channel groups and per-channel setup of a source that is not the active one."""
    channels_groups: List[ChannelGroup] = Field(default_factory=list)
    channels_setup: Dict[int, ChannelSetup] = Field(default_factory=dict)


# Fields that depend on the data of a particular Record and are never copied between Records.
RECORD_SPECIFIC_GUI_FIELDS = {"current_segment_idx", "overlay_segment_idxs", "start_point"}


class GuiSetup(BaseModel):
    right_panel_widgets: List[RightPanelWidgetEnum] = Field(
        default_factory=lambda: RightPanelWidgetEnum.default_widgets())
    add_ons: Dict[str, AddOnSetup] = Field(default_factory=dict)

    traces_are_shown: bool = True
    channel_names_are_shown: bool = True
    channel_infos_are_shown: bool = True
    events_are_shown: bool = True
    periods_are_shown: bool = True

    active_source_id: Optional[str] = None
    navigation_mode: NavigationModeEnum = NavigationModeEnum.SEGMENT
    period_label_id: Optional[int] = None
    pre_ms: float = 0.0
    post_ms: float = 0.0
    current_segment_idx: int = 0
    overlay_segment_idxs: List[int] = Field(default_factory=list)
    start_point: int = 0
    duration_ms: int = settings.DEFAULT_DURATION
    time_step_ms: int = settings.DEFAULT_TIME_STEP
    autoscroll_step_interval_ms: int = settings.AUTO_SCROLL_STEP_INTERVAL_MS
    number_of_dots_to_display: int = settings.DEFAULT_NUMBER_OF_DOTS_TO_DISPLAY
    channels_groups: List[ChannelGroup] = Field(default_factory=list)
    channels_setup: Dict[int, ChannelSetup] = Field(default_factory=dict)
    other_sources_setup: Dict[str, SourceGuiSetup] = Field(default_factory=dict)
    visual_attachment: str = ""

    class Config:
        arbitrary_types_allowed = True

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_right_panel_widgets(cls, value):
        if not isinstance(value, dict) or "right_panel_widgets" not in value:
            return value

        migrated = dict(value)
        normalized = []
        for widget in value.get("right_panel_widgets") or []:
            raw_value = widget.value if isinstance(widget, RightPanelWidgetEnum) else widget
            replacements = (
                [RightPanelWidgetEnum.TIME_SETTINGS.value, RightPanelWidgetEnum.CHANNEL_MANAGEMENT.value]
                if raw_value == RightPanelWidgetEnum.SIGNAL_SETTINGS.value
                else [raw_value]
            )
            for replacement in replacements:
                if replacement not in normalized:
                    normalized.append(replacement)
        migrated["right_panel_widgets"] = normalized
        return migrated

    def all_non_auxiliary_channel_indexes(self) -> List[int]:
        result: List[int] = []
        for group in self.channels_groups:
            if group.is_auxiliary:
                continue
            result.extend(group.channel_indexes)
        return result

    def transferable_copy(self, target: "GuiSetup") -> "GuiSetup":
        """This setup applied to another Record: positions inside the data are kept from `target`."""
        data = self.model_dump()
        for field_name in RECORD_SPECIFIC_GUI_FIELDS:
            data[field_name] = getattr(target, field_name)
        return GuiSetup.model_validate(data)


def default_source_setup(view: SourceView) -> SourceGuiSetup:
    all_channels = list(range(view.number_of_channels))
    return SourceGuiSetup(
        channels_groups=[
            ChannelGroup(
                name="Default",
                channel_indexes=all_channels,
                enabled_indexes=set(all_channels),
                channels_layout=ChannelsLayout(rows_num_to_show=settings.DEFAULT_VISIBLE_CHANNELS_NUM),
            )
        ],
        channels_setup={idx: ChannelSetup(scale=float(settings.DEFAULT_SCALE)) for idx in all_channels},
    )


class Period(BaseModel):
    """Period in Record time (ms from the Record start)."""
    id: int = 0
    period_name_id: int
    start_t_ms: float
    end_t_ms: float
    source_id: Optional[str] = None
    channel: Optional[int] = None
    value: Optional[str] = None
    extra: Dict[str, str] = Field(default_factory=dict)


class Event(BaseModel):
    """Event in Record time (ms from the Record start)."""
    id: int = 0
    event_name_id: int
    t_ms: float
    is_bad: bool = False
    source_id: Optional[str] = None
    channel: Optional[int] = None
    value: Optional[str] = None
    extra: Dict[str, str] = Field(default_factory=dict)


class EventVocabularyEntry(BaseModel):
    name: str
    color: str = "#0066FF"
    is_visible: bool = True


class PeriodVocabularyEntry(BaseModel):
    name: str
    color: str = "#00AA55"
    is_visible: bool = True


_INVALID_SESSION_NAME_CHARS = set('<>:"/\\|?*')


def is_valid_session_name(name: str) -> bool:
    name = name.strip()
    return bool(name) and name not in {".", ".."} and not (set(name) & _INVALID_SESSION_NAME_CHARS)


class UserSession(BaseModel):
    """A named set of annotations and GUI settings of one Record: sessions/<name>/."""
    session_name: str
    changes_saved: bool = True
    events_vocabulary: Dict[int, EventVocabularyEntry] = Field(default_factory=dict)
    events: List[Event] = Field(default_factory=list)
    periods_vocabulary: Dict[int, PeriodVocabularyEntry] = Field(default_factory=dict)
    periods: List[Period] = Field(default_factory=list)
    experiment_description: str = ""
    gui_setup: GuiSetup = Field(default_factory=GuiSetup)

    class Config:
        arbitrary_types_allowed = True

    # ----- files -----

    def save_session(self, sessions_folder: Path):
        folder = sessions_folder / self.session_name
        folder.mkdir(parents=True, exist_ok=True)
        settings_json = self.model_dump_json(
            exclude={"session_name": True, "changes_saved": True, "events": True, "periods": True}, indent=4
        )
        tmp_path = folder / (settings.SESSION_SETTINGS_FILENAME + ".tmp")
        with open(tmp_path, "w", encoding="utf-8") as dest_file:
            dest_file.write(settings_json)
        os.replace(tmp_path, folder / settings.SESSION_SETTINGS_FILENAME)
        write_events(folder / settings.EVENTS_FILENAME, [
            EventRow(id=event.id, t_ms=event.t_ms, label=self.get_event_vocabulary_name(event.event_name_id),
                     source_id=event.source_id, channel=event.channel, value=event.value, is_bad=event.is_bad,
                     extra=dict(event.extra))
            for event in self.events
        ])
        write_periods(folder / settings.PERIODS_FILENAME, [
            PeriodRow(id=period.id, start_t_ms=period.start_t_ms, end_t_ms=period.end_t_ms,
                      label=self.get_period_vocabulary_name(period.period_name_id), source_id=period.source_id,
                      channel=period.channel, value=period.value, extra=dict(period.extra))
            for period in self.periods
        ])

    @staticmethod
    def is_session_folder(folder: Path) -> bool:
        return (Path(folder) / settings.SESSION_SETTINGS_FILENAME).is_file()

    @staticmethod
    def load(session_folder: Path) -> "UserSession":
        session_folder = Path(session_folder)
        settings_path = session_folder / settings.SESSION_SETTINGS_FILENAME
        try:
            with open(settings_path, "r", encoding="utf-8") as file:
                session_dict = json.load(file)
            session_dict["session_name"] = session_folder.name
            session = UserSession.model_validate(session_dict)
            session.add_event_rows(read_events(session_folder / settings.EVENTS_FILENAME), keep_ids=True)
            session.add_period_rows(read_periods(session_folder / settings.PERIODS_FILENAME), keep_ids=True)
        except Exception:
            raise BrokenSessionFileError(settings_path)
        return session

    # ----- annotations from CSV rows -----

    def _event_vocabulary_id(self, label: str) -> int:
        for vocabulary_id, entry in self.events_vocabulary.items():
            if entry.name == label:
                return vocabulary_id
        return self.add_event_vocabulary(label)

    def _period_vocabulary_id(self, label: str) -> int:
        for vocabulary_id, entry in self.periods_vocabulary.items():
            if entry.name == label:
                return vocabulary_id
        return self.add_period_vocabulary(label)

    def add_event_rows(self, rows: List[EventRow], keep_ids: bool = False) -> List[Event]:
        added = []
        for row in rows:
            event = Event(
                id=row.id if keep_ids else self.next_event_id(),
                event_name_id=self._event_vocabulary_id(row.label or "Event"),
                t_ms=row.t_ms, is_bad=row.is_bad, source_id=row.source_id, channel=row.channel,
                value=row.value, extra=dict(row.extra),
            )
            self.events.append(event)
            added.append(event)
        self.sort_events()
        return added

    def add_period_rows(self, rows: List[PeriodRow], keep_ids: bool = False) -> List[Period]:
        added = []
        for row in rows:
            period = Period(
                id=row.id if keep_ids else self.next_period_id(),
                period_name_id=self._period_vocabulary_id(row.label or "Period"),
                start_t_ms=row.start_t_ms, end_t_ms=row.end_t_ms, source_id=row.source_id,
                channel=row.channel, value=row.value, extra=dict(row.extra),
            )
            self.periods.append(period)
            added.append(period)
        self.sort_periods()
        return added

    # ----- vocabularies -----

    def add_event_vocabulary(self, name: str) -> int:
        next_id = max(self.events_vocabulary.keys(), default=-1) + 1
        event_name = name.strip() if name else f"Event {next_id}"
        self.events_vocabulary[next_id] = EventVocabularyEntry(name=event_name)
        return next_id

    def get_event_vocabulary_name(self, event_vocabulary_id: int) -> str:
        entry = self.events_vocabulary.get(event_vocabulary_id)
        if entry is None:
            return f"Event {event_vocabulary_id}"
        return entry.name

    def get_event_vocabulary_color(self, event_vocabulary_id: int) -> str:
        entry = self.events_vocabulary.get(event_vocabulary_id)
        if entry is None or not entry.color:
            return "#0066FF"
        return entry.color

    def rename_event_vocabulary(self, event_vocabulary_id: int, name: str):
        if event_vocabulary_id not in self.events_vocabulary:
            return

        prev_name = self.get_event_vocabulary_name(event_vocabulary_id)
        new_name = name.strip() or prev_name
        self.events_vocabulary[event_vocabulary_id].name = new_name

    def set_event_vocabulary_color(self, event_vocabulary_id: int, color: str):
        if event_vocabulary_id not in self.events_vocabulary:
            return
        self.events_vocabulary[event_vocabulary_id].color = color.strip() or "#0066FF"

    def set_event_vocabulary_visibility(self, event_vocabulary_id: int, is_visible: bool):
        if event_vocabulary_id not in self.events_vocabulary:
            return
        self.events_vocabulary[event_vocabulary_id].is_visible = bool(is_visible)

    def remove_event_vocabulary(self, event_vocabulary_id: int):
        if event_vocabulary_id not in self.events_vocabulary:
            return

        self.events_vocabulary = {key: value for key, value in self.events_vocabulary.items()
                                  if key != event_vocabulary_id}
        self.clear_events_for_vocabulary_id(event_vocabulary_id)

    def add_period_vocabulary(self, name: str) -> int:
        next_id = max(self.periods_vocabulary.keys(), default=-1) + 1
        period_name = name.strip() if name else f"Period {next_id}"
        self.periods_vocabulary[next_id] = PeriodVocabularyEntry(name=period_name)
        return next_id

    def get_period_vocabulary_name(self, period_vocabulary_id: int) -> str:
        entry = self.periods_vocabulary.get(period_vocabulary_id)
        if entry is None:
            return f"Period {period_vocabulary_id}"
        return entry.name

    def get_period_vocabulary_color(self, period_vocabulary_id: int) -> str:
        entry = self.periods_vocabulary.get(period_vocabulary_id)
        if entry is None or not entry.color:
            return "#00AA55"
        return entry.color

    def rename_period_vocabulary(self, period_vocabulary_id: int, name: str):
        if period_vocabulary_id not in self.periods_vocabulary:
            return

        prev_name = self.get_period_vocabulary_name(period_vocabulary_id)
        new_name = name.strip() or prev_name
        self.periods_vocabulary[period_vocabulary_id].name = new_name

    def set_period_vocabulary_color(self, period_vocabulary_id: int, color: str):
        if period_vocabulary_id not in self.periods_vocabulary:
            return
        self.periods_vocabulary[period_vocabulary_id].color = color.strip() or "#00AA55"

    def set_period_vocabulary_visibility(self, period_vocabulary_id: int, is_visible: bool):
        if period_vocabulary_id not in self.periods_vocabulary:
            return
        self.periods_vocabulary[period_vocabulary_id].is_visible = bool(is_visible)

    def remove_period_vocabulary(self, period_vocabulary_id: int):
        if period_vocabulary_id not in self.periods_vocabulary:
            return

        self.periods_vocabulary = {
            key: value for key, value in self.periods_vocabulary.items()
            if key != period_vocabulary_id
        }
        # Remove periods that reference this vocabulary id
        self.periods = [p for p in self.periods if p.period_name_id != period_vocabulary_id]

    def merge_vocabularies(self, other: "UserSession") -> Tuple[Dict[int, int], Dict[int, int]]:
        """Merge `other` vocabularies by name; returns maps of other ids to ids of this session.

        Matching names take the color of `other`, new names are added, nothing is removed and the ids of
        already annotated events and periods do not change.
        """
        event_map: Dict[int, int] = {}
        for other_id, entry in other.events_vocabulary.items():
            own_id = next((vid for vid, own in self.events_vocabulary.items() if own.name == entry.name), None)
            if own_id is None:
                own_id = self.add_event_vocabulary(entry.name)
            self.events_vocabulary[own_id].color = entry.color
            self.events_vocabulary[own_id].is_visible = entry.is_visible
            event_map[other_id] = own_id
        period_map: Dict[int, int] = {}
        for other_id, entry in other.periods_vocabulary.items():
            own_id = next((vid for vid, own in self.periods_vocabulary.items() if own.name == entry.name), None)
            if own_id is None:
                own_id = self.add_period_vocabulary(entry.name)
            self.periods_vocabulary[own_id].color = entry.color
            self.periods_vocabulary[own_id].is_visible = entry.is_visible
            period_map[other_id] = own_id
        return event_map, period_map

    # ----- events and periods -----

    def next_event_id(self) -> int:
        return max((event.id for event in self.events), default=-1) + 1

    def next_period_id(self) -> int:
        return max((period.id for period in self.periods), default=-1) + 1

    def sort_events(self) -> None:
        self.events.sort(key=lambda event: (event.t_ms, event.id))

    def sort_periods(self) -> None:
        self.periods.sort(key=lambda period: (period.start_t_ms, period.id))

    def add_event(self, event_name_id: int, t_ms: float) -> Event:
        """Add a new event to the session."""
        new_event = Event(id=self.next_event_id(), event_name_id=event_name_id, t_ms=float(t_ms))
        self.events.append(new_event)
        self.sort_events()
        return new_event

    def remove_event(self, event: Event):
        """Remove a specific event instance from the session."""
        self.events = [item for item in self.events if item.id != event.id]

    def event_by_id(self, event_id: int) -> Optional[Event]:
        return next((event for event in self.events if event.id == event_id), None)

    def event_set_bad_flag(self, event: Event, is_bad: bool):
        target = self.event_by_id(event.id)
        if target is not None:
            target.is_bad = is_bad

    def clear_events_for_vocabulary_id(self, event_name_id: int):
        """Remove all events that reference the given vocabulary id."""
        self.events = [e for e in self.events if e.event_name_id != event_name_id]

    def add_period(self, period_name_id: int, start_t_ms: float, end_t_ms: float) -> Period:
        period = Period(
            id=self.next_period_id(),
            period_name_id=period_name_id,
            start_t_ms=float(min(start_t_ms, end_t_ms)),
            end_t_ms=float(max(start_t_ms, end_t_ms)),
        )
        self.periods.append(period)
        self.sort_periods()
        return period

    def remove_period(self, period: Period):
        self.periods = [item for item in self.periods if item.id != period.id]

    def period_by_id(self, period_id: int) -> Optional[Period]:
        return next((period for period in self.periods if period.id == period_id), None)

    def set_channel_setup(
            self,
            channel_idx: int,
            *,
            scale: float,
            y_offset: float,
            color: str,
            info: Optional[str] = None,
            number_of_channels: Optional[int] = None,
    ):
        if number_of_channels is not None and not 0 <= channel_idx < number_of_channels:
            return

        prev = self.gui_setup.channels_setup.get(channel_idx)
        self.gui_setup.channels_setup[channel_idx] = ChannelSetup(
            scale=float(scale),
            y_offset=float(y_offset),
            color=color,
            info=(prev.info if (info is None and prev is not None) else (info or "")),
        )

    def set_channels_setup(
            self,
            channel_indexes: List[int],
            *,
            scale: float,
            y_offset: float,
            color: str,
            info: Optional[str] = None,
            number_of_channels: Optional[int] = None,
    ):
        if number_of_channels is not None:
            channel_indexes = [idx for idx in channel_indexes if 0 <= idx < number_of_channels]
        for channel_idx in channel_indexes:
            prev = self.gui_setup.channels_setup.get(channel_idx)
            self.gui_setup.channels_setup[channel_idx] = ChannelSetup(
                scale=float(scale),
                y_offset=float(y_offset),
                color=color,
                info=(prev.info if (info is None and prev is not None) else (info or "")),
            )

    def events_table(self, source_view: Optional[SourceView] = None) -> List[EventTableRow]:
        result = []
        mapper = source_view.time_mapper if source_view is not None else None
        for event in self.events:
            event_periods = [
                self.get_period_vocabulary_name(period.period_name_id)
                for period in self.periods
                if period.start_t_ms <= event.t_ms <= period.end_t_ms
            ]
            segment_idx = mapper.segment_of_time(event.t_ms) if mapper is not None else None
            time_in_segment = (event.t_ms - mapper.segments[segment_idx].t_start_ms
                               if segment_idx is not None else None)
            result.append(EventTableRow(
                name=self.get_event_vocabulary_name(event.event_name_id),
                t_ms=event.t_ms,
                segment_idx=segment_idx,
                time_in_segment_ms=time_in_segment,
                is_bad=event.is_bad,
                periods=event_periods,
            ))
        return result


class RecordData:
    """Samples of the active source of a Record: one int16 memmap per channel over all segments."""

    def __init__(self, source_view: SourceView, memmaps: Tuple[np.memmap, ...]):
        self.source_view = source_view
        self.memmaps = memmaps

    @classmethod
    def open(cls, record_folder: Path, source_view: SourceView) -> "RecordData":
        total = source_view.total_samples
        memmaps = []
        for channel_idx in range(source_view.number_of_channels):
            path = layout.channel_samples_path(record_folder, source_view.source_id, channel_idx)
            if total == 0:
                memmaps.append(np.zeros(0, dtype="<i2"))
                continue
            memmaps.append(np.memmap(path, dtype="<i2", mode="r", shape=(total,)))
        return cls(source_view, tuple(memmaps))

    def window_samples(self, params: GuiSetup) -> int:
        return int(params.duration_ms * self.source_view.sample_rate / 1000.0)

    def process_data_pipeline(self, params: GuiSetup, segment_idx: int, channel_indexes: List[int],
                              output_number_of_dots: int,
                              transformation_add_ons: Optional[List[BaseAddOn]] = None) -> Dict[
        int, np.ndarray[np.float64]]:
        """
        Process data pipeline using multithreading for each visible channel.
        Returns {channel_idx: array of output_number_of_dots points}.
        """
        per_segment = self.process_data_pipeline_multi_segment(
            params=params,
            segment_indexes=[segment_idx],
            channel_indexes=channel_indexes,
            output_number_of_dots=output_number_of_dots,
            transformation_add_ons=transformation_add_ons,
        )
        return per_segment.get(segment_idx, {})

    def process_data_pipeline_multi_segment(self, params: GuiSetup, segment_indexes: List[int],
                                            channel_indexes: List[int],
                                            output_number_of_dots: int,
                                            transformation_add_ons: Optional[List[BaseAddOn]] = None) -> Dict[
        int, Dict[int, np.ndarray[np.float64]]]:
        """
        Run the same pipeline for several display segments at once, sharing a single thread pool.
        Segments that do not fully cover the requested time window are skipped, because
        resampling a partial window would distort the time axis.
        """
        view = self.source_view
        window = self.window_samples(params)
        start_offset = int(params.start_point)
        channel_filters: Dict[int, List[FilterConfig]] = {}
        channel_transformation_add_ons: Dict[int, List[BaseAddOn]] = {}
        for group in params.channels_groups:
            group_filters = list(group.filters or [])
            for channel_idx in group.channel_indexes:
                channel_filters[channel_idx] = group_filters
                channel_transformation_add_ons[channel_idx] = [transformation_add_on for transformation_add_on in
                                                               (transformation_add_ons or [])
                                                               if transformation_add_on.applicable(channel_idx)]

        # The window length is derived from duration_ms here and from sample_rate when the GUI
        # clamps start_point, so allow the single sample those two roundings may disagree on.
        min_required_points = max(0, start_offset + window - 1)
        segments_to_process: List[int] = []
        for segment_idx in segment_indexes:
            if not (0 <= segment_idx < view.number_of_segments) or segment_idx in segments_to_process:
                continue
            available_points = view.display_segments[segment_idx].number_of_samples
            if available_points < min_required_points:
                ephyr_logger().debug(
                    f"Segment {segment_idx} is shorter than the requested window "
                    f"({available_points} < {start_offset + window} samples), skipped"
                )
                continue
            segments_to_process.append(segment_idx)

        results: Dict[int, Dict[int, np.ndarray[np.float64]]] = {idx: {} for idx in segments_to_process}
        if not channel_indexes or not segments_to_process:
            return results

        tasks_num = len(channel_indexes) * len(segments_to_process)
        max_workers = min(tasks_num, (os.cpu_count() or 4) * 4)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_task = {}
            for channel_idx in channel_indexes:
                filters_for_channel = channel_filters.get(channel_idx, [])
                transformation_add_ons_for_channel = channel_transformation_add_ons.get(channel_idx, [])
                required_sample_rate = max(
                    required_sample_rate_for_filters(filters_for_channel),
                    required_sample_rate_for_transformations(transformation_add_ons_for_channel)
                )
                points_for_rate = int(params.duration_ms * 1_000_000 * required_sample_rate)
                target_points = max(int(output_number_of_dots), int(points_for_rate), 1)
                each_point = max(1, int(window / target_points))
                effective_sample_rate = view.sample_rate / each_point
                for segment_idx in segments_to_process:
                    segment = view.display_segments[segment_idx]
                    start_sample = segment.start_sample + start_offset
                    end_sample = min(start_sample + window, segment.start_sample + segment.number_of_samples)
                    future = executor.submit(
                        self.process_single_channel,
                        channel_idx,
                        start_sample,
                        end_sample,
                        each_point,
                        effective_sample_rate,
                        filters_for_channel,
                        output_number_of_dots,
                        transformation_add_ons_for_channel,
                    )
                    future_to_task[future] = (segment_idx, channel_idx)

            for future, (segment_idx, channel_idx) in future_to_task.items():
                try:
                    results[segment_idx][channel_idx] = future.result()
                except Exception as exc:
                    ephyr_logger().error(
                        f"Channel {channel_idx} of segment {segment_idx} generated an exception: {exc}"
                    )
                    raise

        return results

    def process_single_channel(self, channel_idx: int,
                               start_sample: int, end_sample: int,
                               each_point: int, sample_rate: float,
                               filters: List[FilterConfig],
                               output_number_of_dots: int,
                               transformation_add_ons: List[BaseAddOn]) -> np.ndarray[np.float64]:
        """
        Process a single channel's data pipeline over global samples [start_sample, end_sample).
        This method runs in a separate thread for each channel.
        """
        channel_data = self.memmaps[channel_idx][start_sample:end_sample:each_point].astype(np.float64)

        # Convert to physical values in the channel's unit
        channel_data = self.from_int16_to_physical(channel_data, channel_idx)

        # Transform before filtration
        for add_on in transformation_add_ons:
            channel_data = add_on.transform(channel_data, sample_rate)

        # Apply filters in sequence for the current channel group.
        if filters:
            for flt in filters:
                try:
                    channel_data = flt.apply(channel_data, sample_rate)
                except Exception as e:
                    ephyr_logger().debug(str(e))
                    continue

        # Downsample or resample to requested output size
        channel_data = self._resample_to_length(channel_data, output_number_of_dots)

        return channel_data

    @staticmethod
    def _resample_to_length(data: np.ndarray, output_len: int) -> np.ndarray[np.float64]:
        if output_len <= 0:
            return data
        n = len(data)
        if n == output_len or n == 0:
            return data
        if n > output_len:
            idx = np.linspace(0, n - 1, output_len).astype(np.int64)
            return data[idx]
        x_old = np.linspace(0.0, 1.0, n)
        x_new = np.linspace(0.0, 1.0, output_len)
        return np.interp(x_new, x_old, data).astype(np.float64)

    def from_int16_to_physical(self, data: np.ndarray, channel_idx: int):
        """Convert stored samples into values expressed in the channel's unit."""
        info = self.source_view.channel_info
        scale, offset = self.channel_calibration(info.analog_max[channel_idx], info.analog_min[channel_idx],
                                                 info.digital_max[channel_idx], info.digital_min[channel_idx])
        result = np.multiply(scale, data)
        if offset:
            result += offset
        return result

    @staticmethod
    @lru_cache(maxsize=1024)
    def channel_calibration(analog_max, analog_min, digital_max, digital_min) -> Tuple[float, float]:
        scale = (analog_max - analog_min) / (digital_max - digital_min)
        offset = analog_min - digital_min * scale
        # A range symmetric up to one LSB is treated as zero-centred: the half-LSB offset is rounding.
        if abs(offset) <= abs(scale):
            offset = 0.0
        return scale, offset

    def default_scale_for_channel(self, channel_idx: int) -> float:
        return float(settings.DEFAULT_SCALE)

    def default_scale_for_group(self, _channel_indexes: List[int]) -> float:
        return float(settings.DEFAULT_SCALE)


def record_required(method):
    def wrapper(self, *args, **kwargs):
        if self.record_dir is None:
            raise ValueError("Open a Record first")
        return method(self, *args, **kwargs)

    return wrapper


class EphyrSessionManager:
    """The open Record of a workspace: its active source, data and the current session."""

    def __init__(self):
        self.workspace: Optional[Workspace] = None
        self.config_id: Optional[str] = None
        self.record_id: Optional[str] = None
        self.record_dir: Optional[Path] = None
        self.current_user_session: Optional[UserSession] = None
        self.record_data: Optional[RecordData] = None

    # ----- record -----

    @property
    def config(self) -> Optional[ConfigManifest]:
        if self.workspace is None or self.config_id is None:
            return None
        return self.workspace.config(self.config_id)

    @property
    def record(self) -> Optional[RecordManifest]:
        if self.workspace is None or self.config_id is None or self.record_id is None:
            return None
        return self.workspace.record(self.config_id, self.record_id)

    @property
    def source_view(self) -> Optional[SourceView]:
        return self.record_data.source_view if self.record_data is not None else None

    def available_source_ids(self) -> List[str]:
        record = self.record
        return [source.source_id for source in record.sources] if record is not None else []

    def build_source_view(self, source_id: str) -> SourceView:
        config, record = self.config, self.record
        spec = config.source(source_id) if config is not None else None
        record_source = record.source(source_id) if record is not None else None
        if spec is None or record_source is None:
            raise ValueError(f"Source '{source_id}' is not available in this Record")
        return SourceView(spec, record_source, record_name=record.name, start_datetime=record.start_datetime)

    def open_record(self, workspace: Workspace, config_id: str, record_id: str):
        self.current_user_session = None
        self.record_data = None
        self.workspace = workspace
        self.config_id = config_id
        self.record_id = record_id
        self.record_dir = workspace.record_dir(config_id, record_id)
        self.sessions_folder.mkdir(parents=True, exist_ok=True)
        self.load_source(self.config.main_source_id)

    def close_record(self):
        self.current_user_session = None
        self.record_data = None
        self.workspace = None
        self.config_id = None
        self.record_id = None
        self.record_dir = None

    @record_required
    def load_source(self, source_id: str) -> None:
        if source_id not in self.available_source_ids():
            source_id = self.config.main_source_id
        self.record_data = RecordData.open(self.record_dir, self.build_source_view(source_id))
        if self.current_user_session is not None:
            self.current_user_session.gui_setup.active_source_id = source_id
            self.rebuild_display_segments()

    @record_required
    def switch_source(self, source_id: str) -> None:
        """Make another source active, keeping the channel setup of each source in the session."""
        session = self.user_session
        gui_setup = session.gui_setup
        previous = gui_setup.active_source_id or self.config.main_source_id
        if previous == source_id:
            return
        gui_setup.other_sources_setup[previous] = SourceGuiSetup(
            channels_groups=gui_setup.channels_groups, channels_setup=gui_setup.channels_setup
        )
        self.load_source(source_id)
        stored = gui_setup.other_sources_setup.pop(source_id, None) or default_source_setup(self.source_view)
        gui_setup.channels_groups = stored.channels_groups
        gui_setup.channels_setup = stored.channels_setup
        gui_setup.current_segment_idx = 0
        gui_setup.overlay_segment_idxs = []
        gui_setup.start_point = 0

    def rebuild_display_segments(self) -> None:
        """Display segments of the active source for the navigation mode of the current session."""
        view = self.source_view
        if view is None:
            return
        gui_setup = self.current_user_session.gui_setup if self.current_user_session is not None else GuiSetup()
        mode = gui_setup.navigation_mode
        if mode is NavigationModeEnum.CONTINUOUS:
            segments = continuous_display_segments(view)
        elif mode is NavigationModeEnum.PERIOD_LABEL and self.current_user_session is not None:
            session = self.current_user_session
            label_id = gui_setup.period_label_id
            periods = [(period.start_t_ms, period.end_t_ms) for period in session.periods
                       if period.period_name_id == label_id]
            segments = period_display_segments(view, periods, gui_setup.pre_ms, gui_setup.post_ms,
                                               session.get_period_vocabulary_name(label_id)
                                               if label_id is not None else "Period")
        else:
            segments = physical_display_segments(view)
        view.display_segments = segments
        if self.current_user_session is not None:
            count = len(segments)
            gui_setup.current_segment_idx = min(max(0, gui_setup.current_segment_idx), max(0, count - 1))
            gui_setup.overlay_segment_idxs = [idx for idx in gui_setup.overlay_segment_idxs if 0 <= idx < count]

    # ----- sessions -----

    @property
    def user_session(self) -> UserSession:
        if self.current_user_session is None:
            raise ValueError("Open a Record first")

        return self.current_user_session

    @property
    def sessions_folder(self) -> Path:
        return layout.sessions_dir(self.record_dir)

    @property
    def add_ons_data_folder(self) -> Path:
        folder = layout.add_ons_data_dir(self.record_dir)
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def session_name_already_exists(self, session_name: str):
        return (session_name in self.other_session_names
                or self.current_user_session is not None
                and session_name == self.current_user_session.session_name)

    @record_required
    def new_user_session(self, session_name: str):
        if self.session_name_already_exists(session_name):
            raise SessionAlreadyExistsError
        if not is_valid_session_name(session_name):
            raise ValueError(f"Invalid session name: {session_name!r}")

        main_source_id = self.config.main_source_id
        if self.source_view is None or self.source_view.source_id != main_source_id:
            self.record_data = RecordData.open(self.record_dir, self.build_source_view(main_source_id))
        source_setup = default_source_setup(self.source_view)
        session = UserSession(
            session_name=session_name.strip(),
            gui_setup=GuiSetup(
                active_source_id=main_source_id,
                channels_groups=source_setup.channels_groups,
                channels_setup=source_setup.channels_setup,
            ),
        )
        # Annotations stored in the source files become the starting annotations of every new session.
        session.add_event_rows(read_events(layout.source_events_path(self.record_dir)))
        session.add_period_rows(read_periods(layout.source_periods_path(self.record_dir)))
        self.current_user_session = session
        self.rebuild_display_segments()
        self.save_user_session()

    def export_current_session(self, destination_path: Path) -> str:
        self.current_user_session.save_session(destination_path)
        return self.current_user_session.session_name

    @record_required
    def import_new_session(self, user_session: UserSession):
        user_session.save_session(self.sessions_folder)

    @record_required
    def switch_sessions(self, session_name: str):
        session = UserSession.load(self.sessions_folder / session_name)
        self.current_user_session = session
        self.load_source(session.gui_setup.active_source_id or self.config.main_source_id)
        self.rebuild_display_segments()

    @staticmethod
    def parse_session_folder(session_folder: Path) -> UserSession:
        return UserSession.load(session_folder)

    @record_required
    def save_user_session(self):
        self.current_user_session.save_session(self.sessions_folder)

    @record_required
    def delete_session(self, session_name: str):
        folder = self.sessions_folder / session_name
        if folder.is_dir():
            shutil.rmtree(folder)

    @property
    def session_is_active(self):
        return self.record_dir is not None and self.current_user_session is not None

    @property
    def other_session_names(self) -> List[str]:
        if self.record_dir is None or not self.sessions_folder.is_dir():
            return []
        return sorted(item.name for item in self.sessions_folder.iterdir()
                      if item.is_dir() and UserSession.is_session_folder(item))

    def update_right_panel_widgets(self, right_panel_widgets: List):
        if self.current_user_session is not None:
            self.current_user_session.gui_setup.right_panel_widgets = right_panel_widgets
