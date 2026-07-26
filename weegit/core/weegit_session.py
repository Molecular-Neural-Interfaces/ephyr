import json
import os
from concurrent.futures import ThreadPoolExecutor
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Optional, List, Dict, Tuple, Set

import numpy as np
from pydantic import BaseModel, Field, model_validator
from weegit.core.add_ons.base import BaseAddOn, required_sample_rate_for_transformations
from weegit.logger import weegit_logger

from weegit import settings
from weegit.core.header import Header, VoltageUnitEnum
from weegit.core.conversions.filters import (
    FilterConfig,
    required_sample_rate_for_filters,
    ensure_filters_list,
)
from weegit.core.exceptions import BrokenSessionFileError, SessionAlreadyExistsError
from weegit.converter.weegit_io import WeegitIO


class RightPanelWidgetEnum(Enum):
    SIGNAL_SETTINGS = "signal_settings"
    INFORMATION = "information"
    LOGS = "logs"
    ANALYSIS = "analysis"

    @staticmethod
    def widgets_order():
        return [
            RightPanelWidgetEnum.ANALYSIS,
            RightPanelWidgetEnum.SIGNAL_SETTINGS,
            RightPanelWidgetEnum.INFORMATION,
            RightPanelWidgetEnum.LOGS,
        ]


class EventsTableFormat(Enum):
    DICT = "dict"
    MARKDOWN = "markdown"


class EventTableRow(BaseModel):
    name: str
    sweep_idx: int
    time_ms: float
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
    height_ratio: float = 1.0
    width_ratio: float = 1.0


class ChannelsLayout(BaseModel):
    """Grid layout of channels inside a single channel group."""
    columns_num: int = 1
    columns_num_to_show: int = 1
    cur_column_idx: int = 0
    rows_num: Optional[int] = None
    rows_num_to_show: int = 16
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


class GuiSetup(BaseModel):
    right_panel_widgets: List[RightPanelWidgetEnum] = Field(
        default_factory=lambda: RightPanelWidgetEnum.widgets_order())
    add_ons: Dict[str, AddOnSetup] = Field(default_factory=dict)

    traces_are_shown: bool = True
    events_are_shown: bool = True
    periods_are_shown: bool = True
    cut_traces: bool = False

    current_sweep_idx: int = 0
    start_point: int = 0
    duration_ms: int = 10000
    time_step_ms: int = 1000
    autoscroll_step_interval_ms: int = settings.AUTO_SCROLL_STEP_INTERVAL_MS
    number_of_dots_to_display: int = settings.DEFAULT_NUMBER_OF_DOTS_TO_DISPLAY
    channels_groups: List[ChannelGroup] = Field(default_factory=list)
    channels_setup: Dict[int, ChannelSetup] = Field(default_factory=dict)
    channels_mapping_img: str = ""

    class Config:
        arbitrary_types_allowed = True

    def all_non_auxiliary_channel_indexes(self) -> List[int]:
        result: List[int] = []
        for group in self.channels_groups:
            if group.is_auxiliary:
                continue
            result.extend(group.channel_indexes)
        return result


class Period(BaseModel):
    period_name_id: int
    start_sweep_idx: int
    start_time_ms: float
    end_sweep_idx: int
    end_time_ms: float


class Event(BaseModel):
    event_name_id: int
    sweep_idx: int
    time_ms: float
    is_bad: bool = False


class EventVocabularyEntry(BaseModel):
    name: str
    color: str = "#0066FF"

    @model_validator(mode="before")
    @classmethod
    def _from_legacy_value(cls, value):
        if isinstance(value, str):
            return {"name": value, "color": "#0066FF"}
        return value


class PeriodVocabularyEntry(BaseModel):
    name: str
    color: str = "#00AA55"

    @model_validator(mode="before")
    @classmethod
    def _from_legacy_value(cls, value):
        if isinstance(value, str):
            return {"name": value, "color": "#00AA55"}
        return value


