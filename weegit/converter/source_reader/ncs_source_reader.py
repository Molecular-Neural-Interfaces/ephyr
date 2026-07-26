from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from ._exceptions import WrongSourceReaderError
from .abstract_source_reader import AbstractDataWriter, AbstractSourceReader
from weegit.core.header import ChannelInfo, Header

_HEADER_BYTES = 16 * 1024
_SAMPLES_PER_RECORD = 512
_CHUNK_RECORDS = 128
_NCS_RECORD_DTYPE = np.dtype(
    [
        ("timestamp", "<u8"),
        ("channel_number", "<u4"),
        ("sample_frequency", "<u4"),
        ("num_valid_samples", "<u4"),
        ("samples", "<i2", (_SAMPLES_PER_RECORD,)),
    ]
)
_NEV_RECORD_DTYPE = np.dtype(
    [
        ("nstx", "<u2"),
        ("npkt_id", "<u2"),
        ("npkt_data_size", "<u2"),
        ("timestamp", "<u8"),
        ("event_id", "<u2"),
        ("ttl", "<u2"),
        ("crc", "<u2"),
        ("dummy1", "<u2"),
        ("dummy2", "<u2"),
        ("extra", "<i4", (8,)),
        ("event_string", "S128"),
    ]
)


@dataclass(frozen=True)
class NcsFileInfo:
    path: Path
    header: Dict[str, str]
    record_count: int
    sample_rate: float
    points: int
    ad_max_value: int
    input_range_uv: float
    input_inverted: bool


def _resolve_ncs_folder(experiment_path: Path) -> Path:
    if experiment_path.is_dir():
        return experiment_path
    if experiment_path.is_file() and experiment_path.suffix.lower() in {".ncs", ".nev", ".txt"}:
        return experiment_path.parent
    return experiment_path


def _natural_key(path: Path) -> Tuple[str, int, str]:
    match = re.search(r"(\d+)", path.stem)
    prefix = path.stem[: match.start()] if match else path.stem
    number = int(match.group(1)) if match else -1
    return prefix.lower(), number, path.name.lower()


def _list_ordered_ncs_files(experiment_path: Path) -> List[Path]:
    folder = _resolve_ncs_folder(experiment_path)
    if not folder.is_dir():
        return []
    files = [item for item in folder.iterdir() if item.is_file() and item.suffix.lower() == ".ncs"]
    files.sort(key=_natural_key)
    return files


def _read_ncs_header(path: Path) -> Dict[str, str]:
    with open(path, "rb") as f:
        raw = f.read(_HEADER_BYTES)
    text = raw.decode("latin1", errors="replace").replace("\x00", "\n")
    header: Dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("-"):
            continue
        parts = line[1:].split(None, 1)
        if len(parts) == 1:
            header[parts[0]] = ""
        else:
            header[parts[0]] = parts[1].strip().strip('"')
    return header


def _float_header(header: Dict[str, str], key: str, default: Optional[float] = None) -> float:
    raw = header.get(key)
    if raw is None or raw == "":
        if default is None:
            raise ValueError(f"NCS header is missing {key}")
        return default
    return float(raw)


def _int_header(header: Dict[str, str], key: str, default: Optional[int] = None) -> int:
    raw = header.get(key)
    if raw is None or raw == "":
        if default is None:
            raise ValueError(f"NCS header is missing {key}")
        return default
    return int(float(raw))


def _parse_ncs_file(path: Path) -> NcsFileInfo:
    header = _read_ncs_header(path)
    if header.get("FileType", "").upper() != "NCS":
        raise ValueError("Not a Neuralynx NCS file")
    record_size = _int_header(header, "RecordSize", _NCS_RECORD_DTYPE.itemsize)
    if record_size != _NCS_RECORD_DTYPE.itemsize:
        raise ValueError(f"Unsupported NCS record size: {record_size}")
    data_bytes = path.stat().st_size - _HEADER_BYTES
    if data_bytes < 0 or data_bytes % _NCS_RECORD_DTYPE.itemsize != 0:
        raise ValueError(f"Invalid NCS file size: {path}")
    record_count = data_bytes // _NCS_RECORD_DTYPE.itemsize
    if record_count <= 0:
        raise ValueError(f"NCS file contains no data records: {path}")
    sample_rate = _float_header(header, "SamplingFrequency")
    ad_max_value = _int_header(header, "ADMaxValue", 32767)
    input_range = header.get("InputRange")
    if input_range is not None and input_range != "":
        input_range_uv = float(input_range)
    else:
        ad_bit_volts = _float_header(header, "ADBitVolts")
        input_range_uv = ad_bit_volts * ad_max_value * 1_000_000.0
    input_inverted = header.get("InputInverted", "False").strip().lower() == "true"
    return NcsFileInfo(
        path=path,
        header=header,
        record_count=record_count,
        sample_rate=sample_rate,
        points=record_count * _SAMPLES_PER_RECORD,
        ad_max_value=ad_max_value,
        input_range_uv=input_range_uv,
        input_inverted=input_inverted,
    )


