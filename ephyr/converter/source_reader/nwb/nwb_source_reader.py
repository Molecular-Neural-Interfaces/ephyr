# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Tuple

import numpy as np
from pynwb import NWBHDF5IO, TimeSeries
from pynwb.ecephys import ElectricalSeries

from pynwb.icephys import PatchClampSeries

from ephyr.core.manifests import SegmentKindEnum
from ephyr.core.units import (
    PhysicalQuantityEnum,
    SignalUnitEnum,
    canonical_unit_label,
    parse_unit,
    unit_quantity,
)

from .._exceptions import WrongSourceReaderError
from ..abstract_source_reader import (
    AbstractDataWriter,
    AbstractSourceReader,
    ChannelPlan,
    ConversionPlan,
    PeriodPlan,
    SourcePlan,
    SourceRef,
    contiguous_segments,
)

# Prefer large time chunks: HD-MEA NWB is often gzip-chunked (~78k samples),
# and tiny reads re-decompress the same HDF5 slabs thousands of times.
_CHUNK_SAMPLES = 65536
_DIGITAL_MIN = -32768
_DIGITAL_MAX = 32767
_FLOAT_SAMPLE_WINDOWS = 8
_FLOAT_SAMPLE_WINDOW = 8192


@dataclass(frozen=True)
class NwbSeriesRef:
    location: str
    kind: str
    name: str
    n_samples: int
    n_channels: int
    sample_rate: float
    units: str
    channel_names: List[str]
    probes: List[str]
    conversion: float
    offset: float
    preferred_unit: Optional[SignalUnitEnum] = None
    starting_time_s: float = 0.0


def _unit_ascii(unit: str) -> str:
    return canonical_unit_label(unit) or SignalUnitEnum.VOLT.value


def _preferred_unit(series: TimeSeries, units: str) -> Optional[SignalUnitEnum]:
    """Unit a physiologist reads this series in; NWB itself always stores SI units."""
    quantity = unit_quantity(units)
    if isinstance(series, ElectricalSeries) and quantity is PhysicalQuantityEnum.VOLTAGE:
        return SignalUnitEnum.MICROVOLT
    if isinstance(series, PatchClampSeries):
        if quantity is PhysicalQuantityEnum.VOLTAGE:
            return SignalUnitEnum.MILLIVOLT
        if quantity is PhysicalQuantityEnum.CURRENT:
            return SignalUnitEnum.PICOAMPERE
    return None


def _series_rate(series: TimeSeries) -> Optional[float]:
    rate = getattr(series, "rate", None)
    if rate is not None:
        rate = float(rate)
        if rate > 0:
            return rate
    timestamps = getattr(series, "timestamps", None)
    if timestamps is None:
        return None
    try:
        if len(timestamps) < 2:
            return None
        first = float(timestamps[0])
        last = float(timestamps[len(timestamps) - 1])
        if last <= first:
            return None
        return float((len(timestamps) - 1) / (last - first))
    except Exception:
        return None


def _series_start_s(series: TimeSeries) -> float:
    starting_time = getattr(series, "starting_time", None)
    if starting_time is not None:
        try:
            return float(starting_time)
        except Exception:
            pass
    timestamps = getattr(series, "timestamps", None)
    if timestamps is not None:
        try:
            return float(timestamps[0])
        except Exception:
            pass
    return 0.0


def _series_shape(series: TimeSeries) -> Optional[Tuple[int, int]]:
    shape = getattr(series.data, "shape", None)
    if not shape:
        try:
            data = np.asarray(series.data)
            shape = data.shape
        except Exception:
            return None
    if len(shape) == 1:
        return int(shape[0]), 1
    if len(shape) == 2:
        return int(shape[0]), int(shape[1])
    return None


def _iter_series(nwbfile) -> Iterable[Tuple[str, TimeSeries]]:
    for name, obj in nwbfile.acquisition.items():
        yield from _iter_series_from_obj(f"acquisition/{name}", obj)
    for module_name, module in nwbfile.processing.items():
        yield from _iter_series_from_obj(f"processing/{module_name}", module)


def _iter_series_from_obj(location: str, obj) -> Iterable[Tuple[str, TimeSeries]]:
    if isinstance(obj, TimeSeries):
        yield location, obj
        return
    for attr in ("electrical_series", "time_series", "data_interfaces"):
        children = getattr(obj, attr, None)
        if not children:
            continue
        if hasattr(children, "items"):
            iterable = children.items()
        else:
            iterable = enumerate(children)
        for name, child in iterable:
            yield from _iter_series_from_obj(f"{location}/{name}", child)


def _safe_sequence_value(values, idx: int, default: str) -> str:
    try:
        value = values[idx]
    except Exception:
        return default
    if value is None:
        return default
    return str(value)


