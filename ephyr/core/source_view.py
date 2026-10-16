# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

"""Runtime view of one source of a Record: channels, calibration, segments and time mapping."""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, List, Optional, Sequence

from pydantic import BaseModel, Field

from ephyr.core.manifests import RecordSource, SegmentInfo, SegmentKindEnum, SourceSpec
from ephyr.core.units import (
    PhysicalQuantityEnum,
    SignalUnitEnum,
    parse_unit,
    unit_display_label,
    unit_quantity,
)


class ChannelInfo(BaseModel):
    """Per-channel parallel arrays, indexed by channel number."""
    name: List[str]
    probe: List[str] = Field(default_factory=list)
    units: List[str] = Field(default_factory=list)
    analog_min: List[float] = Field(default_factory=list)
    analog_max: List[float] = Field(default_factory=list)
    digital_min: List[int] = Field(default_factory=list)
    digital_max: List[int] = Field(default_factory=list)
    prefiltering: List[str] = Field(default_factory=list)
    impedance_ohm: List[Optional[float]] = Field(default_factory=list)

    def rescale_units(self, channel_indexes: Iterable[int], target: SignalUnitEnum) -> None:
        """Re-express channels in `target` by rescaling the analog range; stored samples are untouched.

        Channels whose unit is unknown or of a different quantity are left as is.
        """
        for idx in channel_indexes:
            if idx >= len(self.units):
                continue
            unit = parse_unit(self.units[idx])
            factor = unit.factor_to(target) if unit is not None else None
            if factor is None:
                continue
            if idx < len(self.analog_min):
                self.analog_min[idx] = float(self.analog_min[idx]) * factor
            if idx < len(self.analog_max):
                self.analog_max[idx] = float(self.analog_max[idx]) * factor
            self.units[idx] = target.value


class NavigationModeEnum(str, Enum):
    CONTINUOUS = "continuous"
    SEGMENT = "segment"
    PERIOD_LABEL = "period_label"


class TimeMapper:
    """Maps Record time (ms from the Record start) to global sample indexes of a source and back.

    Global samples run over all physical segments concatenated in the channel files; the time between
    segments is a gap that has no samples.
    """

    def __init__(self, sample_rate: float, segments: Sequence[SegmentInfo]):
        self.sample_rate = float(sample_rate)
        self.segments = list(segments)
        self._sample_starts = [int(segment.start_sample_idx) for segment in self.segments]
        self._t_starts = [float(segment.t_start_ms) for segment in self.segments]

    @property
    def total_samples(self) -> int:
        if not self.segments:
            return 0
        last = self.segments[-1]
        return int(last.start_sample_idx) + int(last.number_of_samples)

    def segment_duration_ms(self, segment_idx: int) -> float:
        return self.segments[segment_idx].number_of_samples * 1000.0 / self.sample_rate

    def segment_end_ms(self, segment_idx: int) -> float:
        return self.segments[segment_idx].t_start_ms + self.segment_duration_ms(segment_idx)

    def segment_of_sample(self, sample: float) -> Optional[int]:
        if not self.segments:
            return None
        idx = bisect.bisect_right(self._sample_starts, sample) - 1
        if idx < 0:
            return None
        segment = self.segments[idx]
        if sample >= segment.start_sample_idx + segment.number_of_samples and idx != len(self.segments) - 1:
            return None
        return idx

    def segment_of_time(self, t_ms: float) -> Optional[int]:
        """Physical segment containing `t_ms`, or None for a time in a gap or outside the Record."""
        if not self.segments:
            return None
        idx = bisect.bisect_right(self._t_starts, t_ms) - 1
        if idx < 0:
            return None
        if t_ms > self.segment_end_ms(idx):
            return None
        return idx

    def sample_of_time(self, t_ms: float, snap: Optional[str] = None) -> Optional[float]:
        """Fractional global sample of `t_ms`.

        A time in a gap returns None, or the start of the next segment for snap="next" and the end
        of the previous segment for snap="prev".
        """
        idx = self.segment_of_time(t_ms)
        if idx is not None:
            segment = self.segments[idx]
            return segment.start_sample_idx + (t_ms - segment.t_start_ms) * self.sample_rate / 1000.0
        if snap is None or not self.segments:
            return None
        following = bisect.bisect_right(self._t_starts, t_ms)
        if snap == "next":
            if following >= len(self.segments):
                return None
            return float(self.segments[following].start_sample_idx)
        previous = following - 1
        if previous < 0:
            return None
        segment = self.segments[previous]
        return float(segment.start_sample_idx + segment.number_of_samples)

    def time_of_sample(self, sample: float) -> float:
        idx = self.segment_of_sample(sample)
        if idx is None:
            idx = 0 if sample < 0 or not self.segments else len(self.segments) - 1
        if not self.segments:
            return sample * 1000.0 / self.sample_rate
        segment = self.segments[idx]
        return segment.t_start_ms + (sample - segment.start_sample_idx) * 1000.0 / self.sample_rate


