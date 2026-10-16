# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

import numpy as np

from ._exceptions import WrongSourceReaderError
from .abstract_source_reader import (
    AbstractDataWriter,
    AbstractSourceReader,
    ChannelPlan,
    ConversionPlan,
    EventPlan,
    SourcePlan,
    SourceRef,
)
from ephyr.core.manifests import SegmentInfo, SegmentKindEnum

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


def _parse_creation_datetime(header: Dict[str, str], fallback: Path) -> datetime:
    raw = header.get("TimeCreated", "")
    for fmt in ("%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            pass
    return datetime.fromtimestamp(fallback.stat().st_mtime)


def _record_timestamps(info: NcsFileInfo) -> np.ndarray:
    return np.asarray(_records_memmap(info)["timestamp"], dtype=np.int64)


def _segments_from_timestamps(timestamps: np.ndarray, sample_rate: float) -> List[SegmentInfo]:
    """Split records where the timestamp jumps by more than a record and a half: acquisition was paused."""
    record_us = _SAMPLES_PER_RECORD * 1_000_000.0 / sample_rate
    deltas = np.diff(timestamps)
    breaks = np.flatnonzero((deltas > 1.5 * record_us) | (deltas < 0)) + 1
    starts = [0, *breaks.tolist()]
    ends = [*breaks.tolist(), int(timestamps.size)]
    t0 = int(timestamps[0])
    return [
        SegmentInfo(
            start_sample_idx=start * _SAMPLES_PER_RECORD,
            number_of_samples=(end - start) * _SAMPLES_PER_RECORD,
            t_start_ms=(int(timestamps[start]) - t0) / 1000.0,
        )
        for start, end in zip(starts, ends)
    ]


def _nev_path(folder: Path) -> Optional[Path]:
    return next((item for item in folder.iterdir() if item.is_file() and item.suffix.lower() == ".nev"), None)


def _parse_nev_events(nev_path: Optional[Path], t0_us: int) -> List[EventPlan]:
    if nev_path is None or nev_path.stat().st_size <= _HEADER_BYTES:
        return []
    data_bytes = nev_path.stat().st_size - _HEADER_BYTES
    if data_bytes % _NEV_RECORD_DTYPE.itemsize != 0:
        return []
    records = np.memmap(
        nev_path,
        dtype=_NEV_RECORD_DTYPE,
        mode="r",
        offset=_HEADER_BYTES,
        shape=(data_bytes // _NEV_RECORD_DTYPE.itemsize,),
    )
    events: List[EventPlan] = []
    for record in records:
        text = bytes(record["event_string"]).split(b"\x00", 1)[0].decode("latin1", errors="ignore").strip()
        t_ms = (int(record["timestamp"]) - t0_us) / 1000.0
        if text.startswith("TTL"):
            events.append(EventPlan(t_ms=t_ms, label="TTL", value=str(int(record["ttl"])),
                                    extra={"event_id": str(int(record["event_id"])), "text": text}))
        elif text:
            events.append(EventPlan(t_ms=t_ms, label=text, extra={"event_id": str(int(record["event_id"]))}))
    return events


class NcsDataWriter(AbstractDataWriter):
    def __init__(self, file_infos: List[NcsFileInfo]):
        self._file_infos = file_infos

    def __iter__(self) -> Iterator[np.ndarray]:
        memmaps = [_records_memmap(info) for info in self._file_infos]
        record_count = self._file_infos[0].record_count
        for record_pos in range(0, record_count, _CHUNK_RECORDS):
            end = min(record_pos + _CHUNK_RECORDS, record_count)
            width = (end - record_pos) * _SAMPLES_PER_RECORD
            chunk = np.zeros((len(self._file_infos), width), dtype=np.int16)
            for ch_idx, (info, records) in enumerate(zip(self._file_infos, memmaps)):
                samples = np.asarray(records[record_pos:end]["samples"], dtype=np.int16).copy()
                valid = np.asarray(records[record_pos:end]["num_valid_samples"], dtype=np.int64)
                for rec_idx, valid_samples in enumerate(valid):
                    if valid_samples < _SAMPLES_PER_RECORD:
                        samples[rec_idx, max(0, int(valid_samples)):] = 0
                if info.input_inverted:
                    samples = (-samples.astype(np.int32)).clip(-32768, 32767).astype(np.int16)
                chunk[ch_idx, :] = samples.reshape(-1)
            yield chunk

    def total_chunks(self) -> int:
        return max(1, (self._file_infos[0].record_count + _CHUNK_RECORDS - 1) // _CHUNK_RECORDS)


class NcsSourceReader(AbstractSourceReader):
    """
    Neuralynx continuous sampled channel files (.ncs).

    Each .ncs file stores one channel as a 16KB ASCII header followed by fixed
    1044-byte records with 512 int16 samples. The recording is the folder with all .ncs files.
    """

    format_name = "ncs"

    @classmethod
    def resolve(cls, path: Path) -> SourceRef:
        files = _list_ordered_ncs_files(path)
        if not files:
            raise WrongSourceReaderError(cls)
        _parse_ncs_file(files[0])
        folder = files[0].parent
        nev = _nev_path(folder)
        return SourceRef(format=cls.format_name, kind="folder", root=folder, name=folder.name,
                         files=files + ([nev] if nev is not None else []))

    def probe(self, scan: bool = False) -> ConversionPlan:
        folder = self.ref.root
        file_infos = [_parse_ncs_file(path) for path in _list_ordered_ncs_files(folder)]
        first = file_infos[0]
        for info in file_infos[1:]:
            if info.record_count != first.record_count:
                raise ValueError("NCS files have different record counts; they cannot form one source.")
            if abs(info.sample_rate - first.sample_rate) > 1e-9:
                raise ValueError("NCS files have inconsistent sampling rates.")

        timestamps = _record_timestamps(first)
        channels = [
            ChannelPlan(
                name=info.header.get("AcqEntName") or info.path.stem,
                units="uV",
                analog_min=-info.input_range_uv,
                analog_max=info.input_range_uv,
                digital_min=-info.ad_max_value,
                digital_max=info.ad_max_value,
                probe=info.header.get("ProbeName", ""),
                prefiltering=_prefiltering(info.header),
            )
            for info in file_infos
        ]
        segments = _segments_from_timestamps(timestamps, first.sample_rate)
        source = SourcePlan(
            source_id="main",
            name="CSC",
            sample_rate=first.sample_rate,
            channels=channels,
            segments=segments,
            segment_kind=SegmentKindEnum.SEGMENT if len(segments) > 1 else SegmentKindEnum.CONTINUOUS,
            source_format=self.format_name,
            writer_factory=lambda: NcsDataWriter(file_infos),
        )
        return ConversionPlan(
            ref=self.ref,
            sources=[source],
            events=_parse_nev_events(_nev_path(folder), int(timestamps[0])),
            start_datetime=_parse_creation_datetime(first.header, first.path).isoformat(),
            recording_name=folder.name,
            reader_options=dict(self._options),
        )