def _electrical_channel_metadata(series: ElectricalSeries, n_channels: int) -> Tuple[List[str], List[str]]:
    names = [f"ch_{idx}" for idx in range(n_channels)]
    probes = [""] * n_channels
    electrodes = getattr(series, "electrodes", None)
    if electrodes is None:
        return names, probes

    try:
        table = electrodes.table
        indexes = list(electrodes.data[:])
    except Exception:
        return names, probes

    for out_idx, table_idx in enumerate(indexes[:n_channels]):
        name = ""
        for column in ("label", "channel_name", "name"):
            if column in table:
                name = _safe_sequence_value(table[column].data, int(table_idx), "")
                if name:
                    break
        if not name:
            name = f"electrode_{table_idx}"
        names[out_idx] = name

        probe_parts: List[str] = []
        for column in ("location", "group_name"):
            if column in table:
                value = _safe_sequence_value(table[column].data, int(table_idx), "")
                if value:
                    probe_parts.append(value)
        probes[out_idx] = " / ".join(probe_parts)
    return names, probes


def _series_ref(location: str, series: TimeSeries) -> Optional[NwbSeriesRef]:
    shape = _series_shape(series)
    rate = _series_rate(series)
    if shape is None or rate is None:
        return None
    n_samples, n_channels = shape
    if n_samples <= 0 or n_channels <= 0:
        return None

    if isinstance(series, ElectricalSeries):
        names, probes = _electrical_channel_metadata(series, n_channels)
    else:
        names = [str(series.name)] if n_channels == 1 else [f"{series.name}_{idx}" for idx in range(n_channels)]
        probes = [""] * n_channels

    units = _unit_ascii(str(getattr(series, "unit", "") or ""))
    return NwbSeriesRef(
        location=location,
        kind=type(series).__name__,
        name=str(series.name),
        n_samples=n_samples,
        n_channels=n_channels,
        sample_rate=rate,
        units=units,
        channel_names=names,
        probes=probes,
        conversion=float(getattr(series, "conversion", 1.0) or 1.0),
        offset=float(getattr(series, "offset", 0.0) or 0.0),
        preferred_unit=_preferred_unit(series, units),
        starting_time_s=_series_start_s(series),
    )


def _candidates(nwbfile) -> List[Tuple[NwbSeriesRef, TimeSeries]]:
    candidates: List[Tuple[NwbSeriesRef, TimeSeries]] = []
    for location, series in _iter_series(nwbfile):
        ref = _series_ref(location, series)
        if ref is not None:
            candidates.append((ref, series))
    if not candidates:
        raise ValueError("NWB file contains no regular TimeSeries/ElectricalSeries data")
    return candidates


def _main_rank(ref: NwbSeriesRef) -> Tuple[bool, int]:
    return ref.kind == "ElectricalSeries", ref.n_channels * ref.n_samples


def _choose_series(nwbfile) -> Tuple[NwbSeriesRef, TimeSeries]:
    return max(_candidates(nwbfile), key=lambda item: _main_rank(item[0]))


def _group_key(ref: NwbSeriesRef) -> Tuple:
    """Series that differ only in time (sweeps of patch-clamp, chunks) form one source."""
    if ref.kind == "ElectricalSeries":
        identity: Tuple = tuple(ref.channel_names)
    else:
        identity = (ref.location.rsplit("/", 1)[0],)
    return (ref.kind, round(ref.sample_rate, 6), ref.n_channels, ref.units) + identity


def _series_groups(nwbfile) -> List[List[NwbSeriesRef]]:
    groups: Dict[Tuple, List[NwbSeriesRef]] = {}
    for ref, _series in _candidates(nwbfile):
        groups.setdefault(_group_key(ref), []).append(ref)
    result = [sorted(refs, key=lambda ref: (ref.starting_time_s, ref.location)) for refs in groups.values()]
    result.sort(key=lambda refs: max(_main_rank(ref) for ref in refs), reverse=True)
    return result


def _interval_annotations(nwbfile) -> List[PeriodPlan]:
    periods: List[PeriodPlan] = []
    tables = {}
    for name in ("trials", "epochs"):
        table = getattr(nwbfile, name, None)
        if table is not None:
            tables[name] = table
    for name, table in (getattr(nwbfile, "intervals", None) or {}).items():
        tables.setdefault(name, table)
    for name, table in tables.items():
        try:
            frame = table.to_dataframe()
        except Exception:
            continue
        if "start_time" not in frame or "stop_time" not in frame:
            continue
        extra_columns = [column for column in frame.columns if column not in {"start_time", "stop_time", "tags",
                                                                             "timeseries"}]
        for row in frame.itertuples(index=False):
            row_dict = row._asdict()
            tags = row_dict.get("tags")
            label = name
            if isinstance(tags, (list, tuple, np.ndarray)) and len(tags):
                label = f"{name}: {', '.join(str(tag) for tag in tags)}"
            extra = {}
            for column in extra_columns:
                value = row_dict.get(column)
                if isinstance(value, (str, int, float, bool, np.integer, np.floating, np.bool_)):
                    extra[str(column)] = str(value)
            periods.append(
                PeriodPlan(
                    start_t_ms=float(row_dict["start_time"]) * 1000.0,
                    end_t_ms=float(row_dict["stop_time"]) * 1000.0,
                    label=label,
                    extra=extra,
                )
            )
    return periods


