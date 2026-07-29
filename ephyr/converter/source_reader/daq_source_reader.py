from __future__ import annotations

import math
import re
import struct
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import BinaryIO, List, Optional, Tuple

import numpy as np

from ._exceptions import WrongSourceReaderError
from .abstract_source_reader import AbstractDataWriter, AbstractSourceReader
from ephyr.core.header import ChannelInfo, Header

_DAQ_SIGNATURE = b"MATLAB Data Acquisition File.\x00\x19\x00"
_CHUNK_SAMPLES = 512
_DIGITAL_MIN = -32768
_DIGITAL_MAX = 32767


@dataclass(frozen=True)
class DaqBlockChart:
    first_header_offset: int
    positions: List[int]
    block_sizes: List[int]
    block_types: List[int]
    header_sizes: List[int]


@dataclass(frozen=True)
class DaqChannel:
    hw_channel: int
    units: str
    input_range: Tuple[float, float]


@dataclass(frozen=True)
class DaqMetadata:
    creation_datetime: datetime
    sample_rate: float
    samples_acquired: int
    samples_per_trigger: Optional[int]
    native_dtype: np.dtype
    channels: List[DaqChannel]
    chart: DaqBlockChart


def _read_exact(fid: BinaryIO, size: int) -> bytes:
    data = fid.read(size)
    if len(data) != size:
        raise EOFError("Unexpected end of DAQ file")
    return data


def _read_i32(fid: BinaryIO) -> int:
    return struct.unpack("<i", _read_exact(fid, 4))[0]


def _read_u32(fid: BinaryIO) -> int:
    return struct.unpack("<I", _read_exact(fid, 4))[0]


def _read_i64(fid: BinaryIO) -> int:
    return struct.unpack("<q", _read_exact(fid, 8))[0]


def _decode_ascii(data: bytes) -> str:
    return data.decode("latin1", errors="replace")


def _clean_type_name(data: bytes) -> str:
    return _decode_ascii(data).replace("\x00", " ").strip()


