# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import h5py
import numpy as np

from ephyr.core.header import ChannelInfo, Header, VoltageUnitEnum

from ._exceptions import WrongSourceReaderError
from .abstract_source_reader import AbstractDataWriter, AbstractSourceReader


_CHUNK_SAMPLES = 65536
_MAX_RAW_HEADER_SIZE = 5000
_MCS_RAW_SUFFIXES = {".raw", ".mcsraw"}
_MCS_H5_SUFFIXES = {".h5", ".hdf5"}
_MCS_CMOS_SUFFIXES = {".cmcr", ".cmtr"}
_CMOS_FILE_TYPE_ID = "cabb6cdd-47e0-417a-8e04-5664cbbc449b"
_CMOS_CHANNEL_STREAM_TYPE_ID = "9217aeb4-59a0-4d7f-bdcd-0371c9fd66eb"
_CMOS_SENSOR_STREAM_TYPE_ID = "15e5a1fe-df2f-421b-8b60-23eeb2213c45"


@dataclass(frozen=True)
class MCSRecordingInfo:
    path: Path
    source_type: str
    channel_names: List[str]
    units: List[str]
    gains: np.ndarray
    adc_zero: np.ndarray
    digital_min: List[int]
    digital_max: List[int]
    sample_rate: float
    sample_count: int
    dtype: np.dtype
    header_size: int = 0
    h5_dataset_paths: Tuple[str, ...] = ()
    h5_layout: str = "channels_samples"

    @property
    def channel_count(self) -> int:
        return len(self.channel_names)


def _decode_text(value: Any) -> str:
    if isinstance(value, np.ndarray) and value.size == 1:
        value = value.reshape(-1)[0]
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _h5_attr_text(obj, key: str) -> str:
    return _decode_text(obj.attrs.get(key, "")).rstrip("\x00").strip()


def _digital_ranges(dtype: np.dtype, adc_zero: Sequence[int]) -> Tuple[List[int], List[int]]:
    if not np.issubdtype(dtype, np.integer):
        raise ValueError(f"MCS signal data must have an integer dtype, got {dtype}")
    limits = np.iinfo(dtype)
    digital_min = [max(-32768, int(limits.min) - int(zero)) for zero in adc_zero]
    digital_max = [min(32767, int(limits.max) - int(zero)) for zero in adc_zero]
    return digital_min, digital_max


def _parse_mcs_raw(path: Path) -> MCSRecordingInfo:
    with open(path, "rb") as source:
        raw_header = source.read(_MAX_RAW_HEADER_SIZE)

    end = raw_header.find(b"EOH")
    if end < 0:
        raise ValueError("MCS RAW header has no EOH marker")
    header_size = end + 5  # EOH followed by CR/LF.
    lines = raw_header[:header_size].replace(b"\r", b"").split(b"\n")
    values: Dict[bytes, bytes] = {}
    for line in lines:
        if b" = " not in line:
            continue
        key, value = line.split(b" = ", 1)
        values[key.strip()] = value.strip()

    try:
        sample_rate = float(values[b"Sample rate"])
        adc_zero = int(values[b"ADC zero"])
        channel_names = values[b"Streams"].decode("windows-1252").split(";")
        electrode_scale = values[b"El"].decode("windows-1252").replace("/AD", "")
    except (KeyError, UnicodeDecodeError, ValueError) as exc:
        raise ValueError("Incomplete MCS RAW header") from exc

    channel_names = [name.strip() for name in channel_names if name.strip()]
    if not channel_names or sample_rate <= 0:
        raise ValueError("Invalid MCS RAW channel list or sample rate")

    split_at = 0
    while split_at < len(electrode_scale) and electrode_scale[split_at] in "0123456789.+-eE":
        split_at += 1
    if split_at == 0 or split_at == len(electrode_scale):
        raise ValueError(f"Invalid MCS RAW electrode scale: {electrode_scale}")
    gain = float(electrode_scale[:split_at])
    unit = VoltageUnitEnum.normalize(electrode_scale[split_at:].replace("µ", "u")).value

    dtype = np.dtype("<u2")
    data_bytes = path.stat().st_size - header_size
    frame_bytes = dtype.itemsize * len(channel_names)
    if data_bytes < 0 or data_bytes % frame_bytes:
        raise ValueError("MCS RAW data size is not divisible by its channel count")
    sample_count = data_bytes // frame_bytes
    zeros = np.full(len(channel_names), adc_zero, dtype=np.int64)
    digital_min, digital_max = _digital_ranges(dtype, zeros)
    return MCSRecordingInfo(
        path=path,
        source_type="mcs_raw",
        channel_names=channel_names,
        units=[unit] * len(channel_names),
        gains=np.full(len(channel_names), gain, dtype=np.float64),
        adc_zero=zeros,
        digital_min=digital_min,
        digital_max=digital_max,
        sample_rate=sample_rate,
        sample_count=sample_count,
        dtype=dtype,
        header_size=header_size,
    )