def _series_by_location(nwbfile, location: str) -> TimeSeries:
    for candidate_location, series in _iter_series(nwbfile):
        if candidate_location == location:
            return series
    raise ValueError(f"NWB series not found: {location}")


def _physical_chunk(series: TimeSeries, start: int, end: int, ref: NwbSeriesRef) -> np.ndarray:
    data = np.asarray(series.data[start:end], dtype=np.float64)
    if data.ndim == 1:
        data = data[:, np.newaxis]
    data = data * ref.conversion + ref.offset
    return data


def _writer_chunk_samples(series: TimeSeries, n_samples: int) -> int:
    """Pick a time-chunk size that avoids re-decompressing the same HDF5 slabs."""
    chunks = getattr(getattr(series, "data", None), "chunks", None)
    if chunks and len(chunks) >= 1:
        try:
            hdf5_rows = int(chunks[0])
            if hdf5_rows > 0:
                return max(1, min(hdf5_rows, n_samples))
        except Exception:
            pass
    return max(1, min(_CHUNK_SAMPLES, n_samples))


def _dtype_analog_abs_max(series: TimeSeries, ref: NwbSeriesRef) -> Optional[np.ndarray]:
    """Map full integer ADC range through conversion/offset — O(1), no data read."""
    try:
        dtype = np.dtype(series.data.dtype)
    except Exception:
        return None
    if not np.issubdtype(dtype, np.integer):
        return None
    info = np.iinfo(dtype)
    extrema = np.asarray([info.min, info.max], dtype=np.float64) * ref.conversion + ref.offset
    peak = float(np.nanmax(np.abs(extrema)))
    if not np.isfinite(peak) or peak <= 0:
        peak = 1.0
    return np.full(ref.n_channels, peak, dtype=np.float64)


def _sample_analog_abs_max(series: TimeSeries, ref: NwbSeriesRef) -> np.ndarray:
    """Cheap strided peak estimate for float series (avoids a full-file scan)."""
    max_abs = np.zeros(ref.n_channels, dtype=np.float64)
    if ref.n_samples <= 0:
        return np.ones(ref.n_channels, dtype=np.float64)
    window = max(1, min(_FLOAT_SAMPLE_WINDOW, ref.n_samples))
    if ref.n_samples <= window * _FLOAT_SAMPLE_WINDOWS:
        starts = list(range(0, ref.n_samples, window))
    else:
        starts = [
            int(round(i * (ref.n_samples - window) / max(1, _FLOAT_SAMPLE_WINDOWS - 1)))
            for i in range(_FLOAT_SAMPLE_WINDOWS)
        ]
    for start in starts:
        end = min(start + window, ref.n_samples)
        chunk = _physical_chunk(series, start, end, ref)
        if chunk.size == 0:
            continue
        max_abs = np.maximum(max_abs, np.nanmax(np.abs(chunk), axis=0))
    max_abs[~np.isfinite(max_abs)] = 1.0
    max_abs[max_abs <= 0] = 1.0
    return max_abs


def _estimate_quantization(series: TimeSeries, ref: NwbSeriesRef, scan: bool) -> Tuple[np.ndarray, int]:
    chunk_samples = _writer_chunk_samples(series, ref.n_samples)
    dtype_max = _dtype_analog_abs_max(series, ref)
    if dtype_max is not None:
        return dtype_max, chunk_samples
    if not scan:
        return np.ones(ref.n_channels, dtype=np.float64), chunk_samples
    return _sample_analog_abs_max(series, ref), chunk_samples


