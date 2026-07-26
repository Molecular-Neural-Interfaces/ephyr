from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

import numpy as np
from pynwb import NWBHDF5IO, TimeSeries
from pynwb.ecephys import ElectricalSeries

from ._exceptions import WrongSourceReaderError
from .abstract_source_reader import AbstractDataWriter, AbstractSourceReader
from weegit.core.header import ChannelInfo, Header

_CHUNK_SAMPLES = 512
_DIGITAL_MIN = -32768
_DIGITAL_MAX = 32767


@dataclass(frozen=True)
class NwbSeriesRef:
    location: str
    name: str
    n_samples: int
    n_channels: int
    sample_rate: float
    units: str
    channel_names: List[str]
    probes: List[str]
    conversion: float
    offset: float


def _unit_ascii(unit: str) -> str:
    raw = (unit or "").strip().replace("µ", "u").replace("μ", "u")
    aliases = {
        "volt": "V",
        "volts": "V",
        "v": "V",
        "millivolt": "mV",
        "millivolts": "mV",
        "mv": "mV",
        "microvolt": "uV",
        "microvolts": "uV",
        "uv": "uV",
    }
    return aliases.get(raw.lower(), raw or "uV")


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

    return NwbSeriesRef(
        location=location,
        name=str(series.name),
        n_samples=n_samples,
        n_channels=n_channels,
        sample_rate=rate,
        units=_unit_ascii(str(getattr(series, "unit", "") or "")),
        channel_names=names,
        probes=probes,
        conversion=float(getattr(series, "conversion", 1.0) or 1.0),
        offset=float(getattr(series, "offset", 0.0) or 0.0),
    )


def _choose_series(nwbfile) -> Tuple[NwbSeriesRef, TimeSeries]:
    candidates: List[Tuple[NwbSeriesRef, TimeSeries]] = []
    for location, series in _iter_series(nwbfile):
        ref = _series_ref(location, series)
        if ref is not None:
            candidates.append((ref, series))
    if not candidates:
        raise ValueError("NWB file contains no regular TimeSeries/ElectricalSeries data")
    candidates.sort(
        key=lambda item: (
            isinstance(item[1], ElectricalSeries),
            item[0].n_channels * item[0].n_samples,
        ),
        reverse=True,
    )
    return candidates[0]


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


def _scan_quantization(experiment_path: Path, ref: NwbSeriesRef) -> np.ndarray:
    max_abs = np.zeros(ref.n_channels, dtype=np.float64)
    chunk_size = _CHUNK_SAMPLES * 1024
    with NWBHDF5IO(str(experiment_path), "r", load_namespaces=True) as io:
        nwbfile = io.read()
        series = _series_by_location(nwbfile, ref.location)
        for start in range(0, ref.n_samples, chunk_size):
            end = min(start + chunk_size, ref.n_samples)
            chunk = _physical_chunk(series, start, end, ref)
            chunk_max = np.nanmax(np.abs(chunk), axis=0)
            max_abs = np.maximum(max_abs, chunk_max)
    max_abs[~np.isfinite(max_abs)] = 1.0
    max_abs[max_abs <= 0] = 1.0
    return max_abs


class NwbDataWriter(AbstractDataWriter):
    def __init__(self, experiment_path: Path, ref: NwbSeriesRef, analog_abs_max: np.ndarray):
        self._experiment_path = experiment_path
        self._ref = ref
        self._analog_abs_max = analog_abs_max
        self._sample_pos = 0
        self._io: Optional[NWBHDF5IO] = None
        self._series: Optional[TimeSeries] = None

    def __iter__(self) -> "NwbDataWriter":
        self._sample_pos = 0
        self._io = NWBHDF5IO(str(self._experiment_path), "r", load_namespaces=True)
        nwbfile = self._io.read()
        self._series = _series_by_location(nwbfile, self._ref.location)
        return self

    def __next__(self) -> np.ndarray:
        if self._series is None:
            self.__iter__()
        if self._sample_pos >= self._ref.n_samples:
            if self._io is not None:
                self._io.close()
            self._io = None
            self._series = None
            raise StopIteration

        end = min(self._sample_pos + _CHUNK_SAMPLES, self._ref.n_samples)
        physical = _physical_chunk(self._series, self._sample_pos, end, self._ref)
        scales = self._analog_abs_max[np.newaxis, :] / float(_DIGITAL_MAX)
        quantized = np.rint(physical / scales)
        np.clip(quantized, _DIGITAL_MIN, _DIGITAL_MAX, out=quantized)
        self._sample_pos = end
        return quantized.T.astype(np.int16)

    def total_chunks(self, header: Header) -> int:
        total_points = sum(header.number_of_points_per_sweep)
        return max(1, (total_points + _CHUNK_SAMPLES - 1) // _CHUNK_SAMPLES)


class NwbSourceReader(AbstractSourceReader):
    def __init__(self, experiment_path: Path):
        super().__init__(experiment_path)
        self._yielded = False

    @classmethod
    def _try_to_open(cls, experiment_path: Path) -> None:
        if not experiment_path.is_file() or experiment_path.suffix.lower() != ".nwb":
            raise WrongSourceReaderError(cls)
        try:
            with NWBHDF5IO(str(experiment_path), "r", load_namespaces=True) as io:
                nwbfile = io.read()
                _choose_series(nwbfile)
        except Exception:
            raise WrongSourceReaderError(cls)

    def __iter__(self) -> "NwbSourceReader":
        self._yielded = False
        return self

    def __next__(self) -> Tuple[Header, NwbDataWriter]:
        if self._yielded:
            raise StopIteration
        self._yielded = True

        with NWBHDF5IO(str(self._experiment_path), "r", load_namespaces=True) as io:
            nwbfile = io.read()
            ref, _ = _choose_series(nwbfile)
            start_dt = getattr(nwbfile, "session_start_time", None)
            if not isinstance(start_dt, datetime):
                start_dt = datetime.fromtimestamp(self._experiment_path.stat().st_mtime)

        analog_abs_max = _scan_quantization(self._experiment_path, ref)
        channel_info = ChannelInfo(
            name=ref.channel_names,
            probe=ref.probes,
            units=[ref.units] * ref.n_channels,
            analog_min=(-analog_abs_max).tolist(),
            analog_max=analog_abs_max.tolist(),
            digital_min=[_DIGITAL_MIN] * ref.n_channels,
            digital_max=[_DIGITAL_MAX] * ref.n_channels,
            prefiltering=[""] * ref.n_channels,
            number_of_points_per_channel=[ref.n_samples] * ref.n_channels,
        )
        header = Header(
            type_before_conversion="nwb",
            name_before_conversion=f"{self._experiment_path.name}:{ref.location}",
            creation_date_before_conversion=str(start_dt.date()),
            creation_time_before_conversion=str(start_dt.time()),
            sample_interval_microseconds=1e6 / ref.sample_rate,
            sample_rate=ref.sample_rate,
            number_of_channels=ref.n_channels,
            number_of_sweeps=1,
            number_of_points_per_sweep=[ref.n_samples],
            channel_info=channel_info,
        )
        return header, NwbDataWriter(self._experiment_path, ref, analog_abs_max)