class UserSession(BaseModel):
    session_filename: str
    changes_saved: bool = True
    events_vocabulary: Dict[int, EventVocabularyEntry] = Field(default_factory=dict)
    events: List[Event] = Field(default_factory=list)
    periods_vocabulary: Dict[int, PeriodVocabularyEntry] = Field(default_factory=dict)
    periods: List[Period] = Field(default_factory=list)
    experiment_description: str = ""
    gui_setup: GuiSetup = Field(default_factory=GuiSetup)

    class Config:
        arbitrary_types_allowed = True

    def save_session(self, dest_folder: Path):
        dest_folder.mkdir(exist_ok=True)
        dest_filepath = dest_folder / self.session_filename
        json_dump = self.model_dump_json(exclude={"session_filename": True, "changes_saved": True}, indent=4)
        with open(dest_filepath, "w") as dest_file:
            dest_file.write(json_dump)

    def change_name(self, new_session_name: str):
        self.session_filename = new_session_name + settings.SESSION_EXTENSION

    @staticmethod
    def parse_session_file(session_filepath: Path):
        if session_filepath.exists():
            with open(session_filepath, "r") as prev_session_file:
                try:
                    json_string = prev_session_file.read()
                    session_dict = json.loads(json_string)
                    session_dict["session_filename"] = session_filepath.name
                    return UserSession.model_validate(session_dict)
                except Exception:
                    raise BrokenSessionFileError(session_filepath)

        return None

    @staticmethod
    def load_from_default_folder(weegit_experiment_folder, session_filename: str) -> "UserSession":
        session_filepath = UserSession.sessions_folder(weegit_experiment_folder) / session_filename
        return UserSession.parse_session_file(session_filepath)

    @staticmethod
    def session_name_to_filename(session_name: str) -> str:
        return session_name + settings.SESSION_EXTENSION

    @staticmethod
    def is_session_file(filename: str) -> bool:
        return filename.endswith(settings.SESSION_EXTENSION)

    @staticmethod
    def sessions_folder(weegit_experiment_folder: Path):
        folder = weegit_experiment_folder / settings.OTHER_SESSIONS_FOLDER
        folder.mkdir(exist_ok=True)
        return folder

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

    def remove_period_vocabulary(self, period_vocabulary_id: int):
        if period_vocabulary_id not in self.periods_vocabulary:
            return

        self.periods_vocabulary = {
            key: value for key, value in self.periods_vocabulary.items()
            if key != period_vocabulary_id
        }
        # Remove periods that reference this vocabulary id
        self.periods = [p for p in self.periods if p.period_name_id != period_vocabulary_id]

    def add_event(self, event_name_id: int, sweep_idx: int, time_ms: float) -> Event:
        """Add a new event to the session."""
        new_event = Event(event_name_id=event_name_id, sweep_idx=sweep_idx, time_ms=time_ms)
        self.events.append(new_event)
        self.events.sort(key=lambda event: (event.sweep_idx, event.time_ms))
        return new_event

    def remove_event(self, event: Event):
        """Remove a specific event instance from the session."""
        try:
            self.events.remove(event)
        except ValueError:
            pass

    def event_set_bad_flag(self, event: Event, is_bad: bool):
        try:
            event_pos = self.events.index(event)
            self.events[event_pos].is_bad = is_bad
        except ValueError:
            pass

    def clear_events_for_vocabulary_id(self, event_name_id: int):
        """Remove all events that reference the given vocabulary id."""
        self.events = [e for e in self.events if e.event_name_id != event_name_id]

    def add_period(self, period_name_id: int, start_sweep_idx: int, start_time_ms: float,
                   end_sweep_idx: int, end_time_ms: float) -> Period:
        period = Period(
            period_name_id=period_name_id,
            start_sweep_idx=start_sweep_idx,
            start_time_ms=start_time_ms,
            end_sweep_idx=end_sweep_idx,
            end_time_ms=end_time_ms,
        )
        self.periods.append(period)
        return period

    def remove_period(self, period: Period):
        try:
            self.periods.remove(period)
        except ValueError:
            pass

    def set_channel_setup(
            self,
            channel_idx: int,
            *,
            scale: float,
            y_offset: float,
            color: str,
            info: Optional[str] = None,
            header: Optional['Header'] = None,
    ):
        if header:
            total_channels = header.number_of_channels
            if channel_idx < 0 or channel_idx >= total_channels:
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
            header: Optional['Header'] = None,
    ):
        if header:
            total_channels = header.number_of_channels
            channel_indexes = [idx for idx in channel_indexes if 0 <= idx < total_channels]
        for channel_idx in channel_indexes:
            prev = self.gui_setup.channels_setup.get(channel_idx)
            self.gui_setup.channels_setup[channel_idx] = ChannelSetup(
                scale=float(scale),
                y_offset=float(y_offset),
                color=color,
                info=(prev.info if (info is None and prev is not None) else (info or "")),
            )

    @property
    def events_table(self, table_format: EventsTableFormat = EventsTableFormat.DICT):
        result = []
        for event in self.events:
            event_periods = []
            for period in self.periods:
                if event.sweep_idx < period.start_sweep_idx or event.sweep_idx > period.end_sweep_idx:
                    continue
                if period.start_sweep_idx == period.end_sweep_idx:
                    in_period = period.start_time_ms <= event.time_ms <= period.end_time_ms
                elif event.sweep_idx == period.start_sweep_idx:
                    in_period = event.time_ms >= period.start_time_ms
                elif event.sweep_idx == period.end_sweep_idx:
                    in_period = event.time_ms <= period.end_time_ms
                else:
                    in_period = True
                if in_period:
                    event_periods.append(self.get_period_vocabulary_name(period.period_name_id))
            result.append(EventTableRow(
                name=self.get_event_vocabulary_name(event.event_name_id),
                sweep_idx=event.sweep_idx,
                time_ms=event.time_ms,
                is_bad=event.is_bad,
                periods=event_periods,
            ))
        return result