class NwbDataWriter(AbstractDataWriter):
    """Series of one source written one after another (each one is a segment)."""

    def __init__(self, experiment_path: Path, refs: List[NwbSeriesRef], analog_abs_max: np.ndarray,
                 chunk_samples: int = _CHUNK_SAMPLES):
        self._experiment_path = experiment_path
        self._refs = refs
        self._analog_abs_max = analog_abs_max
        self._chunk_samples = max(1, int(chunk_samples))

    def __iter__(self) -> Iterator[np.ndarray]:
        scales = self._analog_abs_max[np.newaxis, :] / float(_DIGITAL_MAX)
        with NWBHDF5IO(str(self._experiment_path), "r", load_namespaces=True) as io:
            nwbfile = io.read()
            for ref in self._refs:
                series = _series_by_location(nwbfile, ref.location)
                for start in range(0, ref.n_samples, self._chunk_samples):
                    end = min(start + self._chunk_samples, ref.n_samples)
                    physical = _physical_chunk(series, start, end, ref)
                    quantized = np.rint(physical / scales)
                    np.clip(quantized, _DIGITAL_MIN, _DIGITAL_MAX, out=quantized)
                    yield quantized.T.astype(np.int16)

    def total_chunks(self) -> int:
        return max(1, sum((ref.n_samples + self._chunk_samples - 1) // self._chunk_samples for ref in self._refs))


def _source_id(refs: List[NwbSeriesRef], is_main: bool, taken: List[str]) -> str:
    if is_main:
        return "main"
    base = "".join(char if char.isalnum() else "_" for char in refs[0].name.lower()).strip("_") or "series"
    candidate, counter = base, 2
    while candidate in taken:
        candidate, counter = f"{base}_{counter}", counter + 1
    return candidate


class NwbSourceReader(AbstractSourceReader):
    """Every regular TimeSeries is a source (series that differ only in time are segments of one source);
    trials, epochs and other interval tables become source periods."""

    format_name = "nwb"

    @classmethod
    def resolve(cls, path: Path) -> SourceRef:
        if not path.is_file() or path.suffix.lower() != ".nwb":
            raise WrongSourceReaderError(cls)
        with NWBHDF5IO(str(path), "r", load_namespaces=True) as io:
            _choose_series(io.read())
        return SourceRef(format=cls.format_name, kind="file", root=path, name=path.name, files=[path])

    def probe(self, scan: bool = False) -> ConversionPlan:
        path = self.ref.root
        sources: List[SourcePlan] = []
        with NWBHDF5IO(str(path), "r", load_namespaces=True) as io:
            nwbfile = io.read()
            start_dt = getattr(nwbfile, "session_start_time", None)
            if not isinstance(start_dt, datetime):
                start_dt = datetime.fromtimestamp(path.stat().st_mtime)
            for idx, refs in enumerate(_series_groups(nwbfile)):
                first = refs[0]
                abs_max = np.zeros(first.n_channels, dtype=np.float64)
                chunk_samples = _CHUNK_SAMPLES
                for ref in refs:
                    series = _series_by_location(nwbfile, ref.location)
                    ref_max, chunk_samples = _estimate_quantization(series, ref, scan)
                    abs_max = np.maximum(abs_max, ref_max)
                channels = [
                    ChannelPlan(
                        name=first.channel_names[ch],
                        units=first.units,
                        analog_min=-float(abs_max[ch]),
                        analog_max=float(abs_max[ch]),
                        digital_min=_DIGITAL_MIN,
                        digital_max=_DIGITAL_MAX,
                        probe=first.probes[ch],
                    )
                    for ch in range(first.n_channels)
                ]
                if first.preferred_unit is not None:
                    _rescale(channels, first.preferred_unit)
                points = [ref.n_samples for ref in refs]
                t_starts = [ref.starting_time_s * 1000.0 for ref in refs]
                source_id = _source_id(refs, idx == 0, [plan.source_id for plan in sources])
                sources.append(
                    SourcePlan(
                        source_id=source_id,
                        name=first.name if len(refs) == 1 else f"{first.name} (+{len(refs) - 1})",
                        sample_rate=first.sample_rate,
                        channels=channels,
                        segments=contiguous_segments(points, first.sample_rate, t_starts,
                                                     labels=[ref.name for ref in refs] if len(refs) > 1 else None),
                        segment_kind=SegmentKindEnum.SWEEP if len(refs) > 1 else SegmentKindEnum.CONTINUOUS,
                        source_format=self.format_name,
                        writer_factory=lambda refs=refs, abs_max=abs_max, chunk=chunk_samples: NwbDataWriter(
                            path, refs, abs_max, chunk
                        ),
                    )
                )
            periods = _interval_annotations(nwbfile)
        return ConversionPlan(
            ref=self.ref,
            sources=sources,
            periods=periods,
            start_datetime=start_dt.isoformat(),
            recording_name=path.stem,
            reader_options=dict(self._options),
        )


def _rescale(channels: List[ChannelPlan], target: SignalUnitEnum) -> None:
    for channel in channels:
        unit = parse_unit(channel.units)
        factor = unit.factor_to(target) if unit is not None else None
        if factor is None:
            continue
        channel.analog_min *= factor
        channel.analog_max *= factor
        channel.units = target.value