def _matlab_field_value(text: str, field: str) -> Optional[str]:
    patterns = [
        rf"(?:^|[;\s])x\.{re.escape(field)}\s*=\s*(.*?);",
        rf"'{re.escape(field)}'\s*,\s*(.*?)(?:,|\))",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()
    return None


def _parse_float(text: str, field: str) -> float:
    value = _matlab_field_value(text, field)
    if value is None:
        raise ValueError(f"DAQ header is missing {field}")
    value = value.strip()
    if value.lower() == "inf":
        return math.inf
    return float(value)


def _parse_int(text: str, field: str, default: Optional[int] = None) -> int:
    value = _matlab_field_value(text, field)
    if value is None:
        if default is not None:
            return default
        raise ValueError(f"DAQ header is missing {field}")
    return int(float(value.strip()))


def _parse_string(text: str, field: str, default: str = "") -> str:
    value = _matlab_field_value(text, field)
    if value is None:
        return default
    value = value.strip()
    quoted = re.match(r"^'(.*)'$", value, flags=re.DOTALL)
    if quoted:
        value = quoted.group(1).replace("''", "'")
    return value.strip()


def _parse_float_vector(text: str, field: str) -> Tuple[float, ...]:
    value = _matlab_field_value(text, field)
    if value is None:
        raise ValueError(f"DAQ header is missing {field}")
    raw = value.strip()
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]
    nums = [float(item) for item in re.findall(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?|inf", raw)]
    return tuple(nums)


def _daq_dtype(native_type: str) -> np.dtype:
    aliases = {
        "single": np.dtype("<f4"),
        "float32": np.dtype("<f4"),
        "double": np.dtype("<f8"),
        "float64": np.dtype("<f8"),
        "int16": np.dtype("<i2"),
        "uint16": np.dtype("<u2"),
        "int32": np.dtype("<i4"),
        "uint32": np.dtype("<u4"),
    }
    dtype = aliases.get(native_type.strip().lower())
    if dtype is None:
        raise ValueError(f"Unsupported DAQ native data type: {native_type}")
    return dtype


def _creation_datetime(values: Tuple[float, ...], fallback: Path) -> datetime:
    try:
        year, month, day, hour, minute, second = values
        whole_second = int(second)
        microsecond = int(round((float(second) - whole_second) * 1_000_000))
        return datetime(
            int(year),
            int(month),
            int(day),
            int(hour),
            int(minute),
            whole_second,
            microsecond,
        )
    except Exception:
        return datetime.fromtimestamp(fallback.stat().st_mtime)


def _read_final_info(fid: BinaryIO, file_size: int) -> Tuple[int, int]:
    if file_size < 16:
        raise ValueError("DAQ file is too small")
    fid.seek(file_size - 16)
    samples_acquired = _read_i64(fid)
    last_header_location = _read_i64(fid)
    if samples_acquired < 0 or last_header_location <= 0 or last_header_location >= file_size:
        raise ValueError("DAQ footer is invalid")

    pos = last_header_location
    block_number = -1
    for _ in range(3):
        fid.seek(pos)
        block_size = _read_i32(fid)
        _read_i32(fid)  # block type
        header_size = _read_i32(fid)
        block_number = _read_u32(fid)
        if block_size <= 0 or header_size <= 0 or header_size > block_size:
            raise ValueError("DAQ final header block is invalid")
        pos += block_size
    return int(samples_acquired), int(block_number) + 1


def _read_chart(fid: BinaryIO, start_pos: int, end_pos: int, max_blocks: int) -> DaqBlockChart:
    positions: List[int] = []
    block_sizes: List[int] = []
    block_types: List[int] = []
    header_sizes: List[int] = []

    pos = start_pos
    first_header_offset: Optional[int] = None
    while pos < end_pos and len(positions) < max_blocks:
        fid.seek(pos)
        block_size = _read_i32(fid)
        if block_size <= 0:
            break
        block_type = _read_i32(fid)
        header_size = _read_i32(fid)
        _ = _read_u32(fid)  # block number
        if header_size <= 0 or header_size > block_size:
            raise ValueError("DAQ block header is invalid")
        if first_header_offset is None:
            first_header_offset = fid.tell() - pos
        positions.append(pos)
        block_sizes.append(block_size)
        block_types.append(block_type)
        header_sizes.append(header_size)
        pos += block_size

    if first_header_offset is None:
        raise ValueError("DAQ file contains no chart blocks")
    return DaqBlockChart(first_header_offset, positions, block_sizes, block_types, header_sizes)


def _read_header_blocks(fid: BinaryIO, chart: DaqBlockChart) -> List[Tuple[str, str]]:
    headers: List[Tuple[str, str]] = []
    for pos, block_size, block_type, header_size in zip(
        chart.positions,
        chart.block_sizes,
        chart.block_types,
        chart.header_sizes,
    ):
        if block_type != 0:
            continue
        fid.seek(pos + chart.first_header_offset)
        type_name = _clean_type_name(_read_exact(fid, 16))
        fid.seek(pos + header_size)
        data = _decode_ascii(_read_exact(fid, block_size - header_size))
        headers.append((type_name, data))
    return headers


def _parse_daq_metadata(experiment_path: Path) -> DaqMetadata:
    with open(experiment_path, "rb") as fid:
        signature = _read_exact(fid, 32)
        if signature != _DAQ_SIGNATURE:
            raise WrongSourceReaderError(DaqSourceReader)

        header_size = _read_i32(fid)
        _ = struct.unpack("<hh", _read_exact(fid, 4))  # file version
        creation_values = struct.unpack("<6d", _read_exact(fid, 48))
        _ = struct.unpack("<d", _read_exact(fid, 8))  # engine offset

        file_size = experiment_path.stat().st_size
        samples_acquired, num_blocks = _read_final_info(fid, file_size)
        fid.seek(file_size - 8)
        last_header_location = _read_i64(fid)
        chart = _read_chart(fid, header_size, last_header_location, max(num_blocks - 4, 1))
        headers = _read_header_blocks(fid, chart)

    obj_text = ""
    hw_text = ""
    channel_texts: List[str] = []
    for type_name, text in headers:
        normalized = type_name.replace("\x00", "").strip().lower()
        if normalized in {"analog input", "analoginput"}:
            obj_text = text
        elif normalized == "daqhwinfo":
            hw_text = text
        elif normalized == "channel":
            channel_texts.append(text)

    if not obj_text or not hw_text or not channel_texts:
        raise ValueError("DAQ file does not contain required AnalogInput, DaqHwInfo, and Channel headers")

    sample_rate = _parse_float(obj_text, "SampleRate")
    samples_per_trigger_float = _parse_float(obj_text, "SamplesPerTrigger")
    samples_per_trigger = None if math.isinf(samples_per_trigger_float) else int(samples_per_trigger_float)
    if sample_rate <= 0:
        raise ValueError("DAQ file has invalid sample rate")
    if samples_per_trigger is not None and samples_per_trigger <= 0:
        raise ValueError("DAQ file has invalid SamplesPerTrigger")

    native_dtype = _daq_dtype(_parse_string(hw_text, "NativeDataType", "single"))
    channels = []
    for idx, text in enumerate(channel_texts):
        input_range = _parse_float_vector(text, "InputRange")
        if len(input_range) != 2 or input_range[0] == input_range[1]:
            raise ValueError("DAQ channel has invalid InputRange")
        channels.append(
            DaqChannel(
                hw_channel=_parse_int(text, "HwChannel", idx),
                units=_parse_string(text, "Units", ""),
                input_range=(float(input_range[0]), float(input_range[1])),
            )
        )

    if samples_acquired <= 0:
        raise ValueError("DAQ file contains no acquired samples")

    return DaqMetadata(
        creation_datetime=_creation_datetime(creation_values, experiment_path),
        sample_rate=sample_rate,
        samples_acquired=samples_acquired,
        samples_per_trigger=samples_per_trigger,
        native_dtype=native_dtype,
        channels=channels,
        chart=chart,
    )


def _points_per_sweep(metadata: DaqMetadata) -> List[int]:
    samples_per_trigger = metadata.samples_per_trigger
    if samples_per_trigger is None:
        return [metadata.samples_acquired]
    full_sweeps, remainder = divmod(metadata.samples_acquired, samples_per_trigger)
    points = [samples_per_trigger] * full_sweeps
    if remainder:
        points.append(remainder)
    return points or [metadata.samples_acquired]


class DaqDataWriter(AbstractDataWriter):
    def __init__(self, experiment_path: Path, metadata: DaqMetadata):
        self._experiment_path = experiment_path
        self._metadata = metadata
        self._data_block_indexes = [
            idx for idx, block_type in enumerate(metadata.chart.block_types) if block_type == 1
        ]
        self._block_idx = 0
        self._fid: Optional[BinaryIO] = None

    def __iter__(self) -> "DaqDataWriter":
        self._block_idx = 0
        self._fid = open(self._experiment_path, "rb")
        return self

    def __next__(self) -> np.ndarray:
        if self._fid is None:
            self._fid = open(self._experiment_path, "rb")
        if self._block_idx >= len(self._data_block_indexes):
            self._fid.close()
            self._fid = None
            raise StopIteration

        chart_idx = self._data_block_indexes[self._block_idx]
        self._block_idx += 1

        chart = self._metadata.chart
        pos = chart.positions[chart_idx]
        block_size = chart.block_sizes[chart_idx]
        header_size = chart.header_sizes[chart_idx]
        n_channels = len(self._metadata.channels)
        dtype = self._metadata.native_dtype
        payload_bytes = block_size - header_size
        n_values = payload_bytes // dtype.itemsize
        n_samples = n_values // n_channels
        if n_samples <= 0:
            return self.__next__()

        self._fid.seek(pos + header_size)
        values = np.fromfile(self._fid, dtype=dtype, count=n_samples * n_channels)
        if values.size != n_samples * n_channels:
            raise EOFError("DAQ data block ended unexpectedly")
        block = values.reshape(n_samples, n_channels)

        ranges = np.asarray(
            [channel.input_range[1] - channel.input_range[0] for channel in self._metadata.channels],
            dtype=np.float64,
        )
        scaled = np.rint(block.astype(np.float64) * (2 ** 16) / ranges[np.newaxis, :])
        np.clip(scaled, _DIGITAL_MIN, _DIGITAL_MAX, out=scaled)
        return scaled.T.astype(np.int16)

    def total_chunks(self, header: Header) -> int:
        total_points = sum(header.number_of_points_per_sweep)
        return max(1, (total_points + _CHUNK_SAMPLES - 1) // _CHUNK_SAMPLES)


class DaqSourceReader(AbstractSourceReader):
    def __init__(self, experiment_path: Path):
        super().__init__(experiment_path)
        self._yielded = False

    @classmethod
    def _try_to_open(cls, experiment_path: Path) -> None:
        if not experiment_path.is_file() or experiment_path.suffix.lower() != ".daq":
            raise WrongSourceReaderError(cls)
        try:
            _parse_daq_metadata(experiment_path)
        except WrongSourceReaderError:
            raise
        except Exception:
            raise WrongSourceReaderError(cls)

    def __iter__(self) -> "DaqSourceReader":
        self._yielded = False
        return self

    def __next__(self) -> Tuple[Header, DaqDataWriter]:
        if self._yielded:
            raise StopIteration
        self._yielded = True

        metadata = _parse_daq_metadata(self._experiment_path)
        points_per_sweep = _points_per_sweep(metadata)
        total_points = sum(points_per_sweep)

        channel_info = ChannelInfo(
            name=[f"Ch{channel.hw_channel}" for channel in metadata.channels],
            probe=[""] * len(metadata.channels),
            units=[channel.units for channel in metadata.channels],
            analog_min=[channel.input_range[0] for channel in metadata.channels],
            analog_max=[channel.input_range[1] for channel in metadata.channels],
            digital_min=[_DIGITAL_MIN] * len(metadata.channels),
            digital_max=[_DIGITAL_MAX] * len(metadata.channels),
            prefiltering=[""] * len(metadata.channels),
            number_of_points_per_channel=[total_points] * len(metadata.channels),
        )

        header = Header(
            type_before_conversion="daq",
            name_before_conversion=self._experiment_path.name,
            creation_date_before_conversion=str(metadata.creation_datetime.date()),
            creation_time_before_conversion=str(metadata.creation_datetime.time()),
            sample_interval_microseconds=1e6 / metadata.sample_rate,
            sample_rate=metadata.sample_rate,
            number_of_channels=len(metadata.channels),
            number_of_sweeps=len(points_per_sweep),
            number_of_points_per_sweep=points_per_sweep,
            channel_info=channel_info,
        )
        return header, DaqDataWriter(self._experiment_path, metadata)