class ExperimentData(BaseModel):
    header: Header
    data_memmaps: Tuple[Tuple[np.memmap, ...], ...]

    class Config:
        arbitrary_types_allowed = True

    def process_data_pipeline(self, params: GuiSetup, sweep_idx: int, channel_indexes: List[int],
                              output_number_of_dots: int,
                              transformation_add_ons: Optional[List[BaseAddOn]] = None) -> Dict[
        int, np.ndarray[np.float64]]:
        """
        Process data pipeline using multithreading for each visible channel.
        Returns array of shape (len(visible_channel_indexes), number_of_time_points)
        """
        start_sample = params.start_point
        end_sample = params.start_point + int(params.duration_ms * 1000 / self.header.sample_interval_microseconds)
        channel_filters: Dict[int, List[FilterConfig]] = {}
        channel_transformation_add_ons: Dict[int, List[BaseAddOn]] = {}
        for group_idx, group in enumerate(params.channels_groups):
            group_filters = list(group.filters or [])
            for channel_idx in group.channel_indexes:
                channel_filters[channel_idx] = group_filters
                channel_transformation_add_ons[channel_idx] = [transformation_add_on for transformation_add_on in
                                                               (transformation_add_ons or [])
                                                               if transformation_add_on.applicable(channel_idx)]

        # Collect results by waiting for each future to complete
        results = {}
        if channel_indexes:
            # Use ThreadPoolExecutor to process channels in parallel
            with ThreadPoolExecutor(max_workers=len(channel_indexes)) as executor:
                # Submit all tasks and store futures
                future_to_channel = {}
                for channel_idx in channel_indexes:
                    filters_for_channel = channel_filters.get(channel_idx, [])
                    transformation_add_ons_for_channel = channel_transformation_add_ons.get(channel_idx, [])
                    required_sample_rate = max(
                        required_sample_rate_for_filters(filters_for_channel),
                        required_sample_rate_for_transformations(transformation_add_ons_for_channel)
                    )
                    points_for_rate = int(params.duration_ms * 1_000_000 * required_sample_rate)
                    target_points = max(int(output_number_of_dots), int(points_for_rate), 1)
                    each_point = max(1, int((end_sample - start_sample) / target_points))
                    effective_sample_rate = (
                        self.header.sample_rate / each_point if each_point > 0 else self.header.sample_rate
                    )
                    future = executor.submit(
                        self.process_single_channel,
                        channel_idx,
                        sweep_idx,
                        start_sample,
                        end_sample,
                        each_point,
                        effective_sample_rate,
                        filters_for_channel,
                        output_number_of_dots,
                        transformation_add_ons_for_channel,
                    )
                    future_to_channel[future] = channel_idx

                for future, channel_idx in future_to_channel.items():
                    try:
                        channel_data = future.result()  # This blocks until the thread completes
                        results[channel_idx] = channel_data
                    except Exception as exc:
                        weegit_logger().error(f"Channel {channel_idx} generated an exception: {exc}")
                        raise

        return results

    def process_single_channel(self, channel_idx: int, sweep_idx: int,
                               start_sample: int, end_sample: int,
                               each_point: int, sample_rate: float,
                               filters: List[FilterConfig],
                               output_number_of_dots: int,
                               transformation_add_ons: List[BaseAddOn]) -> np.ndarray[np.float64]:
        """
        Process a single channel's data pipeline.
        This method runs in a separate thread for each channel.
        """
        # Read only the required data for this specific channel
        channel_data = self.data_memmaps[sweep_idx][channel_idx][start_sample:end_sample:each_point].astype(np.float64)

        # Convert to voltage
        channel_data = self.from_int16_to_voltage_val(channel_data, channel_idx)

        # Transform before filtration
        for add_on in transformation_add_ons:
            channel_data = add_on.transform(channel_data, sample_rate)

        # Apply filters in sequence for the current channel group.
        if filters:
            for flt in filters:
                try:
                    channel_data = flt.apply(channel_data, sample_rate)
                except Exception as e:
                    weegit_logger().debug(str(e))
                    continue

        # Downsample or resample to requested output size
        channel_data = self._resample_to_length(channel_data, output_number_of_dots)

        return channel_data

    @staticmethod
    def _resample_to_length(data: np.ndarray, output_len: int) -> np.ndarray[np.float64]:
        if output_len <= 0:
            return data
        n = len(data)
        if n == output_len:
            return data
        if n > output_len:
            idx = np.linspace(0, n - 1, output_len).astype(np.int64)
            return data[idx]
        x_old = np.linspace(0.0, 1.0, n)
        x_new = np.linspace(0.0, 1.0, output_len)
        return np.interp(x_new, x_old, data).astype(np.float64)

    def from_int16_to_voltage_val(self, data: np.ndarray, channel_idx: int):
        units = self.header.channel_info.units or []
        channel_units = units[channel_idx] if channel_idx < len(units) else ""
        return np.multiply(self.channel_scale(self.header.channel_info.analog_max[channel_idx],
                                              self.header.channel_info.analog_min[channel_idx],
                                              self.header.channel_info.digital_max[channel_idx],
                                              self.header.channel_info.digital_min[channel_idx],
                                              channel_units),
                           data)
        # if self.header.type_before_conversion == "rhs":
        #     return np.multiply(0.195, data)
        # elif self.header.type_before_conversion == "daq":
        #     pass
        # else:
        #     raise NotImplementedError(f"from_int16_to_voltage_val is not implemented for "
        #                               f"{self.header.type_before_conversion}")

    @staticmethod
    @lru_cache(maxsize=1024)
    def channel_scale(analog_max, analog_min, digital_max, digital_min, units):
        base_scale = (analog_max - analog_min) / (digital_max - digital_min)
        unit_enum = VoltageUnitEnum.normalize(units)
        return base_scale * unit_enum.to_uv_multiplier()