def _parse_mcs_h5(path: Path, stream_id: int) -> MCSRecordingInfo:
    stream_path = f"/Data/Recording_0/AnalogStream/Stream_{stream_id}"
    with h5py.File(path, "r") as source:
        if stream_path not in source:
            available_path = "/Data/Recording_0/AnalogStream"
            available = list(source[available_path].keys()) if available_path in source else []
            raise ValueError(f"MCS HDF5 stream {stream_id} is unavailable; found {available}")
        stream = source[stream_path]
        if "ChannelData" not in stream or "InfoChannel" not in stream:
            raise ValueError("Invalid MCS HDF5 analog stream")

        data = stream["ChannelData"]
        info = np.asarray(stream["InfoChannel"])
        if data.ndim != 2 or info.ndim != 1 or data.shape[0] != info.size:
            raise ValueError("MCS HDF5 channel metadata does not match ChannelData")
        required_fields = {"ChannelID", "Label", "Unit", "Tick", "Exponent", "ConversionFactor", "ADZero"}
        if info.dtype.names is None or not required_fields.issubset(info.dtype.names):
            raise ValueError("MCS HDF5 InfoChannel is missing required fields")

        ticks = np.asarray(info["Tick"], dtype=np.float64)
        if np.any(ticks <= 0) or not np.allclose(ticks, ticks[0]):
            raise ValueError("MCS HDF5 channels have invalid or inconsistent ticks")
        sample_rate = 1_000_000.0 / float(ticks[0])

        channel_ids = [_decode_text(value) for value in info["ChannelID"]]
        labels = [_decode_text(value).strip() for value in info["Label"]]
        channel_names = [label or f"Ch{channel_id}" for label, channel_id in zip(labels, channel_ids)]
        if len(set(channel_names)) != len(channel_names):
            channel_names = [f"{name}__{index}" for index, name in enumerate(channel_names)]

        units = [VoltageUnitEnum.normalize(_decode_text(value)).value for value in info["Unit"]]
        gains = np.asarray(info["ConversionFactor"], dtype=np.float64) * np.power(
            10.0, np.asarray(info["Exponent"], dtype=np.float64)
        )
        zeros = np.asarray(info["ADZero"], dtype=np.int64)
        dtype = np.dtype(data.dtype)
        digital_min, digital_max = _digital_ranges(dtype, zeros)
        sample_count = int(data.shape[1])

    return MCSRecordingInfo(
        path=path,
        source_type="mcs_h5",
        channel_names=channel_names,
        units=units,
        gains=gains,
        adc_zero=zeros,
        digital_min=digital_min,
        digital_max=digital_max,
        sample_rate=sample_rate,
        sample_count=sample_count,
        dtype=dtype,
        h5_dataset_paths=(f"{stream_path}/ChannelData",),
    )


def _cmos_streams(acquisition: h5py.Group, type_id: str) -> List[h5py.Group]:
    streams = [
        value
        for value in acquisition.values()
        if isinstance(value, h5py.Group) and _h5_attr_text(value, "ID.TypeID") == type_id
    ]
    return sorted(streams, key=lambda stream: stream.name)


def _choose_cmos_stream(acquisition: h5py.Group, options: Dict[str, Any]) -> h5py.Group:
    sensor_streams = _cmos_streams(acquisition, _CMOS_SENSOR_STREAM_TYPE_ID)
    channel_streams = _cmos_streams(acquisition, _CMOS_CHANNEL_STREAM_TYPE_ID)
    streams = sensor_streams + channel_streams
    if not streams:
        raise ValueError("CMOS-MEA file contains no continuous sensor or channel streams")

    requested_name = options.get("stream_name")
    if requested_name is not None:
        for stream in streams:
            if stream.name.rsplit("/", 1)[-1] == str(requested_name):
                return stream
        raise ValueError(f"CMOS-MEA stream is unavailable: {requested_name}")

    requested_id = options.get("mcs_stream_id", options.get("stream_id"))
    if requested_id is not None:
        index = int(requested_id)
        if index < 0 or index >= len(streams):
            raise ValueError(f"CMOS-MEA stream index is unavailable: {index}")
        return streams[index]

    # The sensor stream is the primary electrophysiology signal in CMOS-MEA files.
    return streams[0]