def _records_memmap(info: NcsFileInfo) -> np.memmap:
    return np.memmap(
        info.path,
        dtype=_NCS_RECORD_DTYPE,
        mode="r",
        offset=_HEADER_BYTES,
        shape=(info.record_count,),
    )


def _prefiltering(header: Dict[str, str]) -> str:
    parts: List[str] = []
    low_enabled = header.get("DSPLowCutFilterEnabled") or header.get("DspLowCutFilterEnabled")
    low_freq = header.get("DspLowCutFrequency")
    low_type = header.get("DspLowCutFilterType")
    high_enabled = header.get("DSPHighCutFilterEnabled") or header.get("DspHighCutFilterEnabled")
    high_freq = header.get("DspHighCutFrequency")
    high_type = header.get("DspHighCutFilterType")
    if low_freq:
        parts.append(f"LowCut {low_enabled or ''} {low_type or ''} {low_freq}".strip())
    if high_freq:
        parts.append(f"HighCut {high_enabled or ''} {high_type or ''} {high_freq}".strip())
    return ", ".join(parts)


def _parse_creation_datetime(header: Dict[str, str], fallback: Path) -> Tuple[str, str]:
    raw = header.get("TimeCreated", "")
    for fmt in ("%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(raw, fmt)
            return str(dt.date()), str(dt.time())
        except ValueError:
            pass
    dt = datetime.fromtimestamp(fallback.stat().st_mtime)
    return str(dt.date()), str(dt.time())


def _parse_nev_events(folder: Path, reference: NcsFileInfo, ad_max_value: int) -> List[Tuple[int, int]]:
    nev_path = folder / "Events.nev"
    if not nev_path.exists() or nev_path.stat().st_size <= _HEADER_BYTES:
        return []
    data_bytes = nev_path.stat().st_size - _HEADER_BYTES
    if data_bytes % _NEV_RECORD_DTYPE.itemsize != 0:
        return []

    timestamps = np.asarray(_records_memmap(reference)["timestamp"], dtype=np.int64)
    if timestamps.size == 0:
        return []
    events = np.memmap(
        nev_path,
        dtype=_NEV_RECORD_DTYPE,
        mode="r",
        offset=_HEADER_BYTES,
        shape=(data_bytes // _NEV_RECORD_DTYPE.itemsize,),
    )
    result: List[Tuple[int, int]] = []
    sample_interval_us = 1_000_000.0 / reference.sample_rate
    for event in events:
        event_ts = int(event["timestamp"])
        record_idx = int(np.searchsorted(timestamps, event_ts, side="right") - 1)
        if record_idx < 0:
            record_idx = 0
        elif record_idx >= timestamps.size:
            record_idx = int(timestamps.size - 1)
        offset = int(round((event_ts - int(timestamps[record_idx])) / sample_interval_us))
        sample_idx = record_idx * _SAMPLES_PER_RECORD + offset
        if sample_idx < 0 or sample_idx >= reference.points:
            continue
        text = bytes(event["event_string"]).split(b"\x00", 1)[0].decode("latin1", errors="ignore")
        if text.startswith("TTL"):
            result.append((sample_idx, ad_max_value))
        elif text.startswith("AD Record Loss Detected"):
            result.append((sample_idx, -ad_max_value))
    return result


class NcsDataWriter(AbstractDataWriter):
    def __init__(self, file_infos: List[NcsFileInfo], include_events: bool, event_marks: List[Tuple[int, int]]):
        self._file_infos = file_infos
        self._include_events = include_events
        self._event_marks = sorted(event_marks)
        self._record_pos = 0
        self._memmaps: List[np.memmap] = []

    def __iter__(self) -> "NcsDataWriter":
        self._record_pos = 0
        self._memmaps = [_records_memmap(info) for info in self._file_infos]
        return self

    def __next__(self) -> np.ndarray:
        record_count = self._file_infos[0].record_count
        if self._record_pos >= record_count:
            raise StopIteration
        end = min(self._record_pos + _CHUNK_RECORDS, record_count)
        width = (end - self._record_pos) * _SAMPLES_PER_RECORD
        total_channels = len(self._file_infos) + (1 if self._include_events else 0)
        chunk = np.zeros((total_channels, width), dtype=np.int16)

        for ch_idx, (info, records) in enumerate(zip(self._file_infos, self._memmaps)):
            samples = np.asarray(records[self._record_pos:end]["samples"], dtype=np.int16).copy()
            valid = np.asarray(records[self._record_pos:end]["num_valid_samples"], dtype=np.int64)
            for rec_idx, valid_samples in enumerate(valid):
                if valid_samples < _SAMPLES_PER_RECORD:
                    samples[rec_idx, max(0, int(valid_samples)):] = 0
            if info.input_inverted:
                samples = (-samples.astype(np.int32)).clip(-32768, 32767).astype(np.int16)
            chunk[ch_idx, :] = samples.reshape(-1)

        if self._include_events:
            chunk_start = self._record_pos * _SAMPLES_PER_RECORD
            chunk_end = chunk_start + width
            event_channel = chunk[-1, :]
            for sample_idx, value in self._event_marks:
                if chunk_start <= sample_idx < chunk_end:
                    event_channel[sample_idx - chunk_start] = np.int16(value)

        self._record_pos = end
        return chunk

    def total_chunks(self, header: Header) -> int:
        total_points = sum(header.number_of_points_per_sweep)
        chunk_points = _CHUNK_RECORDS * _SAMPLES_PER_RECORD
        return max(1, (total_points + chunk_points - 1) // chunk_points)


class NcsSourceReader(AbstractSourceReader):
    """
    Neuralynx continuous sampled channel files (.ncs).

    Each .ncs file stores one channel as a 16KB ASCII header followed by fixed
    1044-byte records with 512 int16 samples.
    """

    def __init__(self, experiment_path: Path):
        super().__init__(experiment_path)
        self._source_folder = _resolve_ncs_folder(experiment_path)
        self._yielded = False

    @classmethod
    def _try_to_open(cls, experiment_path: Path):
        files = _list_ordered_ncs_files(experiment_path)
        if not files:
            raise WrongSourceReaderError(cls)
        try:
            _parse_ncs_file(files[0])
        except Exception:
            raise WrongSourceReaderError(cls)

    def __iter__(self) -> "NcsSourceReader":
        self._yielded = False
        return self

    def __next__(self) -> Tuple[Header, NcsDataWriter]:
        if self._yielded:
            raise StopIteration
        self._yielded = True

        file_infos = [_parse_ncs_file(path) for path in _list_ordered_ncs_files(self._source_folder)]
        if not file_infos:
            raise StopIteration

        first = file_infos[0]
        for info in file_infos[1:]:
            if info.record_count != first.record_count:
                raise ValueError("NCS files have different record counts; cannot merge into one Weegit sweep.")
            if abs(info.sample_rate - first.sample_rate) > 1e-9:
                raise ValueError("NCS files have inconsistent sampling rates.")

        event_marks = _parse_nev_events(self._source_folder, first, first.ad_max_value)
        include_events = len(event_marks) > 0

        names = [info.header.get("AcqEntName") or info.path.stem for info in file_infos]
        probes = [info.header.get("ProbeName", "") for info in file_infos]
        units = ["uV"] * len(file_infos)
        analog_min = [-info.input_range_uv for info in file_infos]
        analog_max = [info.input_range_uv for info in file_infos]
        digital_min = [-info.ad_max_value for info in file_infos]
        digital_max = [info.ad_max_value for info in file_infos]
        prefiltering = [_prefiltering(info.header) for info in file_infos]
        total_channels = len(file_infos)

        if include_events:
            names.append("Events")
            probes.append("")
            units.append("uV")
            analog_min.append(-first.input_range_uv)
            analog_max.append(first.input_range_uv)
            digital_min.append(-first.ad_max_value)
            digital_max.append(first.ad_max_value)
            prefiltering.append("")
            total_channels += 1

        date, time = _parse_creation_datetime(first.header, first.path)
        channel_info = ChannelInfo(
            name=names,
            probe=probes,
            units=units,
            analog_min=analog_min,
            analog_max=analog_max,
            digital_min=digital_min,
            digital_max=digital_max,
            prefiltering=prefiltering,
            number_of_points_per_channel=[first.points] * total_channels,
        )
        header = Header(
            type_before_conversion="ncs",
            name_before_conversion=self._source_folder.name,
            creation_date_before_conversion=date,
            creation_time_before_conversion=time,
            sample_interval_microseconds=1e6 / first.sample_rate,
            sample_rate=first.sample_rate,
            number_of_channels=total_channels,
            number_of_sweeps=1,
            number_of_points_per_sweep=[first.points],
            channel_info=channel_info,
        )
        return header, NcsDataWriter(file_infos, include_events, event_marks)