def weegit_experiment_folder_required(method):
    def wrapper(self, *args, **kwargs):
        if self.weegit_experiment_folder is None:
            raise ValueError("Select weegit experiment folder first'")
        return method(self, *args, **kwargs)

    return wrapper


class WeegitSessionManager(BaseModel):
    weegit_experiment_folder: Optional[Path] = None
    current_user_session: Optional[UserSession] = None
    experiment_data: Optional[ExperimentData] = None

    class Config:
        arbitrary_types_allowed = True

    @property
    def user_session(self) -> UserSession:
        if self.current_user_session is None:
            raise ValueError("Select weegit experiment folder first")

        return self.current_user_session

    def session_name_already_exists(self, session_name: str):
        return self.session_filename_already_exists(UserSession.session_name_to_filename(session_name))

    def session_filename_already_exists(self, session_filename: str):
        return (session_filename in self.other_session_filenames
                or self.current_user_session is not None
                and session_filename == self.current_user_session.session_filename)

    def new_user_session(self, session_filename: str):
        if self.session_filename_already_exists(session_filename):
            raise SessionAlreadyExistsError

        all_channels = list(range(self.experiment_data.header.number_of_channels))
        self.current_user_session = UserSession(
            session_filename=session_filename,
            gui_setup=GuiSetup(
                channels_groups=[
                    ChannelGroup(
                        name="Default",
                        channel_indexes=all_channels,
                        enabled_indexes=set(all_channels),
                        channels_layout=ChannelsLayout(
                            rows_num_to_show=settings.DEFAULT_VISIBLE_CHANNELS_NUM,
                        ),
                    )
                ],
                channels_setup={idx: ChannelSetup() for idx in all_channels},
            ),
        )
        self.save_user_session()

    def export_current_session(self, destination_path: Path) -> str:
        self.current_user_session.save_session(destination_path)
        return self.current_user_session.session_filename

    @weegit_experiment_folder_required
    def import_new_session(self, user_session: UserSession):
        user_session.save_session(UserSession.sessions_folder(self.weegit_experiment_folder))

    @weegit_experiment_folder_required
    def switch_sessions(self, session_filename: str):
        self.current_user_session = UserSession.load_from_default_folder(self.weegit_experiment_folder,
                                                                         session_filename)

    @staticmethod
    def parse_session_file(session_filepath: Path):
        return UserSession.parse_session_file(session_filepath)

    @weegit_experiment_folder_required
    def save_user_session(self):
        self.current_user_session.save_session(UserSession.sessions_folder(self.weegit_experiment_folder))

    def init_from_folder(self, weegit_experiment_folder: Path):
        self.current_user_session = None  # fixme: I don't like the solution
        sessions_folder = UserSession.sessions_folder(weegit_experiment_folder)
        sessions_folder.mkdir(exist_ok=True)
        header, data_memmaps = WeegitIO.read_weegit(weegit_experiment_folder)
        self.experiment_data = ExperimentData(header=header, data_memmaps=data_memmaps)
        self.weegit_experiment_folder = weegit_experiment_folder

    @property
    def session_is_active(self):
        return self.weegit_experiment_folder is not None

    @property
    @weegit_experiment_folder_required
    def other_session_filenames(self):
        session_filenames = []
        if self.weegit_experiment_folder:
            sessions_folder = UserSession.sessions_folder(self.weegit_experiment_folder)
            for file in os.listdir(sessions_folder):
                if UserSession.is_session_file(file):
                    session_filenames.append(file)

        return session_filenames

    def update_right_panel_widgets(self, right_panel_widgets: List):
        if self.current_user_session is not None:
            self.current_user_session.gui_setup.right_panel_widgets = right_panel_widgets