def _parse_cmos_sensor_stream(path: Path, stream: h5py.Group) -> MCSRecordingInfo:
    if "SensorMeta" not in stream:
        raise ValueError("CMOS-MEA sensor stream has no SensorMeta")
    metadata = np.asarray(stream["SensorMeta"])
    required = {
        "RegionID",
        "GroupID",
        "Label",
        "Unit",
        "Exponent",
        "Tick",
        "ADCBits",
        "Region.Left",
        "Region.Top",
        "Region.Right",
        "Region.Bottom",
        "Conversion Factors",
    }
    if metadata.dtype.names is None or not required.issubset(metadata.dtype.names):
        raise ValueError("CMOS-MEA SensorMeta is missing required fields")

    group_ids = np.unique(metadata["GroupID"])
    if group_ids.size != 1:
        raise ValueError("CMOS-MEA files with multiple sensor sweeps are not supported")

    ticks = np.asarray(metadata["Tick"], dtype=np.float64)
    if np.any(ticks <= 0) or not np.allclose(ticks, ticks[0]):
        raise ValueError("CMOS-MEA sensor regions have inconsistent ticks")

    dataset_paths: List[str] = []
    channel_names: List[str] = []
    units: List[str] = []
    gains: List[float] = []
    dtypes: List[np.dtype] = []
    sample_count: Optional[int] = None

    rows_by_region = {int(row["RegionID"]): row for row in metadata}
    for region_id in sorted(rows_by_region):
        row = rows_by_region[region_id]
        group_id = int(row["GroupID"])
        dataset_name = f"SensorData {region_id} {group_id}"
        if dataset_name not in stream:
            raise ValueError(f"CMOS-MEA sensor dataset is missing: {dataset_name}")
        dataset = stream[dataset_name]
        if dataset.ndim != 3:
            raise ValueError(f"CMOS-MEA sensor dataset must be three-dimensional: {dataset.name}")

        left, top = int(row["Region.Left"]), int(row["Region.Top"])
        right, bottom = int(row["Region.Right"]), int(row["Region.Bottom"])
        width, height = right - left + 1, bottom - top + 1
        if dataset.shape[1:] != (width, height):
            raise ValueError(f"CMOS-MEA sensor region dimensions do not match metadata: {dataset.name}")
        if sample_count is None:
            sample_count = int(dataset.shape[0])
        elif dataset.shape[0] != sample_count:
            raise ValueError("CMOS-MEA sensor regions have different sample counts")

        factors_text = _decode_text(row["Conversion Factors"]).strip()
        factors = np.fromstring(factors_text, sep=" ", dtype=np.float64)
        if factors.size != width * height:
            raise ValueError(f"CMOS-MEA conversion-factor count does not match region: {dataset.name}")
        exponent = int(row["Exponent"])
        gains.extend((factors * (10.0 ** exponent)).tolist())
        unit = VoltageUnitEnum.normalize(_decode_text(row["Unit"])).value
        units.extend([unit] * factors.size)

        region_label = _decode_text(row["Label"]).strip() or f"ROI_{region_id}"
        for x in range(left, right + 1):
            for y in range(top, bottom + 1):
                channel_names.append(f"{region_label}__X{x}_Y{y}")
        dataset_paths.append(dataset.name)
        dtypes.append(np.dtype(dataset.dtype))

    if sample_count is None or not dtypes:
        raise ValueError("CMOS-MEA sensor stream contains no data")
    if any(dtype != dtypes[0] for dtype in dtypes[1:]):
        raise ValueError("CMOS-MEA sensor regions have inconsistent dtypes")
    dtype = dtypes[0]
    zeros = np.zeros(len(channel_names), dtype=np.int64)
    digital_min, digital_max = _digital_ranges(dtype, zeros)
    return MCSRecordingInfo(
        path=path,
        source_type=f"mcs_{path.suffix.lower().lstrip('.')}",
        channel_names=channel_names,
        units=units,
        gains=np.asarray(gains, dtype=np.float64),
        adc_zero=zeros,
        digital_min=digital_min,
        digital_max=digital_max,
        sample_rate=1_000_000.0 / float(ticks[0]),
        sample_count=sample_count,
        dtype=dtype,
        h5_dataset_paths=tuple(dataset_paths),
        h5_layout="samples_grid",
    )