@dataclass(frozen=True)
class DisplaySegment:
    """A range of global samples that the GUI shows as one sweep-like view."""
    start_sample: int
    number_of_samples: int
    label: str
    physical_segment_idx: Optional[int] = None
    # Window around a period: offset of the period start inside this display segment.
    anchor_ms: float = 0.0


class SourceView:
    """Everything the GUI and the analysis need to know about the active source of a Record."""

    def __init__(
        self,
        spec: SourceSpec,
        record_source: RecordSource,
        *,
        record_name: str = "",
        start_datetime: str = "",
    ):
        self.spec = spec
        self.record_source = record_source
        self.record_name = record_name
        self.start_datetime = start_datetime
        self.time_mapper = TimeMapper(spec.signature.sample_rate, record_source.segments)
        signature = spec.signature
        calibration = record_source.channels
        n_channels = len(signature.channels)
        descriptive = spec.descriptive
        self.channel_info = ChannelInfo(
            name=[channel.name for channel in signature.channels],
            probe=_padded(descriptive.probes, n_channels, ""),
            units=[channel.units for channel in signature.channels],
            analog_min=[float(c.analog_min) for c in calibration],
            analog_max=[float(c.analog_max) for c in calibration],
            digital_min=[int(c.digital_min) for c in calibration],
            digital_max=[int(c.digital_max) for c in calibration],
            prefiltering=_padded(descriptive.prefiltering, n_channels, ""),
            impedance_ohm=[c.impedance_ohm for c in calibration],
        )
        self.display_segments: List[DisplaySegment] = continuous_display_segments(self)

    @property
    def source_id(self) -> str:
        return self.spec.source_id

    @property
    def source_name(self) -> str:
        return self.spec.name

    @property
    def source_format(self) -> str:
        return self.spec.descriptive.source_format

    @property
    def segment_kind(self) -> SegmentKindEnum:
        return self.spec.descriptive.segment_kind

    @property
    def sample_rate(self) -> float:
        return float(self.spec.signature.sample_rate)

    @property
    def sample_interval_microseconds(self) -> float:
        return 1e6 / self.sample_rate

    @property
    def number_of_channels(self) -> int:
        return len(self.spec.signature.channels)

    @property
    def physical_segments(self) -> List[SegmentInfo]:
        return self.record_source.segments

    @property
    def total_samples(self) -> int:
        return self.time_mapper.total_samples

    @property
    def number_of_segments(self) -> int:
        return len(self.display_segments)

    @property
    def segment_points(self) -> List[int]:
        return [segment.number_of_samples for segment in self.display_segments]

    def segment_label(self, idx: int) -> str:
        if 0 <= idx < len(self.display_segments):
            return self.display_segments[idx].label
        return ""

    def segment_duration_ms(self, idx: int) -> float:
        if not 0 <= idx < len(self.display_segments):
            return 0.0
        return self.display_segments[idx].number_of_samples * 1000.0 / self.sample_rate

    def local_ms_of_time(self, segment_idx: int, t_ms: float, snap: Optional[str] = None) -> Optional[float]:
        """Position of Record time `t_ms` inside a display segment, None when it is not shown there."""
        if not 0 <= segment_idx < len(self.display_segments):
            return None
        segment = self.display_segments[segment_idx]
        sample = self.time_mapper.sample_of_time(t_ms, snap=snap)
        if sample is None:
            return None
        local = sample - segment.start_sample
        if snap is None and not 0 <= local <= segment.number_of_samples:
            return None
        return local * 1000.0 / self.sample_rate

    def time_of_local_ms(self, segment_idx: int, local_ms: float) -> float:
        segment = self.display_segments[segment_idx]
        sample = segment.start_sample + local_ms * self.sample_rate / 1000.0
        return self.time_mapper.time_of_sample(sample)

    def segment_time_range_ms(self, segment_idx: int) -> tuple[float, float]:
        segment = self.display_segments[segment_idx]
        start = self.time_mapper.time_of_sample(segment.start_sample)
        end = self.time_mapper.time_of_sample(segment.start_sample + segment.number_of_samples)
        return start, end

    def gap_positions_ms(self, segment_idx: int) -> List[float]:
        """Local positions of the boundaries between physical segments inside a display segment."""
        segment = self.display_segments[segment_idx]
        end = segment.start_sample + segment.number_of_samples
        return [
            (physical.start_sample_idx - segment.start_sample) * 1000.0 / self.sample_rate
            for physical in self.physical_segments[1:]
            if segment.start_sample < physical.start_sample_idx < end
        ]

    def channel_unit_label(self, channel_idx: int) -> str:
        units = self.channel_info.units
        return units[channel_idx] if 0 <= channel_idx < len(units) else ""

    def channel_unit(self, channel_idx: int) -> Optional[SignalUnitEnum]:
        return parse_unit(self.channel_unit_label(channel_idx))

    def channel_unit_display(self, channel_idx: int) -> str:
        return unit_display_label(self.channel_unit_label(channel_idx))

    def channel_quantity(self, channel_idx: int) -> PhysicalQuantityEnum:
        return unit_quantity(self.channel_unit_label(channel_idx))

    def common_unit_display(self, channel_indexes: Optional[Iterable[int]] = None) -> str:
        """Display unit shared by all given channels (all channels by default), "" if they differ."""
        if channel_indexes is None:
            channel_indexes = range(self.number_of_channels)
        units = {self.channel_unit_display(idx) for idx in channel_indexes}
        return units.pop() if len(units) == 1 else ""