def _parse_cmos_channel_stream(path: Path, stream: h5py.Group) -> MCSRecordingInfo:
    if "ChannelMeta" not in stream:
        raise ValueError("CMOS-MEA channel stream has no ChannelMeta")
    metadata = np.asarray(stream["ChannelMeta"])
    required = {"ChannelID", "GroupID", "Label", "Unit", "Exponent", "Tick", "ConversionFactor"}
    if metadata.dtype.names is None or not required.issubset(metadata.dtype.names):
        raise ValueError("CMOS-MEA ChannelMeta is missing required fields")

    group_ids = np.unique(metadata["GroupID"])
    if group_ids.size != 1:
        raise ValueError("CMOS-MEA files with multiple channel sweeps are not supported")
    group_id = int(group_ids[0])
    dataset_name = f"ChannelData {group_id}"
    if dataset_name not in stream:
        raise ValueError(f"CMOS-MEA channel dataset is missing: {dataset_name}")
    dataset = stream[dataset_name]
    if dataset.ndim != 2 or dataset.shape[0] != metadata.size:
        raise ValueError("CMOS-MEA ChannelData does not match ChannelMeta")

    ticks = np.asarray(metadata["Tick"], dtype=np.float64)
    if np.any(ticks <= 0) or not np.allclose(ticks, ticks[0]):
        raise ValueError("CMOS-MEA channels have inconsistent ticks")
    names = [
        _decode_text(row["Label"]).strip() or f"Ch{int(row['ChannelID'])}"
        for row in metadata
    ]
    units = [VoltageUnitEnum.normalize(_decode_text(row["Unit"])).value for row in metadata]
    gains = np.asarray(metadata["ConversionFactor"], dtype=np.float64) * np.power(
        10.0, np.asarray(metadata["Exponent"], dtype=np.float64)
    )
    dtype = np.dtype(dataset.dtype)
    zeros = np.zeros(metadata.size, dtype=np.int64)
    digital_min, digital_max = _digital_ranges(dtype, zeros)
    return MCSRecordingInfo(
        path=path,
        source_type=f"mcs_{path.suffix.lower().lstrip('.')}",
        channel_names=names,
        units=units,
        gains=gains,
        adc_zero=zeros,
        digital_min=digital_min,
        digital_max=digital_max,
        sample_rate=1_000_000.0 / float(ticks[0]),
        sample_count=int(dataset.shape[1]),
        dtype=dtype,
        h5_dataset_paths=(dataset.name,),
    )


def _parse_mcs_cmos(path: Path, options: Dict[str, Any]) -> MCSRecordingInfo:
    with h5py.File(path, "r") as source:
        if _h5_attr_text(source, "ID.TypeID") != _CMOS_FILE_TYPE_ID:
            raise ValueError("Not an MCS CMOS-MEA HDF5 file")
        try:
            acquisition = source["Acquisition"]
        except KeyError as exc:
            if path.suffix.lower() == ".cmtr":
                raise ValueError(
                    "CMTR Acquisition link cannot be resolved; keep the source CMCR file next to the CMTR file"
                ) from exc
            raise ValueError("CMOS-MEA file has no Acquisition group") from exc

        stream = _choose_cmos_stream(acquisition, options)
        stream_type = _h5_attr_text(stream, "ID.TypeID")
        if stream_type == _CMOS_SENSOR_STREAM_TYPE_ID:
            return _parse_cmos_sensor_stream(path, stream)
        return _parse_cmos_channel_stream(path, stream)


def _parse_mcs(path: Path, options: Dict[str, Any]) -> MCSRecordingInfo:
    suffix = path.suffix.lower()
    if suffix in _MCS_RAW_SUFFIXES:
        return _parse_mcs_raw(path)
    if suffix in _MCS_H5_SUFFIXES:
        stream_id = options.get("mcs_stream_id", options.get("stream_id", 0))
        return _parse_mcs_h5(path, int(stream_id))
    if suffix in _MCS_CMOS_SUFFIXES:
        return _parse_mcs_cmos(path, options)
    raise ValueError(f"Unsupported Multi Channel Systems file extension: {suffix}")


class MCSDataWriter(AbstractDataWriter):
    def __init__(self, info: MCSRecordingInfo, chunk_samples: int = _CHUNK_SAMPLES):
        self._info = info
        # CMOS sensor recordings can have thousands of channels. Keep temporary
        # int64 conversion buffers bounded instead of allocating hundreds of MB.
        adaptive_samples = max(1, 4_000_000 // max(1, info.channel_count))
        self._chunk_samples = min(chunk_samples, adaptive_samples)
        self._sample_position = 0
        self._raw_data: Optional[np.memmap] = None
        self._h5_file: Optional[h5py.File] = None
        self._h5_data: List[h5py.Dataset] = []

    def __iter__(self) -> "MCSDataWriter":
        self._close()
        self._sample_position = 0
        if self._info.source_type == "mcs_raw":
            self._raw_data = np.memmap(
                self._info.path,
                dtype=self._info.dtype,
                mode="r",
                offset=self._info.header_size,
                shape=(self._info.sample_count, self._info.channel_count),
            )
        else:
            self._h5_file = h5py.File(self._info.path, "r")
            self._h5_data = [
                self._h5_file[dataset_path] for dataset_path in self._info.h5_dataset_paths
            ]
        return self

    def __next__(self) -> np.ndarray:
        if self._sample_position >= self._info.sample_count:
            self._close()
            raise StopIteration

        end = min(self._sample_position + self._chunk_samples, self._info.sample_count)
        if self._raw_data is not None:
            values = np.asarray(self._raw_data[self._sample_position:end, :]).T
        elif self._h5_data:
            if self._info.h5_layout == "samples_grid":
                blocks = [
                    np.asarray(dataset[self._sample_position:end, ...]).reshape(
                        end - self._sample_position, -1
                    ).T
                    for dataset in self._h5_data
                ]
                values = np.vstack(blocks)
            else:
                values = np.asarray(self._h5_data[0][:, self._sample_position:end])
        else:
            raise RuntimeError("MCSDataWriter must be iterated before reading")

        values = values.astype(np.int64) - self._info.adc_zero[:, None]
        result = np.clip(values, -32768, 32767).astype(np.int16)
        self._sample_position = end
        return result

    def total_chunks(self, header: Header) -> int:
        return (self._info.sample_count + self._chunk_samples - 1) // self._chunk_samples

    def _close(self) -> None:
        self._raw_data = None
        self._h5_data = []
        if self._h5_file is not None:
            self._h5_file.close()
            self._h5_file = None

    def __del__(self):
        self._close()


class MCSSourceReader(AbstractSourceReader):
    """Read MCS RAW, DataManager HDF5, and CMOS-MEA CMCR/CMTR files."""

    def __init__(self, experiment_path: Path):
        super().__init__(experiment_path)
        self._yielded = False
        self._options: Dict[str, Any] = {}

    @classmethod
    def _try_to_open(cls, experiment_path: Path) -> None:
        path = Path(experiment_path)
        supported_suffixes = _MCS_RAW_SUFFIXES | _MCS_H5_SUFFIXES | _MCS_CMOS_SUFFIXES
        if not path.is_file() or path.suffix.lower() not in supported_suffixes:
            raise WrongSourceReaderError(cls)
        try:
            _parse_mcs(path, {})
        except Exception:
            raise WrongSourceReaderError(cls)

    def __iter__(self) -> "MCSSourceReader":
        self._yielded = False
        return self

    def __next__(self) -> Tuple[Header, MCSDataWriter]:
        if self._yielded:
            raise StopIteration
        self._yielded = True

        path = Path(self._experiment_path)
        info = _parse_mcs(path, self._options)
        analog_min = (np.asarray(info.digital_min) * info.gains).tolist()
        analog_max = (np.asarray(info.digital_max) * info.gains).tolist()
        channel_info = ChannelInfo(
            name=info.channel_names,
            probe=[""] * info.channel_count,
            units=info.units,
            analog_min=analog_min,
            analog_max=analog_max,
            digital_min=info.digital_min,
            digital_max=info.digital_max,
            prefiltering=[""] * info.channel_count,
            number_of_points_per_channel=[info.sample_count] * info.channel_count,
        )

        created = datetime.fromtimestamp(path.stat().st_mtime)
        header = Header(
            type_before_conversion=info.source_type,
            name_before_conversion=path.name,
            creation_date_before_conversion=str(created.date()),
            creation_time_before_conversion=str(created.time()),
            sample_interval_microseconds=1e6 / info.sample_rate,
            sample_rate=info.sample_rate,
            number_of_channels=info.channel_count,
            number_of_sweeps=1,
            number_of_points_per_sweep=[info.sample_count],
            channel_info=channel_info,
        )
        return header, MCSDataWriter(info)

    def set_conversion_options(self, options: Optional[Dict[str, Any]] = None) -> None:
        self._options = dict(options or {})