def _padded(values: Sequence[str], length: int, fill: str) -> List[str]:
    result = list(values)[:length]
    result.extend([fill] * (length - len(result)))
    return result


def _physical_label(view: SourceView, idx: int) -> str:
    segment = view.physical_segments[idx]
    if segment.label:
        return segment.label
    return f"{view.segment_kind.label} {idx + 1}"


def continuous_display_segments(view: SourceView) -> List[DisplaySegment]:
    return [DisplaySegment(start_sample=0, number_of_samples=view.total_samples, label="Continuous")]


def physical_display_segments(view: SourceView) -> List[DisplaySegment]:
    return [
        DisplaySegment(
            start_sample=int(segment.start_sample_idx),
            number_of_samples=int(segment.number_of_samples),
            label=_physical_label(view, idx),
            physical_segment_idx=idx,
        )
        for idx, segment in enumerate(view.physical_segments)
    ]


def period_display_segments(
    view: SourceView,
    periods: Sequence[tuple[float, float]],
    pre_ms: float,
    post_ms: float,
    label: str,
) -> List[DisplaySegment]:
    """Windows [start - pre, end + post] around each period, clipped to the physical segment of its start."""
    mapper = view.time_mapper
    result: List[DisplaySegment] = []
    for number, (start_ms, end_ms) in enumerate(periods, start=1):
        start_sample = mapper.sample_of_time(start_ms, snap="next")
        if start_sample is None:
            continue
        physical_idx = mapper.segment_of_sample(start_sample)
        if physical_idx is None:
            continue
        physical = mapper.segments[physical_idx]
        segment_start = int(physical.start_sample_idx)
        segment_end = segment_start + int(physical.number_of_samples)
        end_sample = mapper.sample_of_time(end_ms, snap="prev")
        if end_sample is None or end_sample < start_sample:
            end_sample = start_sample
        window_start = max(segment_start, int(round(start_sample - pre_ms * view.sample_rate / 1000.0)))
        window_end = min(segment_end, int(round(end_sample + post_ms * view.sample_rate / 1000.0)))
        if window_end <= window_start:
            continue
        result.append(
            DisplaySegment(
                start_sample=window_start,
                number_of_samples=window_end - window_start,
                label=f"{label} {number}",
                physical_segment_idx=physical_idx,
                anchor_ms=(start_sample - window_start) * 1000.0 / view.sample_rate,
            )
        )
    return result


@dataclass(eq=False)
class ShownEvent:
    """An event projected into a display segment: `time_ms` from the segment start, `t_ms` in Record time."""
    event: object
    time_ms: float

    @property
    def id(self) -> int:
        return self.event.id

    @property
    def t_ms(self) -> float:
        return self.event.t_ms

    @property
    def event_name_id(self) -> int:
        return self.event.event_name_id

    @property
    def is_bad(self) -> bool:
        return self.event.is_bad


@dataclass(eq=False)
class ShownPeriod:
    """A period clipped to a display segment; times are from the segment start."""
    period: object
    start_time_ms: float
    end_time_ms: float
    # Whether the real start / end of the period lies inside this display segment.
    start_in_segment: bool
    end_in_segment: bool

    @property
    def id(self) -> int:
        return self.period.id

    @property
    def period_name_id(self) -> int:
        return self.period.period_name_id


def shown_events(view: SourceView, segment_idx: int, events: Iterable) -> List[ShownEvent]:
    result = []
    for event in events:
        local_ms = view.local_ms_of_time(segment_idx, float(event.t_ms))
        if local_ms is not None:
            result.append(ShownEvent(event, local_ms))
    return result


def shown_periods(view: SourceView, segment_idx: int, periods: Iterable) -> List[ShownPeriod]:
    if not 0 <= segment_idx < view.number_of_segments:
        return []
    duration_ms = view.segment_duration_ms(segment_idx)
    result = []
    for period in periods:
        start = view.local_ms_of_time(segment_idx, float(period.start_t_ms), snap="next")
        end = view.local_ms_of_time(segment_idx, float(period.end_t_ms), snap="prev")
        if start is None or end is None or end < 0 or start > duration_ms or end < start:
            continue
        result.append(ShownPeriod(
            period,
            max(0.0, start),
            min(duration_ms, end),
            start_in_segment=view.local_ms_of_time(segment_idx, float(period.start_t_ms)) is not None,
            end_in_segment=view.local_ms_of_time(segment_idx, float(period.end_t_ms)) is not None,
        ))
    return result
