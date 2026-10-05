# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import struct
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
_MCS_MCD_SUFFIXES = {".mcd"}
_MCD_MAGIC = b"MCSSTRM "
_MCD_HEADER_LIST = b"LISThdr "
_MCD_CHUNK = struct.Struct("<8sq")
_MCD_BLOCK_TIMES = struct.Struct("<qq")
# Fixed MC_Rack STRMHDR layout: stream properties followed by 1104-byte channel records.
_MCD_STREAM_KIND = slice(2, 11)
_MCD_STREAM_RATE_COUNT_OFFSET = 784
_MCD_STREAM_ID = slice(792, 800)
_MCD_CHANNEL_RECORDS_OFFSET = 804
_MCD_CHANNEL_RECORD_SIZE = 1104
_MCD_CHANNEL_NAME = slice(12, 788)
_MCD_CHANNEL_LABEL = slice(790, 1048)
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
    sweep_sample_counts: Tuple[int, ...] = ()
    mcd_channel_counts: Tuple[int, ...] = ()
    # (blocks, streams) byte offsets of interleaved uint16 frames and samples per block.
    mcd_block_offsets: Optional[np.ndarray] = None
    mcd_block_samples: Optional[np.ndarray] = None

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


@dataclass(frozen=True)
class _MCDStream:
    stream_id: str
    kind: str
    channel_labels: List[str]
    sample_rate: float
    bits: int
    adc_zero: int
    gain_volts: float


def _c_string(data: bytes) -> str:
    return data.split(b"\x00", 1)[0].decode("windows-1252", errors="replace").strip()


def _parse_mcd_stream(stream_header: bytes, stream_format: bytes) -> _MCDStream:
    if len(stream_header) < _MCD_CHANNEL_RECORDS_OFFSET or len(stream_format) < 16:
        raise ValueError("MCD stream header is truncated")
    rate_millihertz, channel_count = struct.unpack_from("<ii", stream_header, _MCD_STREAM_RATE_COUNT_OFFSET)
    records_end = _MCD_CHANNEL_RECORDS_OFFSET + channel_count * _MCD_CHANNEL_RECORD_SIZE
    if rate_millihertz <= 0 or channel_count <= 0 or len(stream_header) < records_end:
        raise ValueError("MCD stream header has an invalid sample rate or channel list")

    labels: List[Optional[str]] = [None] * channel_count
    for record_index in range(channel_count):
        start = _MCD_CHANNEL_RECORDS_OFFSET + record_index * _MCD_CHANNEL_RECORD_SIZE
        record = stream_header[start:start + _MCD_CHANNEL_RECORD_SIZE]
        data_index = struct.unpack_from("<i", record, 4)[0]
        if not 0 <= data_index < channel_count or labels[data_index] is not None:
            raise ValueError("MCD channel records have invalid data indices")
        labels[data_index] = (
            _c_string(record[_MCD_CHANNEL_LABEL])
            or _c_string(record[_MCD_CHANNEL_NAME])
            or f"Ch{data_index}"
        )

    bits, adc_zero = struct.unpack_from("<HH", stream_format, 4)
    gain_volts = struct.unpack_from("<d", stream_format, 8)[0]
    return _MCDStream(
        stream_id=stream_header[_MCD_STREAM_ID].decode("ascii", errors="replace"),
        kind=_c_string(stream_header[_MCD_STREAM_KIND]),
        channel_labels=[str(label) for label in labels],
        sample_rate=rate_millihertz / 1000.0,
        bits=int(bits),
        adc_zero=int(adc_zero),
        gain_volts=float(gain_volts),
    )


def _parse_mcd_header(source, file_size: int) -> Tuple[List[_MCDStream], int]:
    source.seek(0)
    magic, _ = _MCD_CHUNK.unpack(source.read(_MCD_CHUNK.size))
    if magic != _MCD_MAGIC:
        raise ValueError("Not an MC_Rack MCD file")
    tag, size = _MCD_CHUNK.unpack(source.read(_MCD_CHUNK.size))
    data_start = 2 * _MCD_CHUNK.size + size
    if tag != _MCD_HEADER_LIST or size <= 0 or data_start > file_size:
        raise ValueError("MCD file has no valid header list")
    header = source.read(size)

    streams: List[_MCDStream] = []
    pending_header: Optional[bytes] = None
    position = 0
    while position + _MCD_CHUNK.size <= len(header):
        tag, size = _MCD_CHUNK.unpack_from(header, position)
        payload_start = position + _MCD_CHUNK.size
        if size < 0 or payload_start + size > len(header):
            raise ValueError("MCD header chunk is truncated")
        payload = header[payload_start:payload_start + size]
        if tag == b"STRMHDR ":
            pending_header = payload
        elif tag == b"STRMFMT " and pending_header is not None:
            streams.append(_parse_mcd_stream(pending_header, payload))
            pending_header = None
        position = payload_start + size
    return streams, data_start


def _select_mcd_streams(streams: Sequence[_MCDStream], options: Dict[str, Any]) -> List[_MCDStream]:
    requested_name = options.get("stream_name")
    if requested_name is not None:
        selected = [stream for stream in streams if stream.stream_id == str(requested_name)]
        if not selected:
            raise ValueError(f"MCD stream is unavailable: {requested_name}")
    else:
        # Digital, trigger and spike-cutout streams are not continuous voltage signals.
        selected = [stream for stream in streams if stream.kind == "analog" and stream.gain_volts > 0]
        if not selected:
            raise ValueError("MCD file contains no continuous analog streams")
    if any(stream.sample_rate != selected[0].sample_rate for stream in selected[1:]):
        raise ValueError("MCD analog streams have different sample rates")
    if any(stream.bits != 16 for stream in selected):
        raise ValueError("Only 16-bit MCD analog streams are supported")
    return selected


def _parse_mcs_mcd(path: Path, options: Dict[str, Any]) -> MCSRecordingInfo:
    file_size = path.stat().st_size
    with open(path, "rb") as source:
        streams, data_start = _parse_mcd_header(source, file_size)
        selected = _select_mcd_streams(streams, options)
        blocks: Dict[str, List[Tuple[int, int, int, int]]] = {stream.stream_id: [] for stream in selected}
        position = data_start
        while position + _MCD_CHUNK.size <= file_size:
            source.seek(position)
            tag, size = _MCD_CHUNK.unpack(source.read(_MCD_CHUNK.size))
            # An interrupted recording leaves a partially written last block.
            if size < 0 or position + _MCD_CHUNK.size + size > file_size:
                break
            stream_blocks = blocks.get(tag.decode("ascii", errors="replace"))
            if stream_blocks is not None and size >= _MCD_BLOCK_TIMES.size:
                start_time, end_time = _MCD_BLOCK_TIMES.unpack(source.read(_MCD_BLOCK_TIMES.size))
                data_offset = position + _MCD_CHUNK.size + _MCD_BLOCK_TIMES.size
                stream_blocks.append((data_offset, size - _MCD_BLOCK_TIMES.size, start_time, end_time))
            position += _MCD_CHUNK.size + size

    block_count = min(len(stream_blocks) for stream_blocks in blocks.values())
    if block_count == 0:
        raise ValueError("MCD file contains no analog data blocks")
    offsets = np.empty((block_count, len(selected)), dtype=np.int64)
    samples = np.empty(block_count, dtype=np.int64)
    sweep_sample_counts: List[int] = []
    previous_end: Optional[int] = None
    for block_index in range(block_count):
        block_start: Optional[int] = None
        for stream_index, stream in enumerate(selected):
            data_offset, data_bytes, start_time, end_time = blocks[stream.stream_id][block_index]
            frame_bytes = 2 * len(stream.channel_labels)
            if data_bytes % frame_bytes:
                raise ValueError(f"MCD block size does not match channel count in stream {stream.stream_id}")
            if stream_index == 0:
                block_start, block_end = start_time, end_time
                samples[block_index] = data_bytes // frame_bytes
            elif start_time != block_start or data_bytes // frame_bytes != samples[block_index]:
                raise ValueError("MCD analog streams are not block-aligned")
            offsets[block_index, stream_index] = data_offset
        # Triggered recordings store sweeps as runs of contiguous blocks separated by time gaps.
        if previous_end is None or block_start != previous_end:
            sweep_sample_counts.append(0)
        sweep_sample_counts[-1] += int(samples[block_index])
        previous_end = block_end

    channel_names = [label for stream in selected for label in stream.channel_labels]
    if len(set(channel_names)) != len(channel_names):
        channel_names = [
            f"{label}__{stream.stream_id}" for stream in selected for label in stream.channel_labels
        ]
    zeros = np.concatenate(
        [np.full(len(stream.channel_labels), stream.adc_zero, dtype=np.int64) for stream in selected]
    )
    gains = np.concatenate(
        [np.full(len(stream.channel_labels), stream.gain_volts * 1e6) for stream in selected]
    )
    dtype = np.dtype("<u2")
    digital_min, digital_max = _digital_ranges(dtype, zeros)
    return MCSRecordingInfo(
        path=path,
        source_type="mcs_mcd",
        channel_names=channel_names,
        units=[VoltageUnitEnum.MICROVOLT.value] * len(channel_names),
        gains=gains,
        adc_zero=zeros,
        digital_min=digital_min,
        digital_max=digital_max,
        sample_rate=selected[0].sample_rate,
        sample_count=int(samples.sum()),
        dtype=dtype,
        sweep_sample_counts=tuple(sweep_sample_counts),
        mcd_channel_counts=tuple(len(stream.channel_labels) for stream in selected),
        mcd_block_offsets=offsets,
        mcd_block_samples=samples,
    )


def _parse_mcs(path: Path, options: Dict[str, Any]) -> MCSRecordingInfo:
    suffix = path.suffix.lower()
    if suffix in _MCS_MCD_SUFFIXES:
        return _parse_mcs_mcd(path, options)
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
        self._mcd_file = None
        self._mcd_block_index = 0

    def __iter__(self) -> "MCSDataWriter":
        self._close()
        self._sample_position = 0
        self._mcd_block_index = 0
        if self._info.source_type == "mcs_mcd":
            self._mcd_file = open(self._info.path, "rb")
        elif self._info.source_type == "mcs_raw":
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
        if self._mcd_file is not None:
            values = self._read_mcd_blocks()
            end = self._sample_position + values.shape[1]
        elif self._raw_data is not None:
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

    def _read_mcd_blocks(self) -> np.ndarray:
        offsets = self._info.mcd_block_offsets
        block_samples = self._info.mcd_block_samples
        first_block = self._mcd_block_index
        last_block = first_block + 1
        total = int(block_samples[first_block])
        while last_block < len(block_samples) and total + block_samples[last_block] <= self._chunk_samples:
            total += int(block_samples[last_block])
            last_block += 1

        values = np.empty((self._info.channel_count, total), dtype=self._info.dtype)
        column = 0
        for block_index in range(first_block, last_block):
            samples = int(block_samples[block_index])
            row = 0
            for stream_index, channel_count in enumerate(self._info.mcd_channel_counts):
                self._mcd_file.seek(int(offsets[block_index, stream_index]))
                frames = np.fromfile(self._mcd_file, dtype=self._info.dtype, count=samples * channel_count)
                if frames.size != samples * channel_count:
                    raise ValueError("MCD data block is truncated")
                values[row:row + channel_count, column:column + samples] = frames.reshape(
                    samples, channel_count
                ).T
                row += channel_count
            column += samples
        self._mcd_block_index = last_block
        return values

    def total_chunks(self, header: Header) -> int:
        if self._info.mcd_block_samples is not None:
            chunks = 0
            filled = 0
            for samples in self._info.mcd_block_samples:
                if chunks == 0 or filled + samples > self._chunk_samples:
                    chunks += 1
                    filled = 0
                filled += int(samples)
            return chunks
        return (self._info.sample_count + self._chunk_samples - 1) // self._chunk_samples

    def _close(self) -> None:
        if self._mcd_file is not None:
            self._mcd_file.close()
            self._mcd_file = None
        self._raw_data = None
        self._h5_data = []
        if self._h5_file is not None:
            self._h5_file.close()
            self._h5_file = None

    def __del__(self):
        self._close()


class MCSSourceReader(AbstractSourceReader):
    """Read MC_Rack MCD, MCS RAW, DataManager HDF5, and CMOS-MEA CMCR/CMTR files."""

    def __init__(self, experiment_path: Path):
        super().__init__(experiment_path)
        self._yielded = False
        self._options: Dict[str, Any] = {}

    @classmethod
    def _try_to_open(cls, experiment_path: Path) -> None:
        path = Path(experiment_path)
        supported_suffixes = _MCS_RAW_SUFFIXES | _MCS_H5_SUFFIXES | _MCS_CMOS_SUFFIXES | _MCS_MCD_SUFFIXES
        if not path.is_file() or path.suffix.lower() not in supported_suffixes:
            raise WrongSourceReaderError(cls)
        try:
            if path.suffix.lower() in _MCS_MCD_SUFFIXES:
                # Avoid scanning every data block of multi-gigabyte recordings just to detect the format.
                with open(path, "rb") as source:
                    streams, _ = _parse_mcd_header(source, path.stat().st_size)
                _select_mcd_streams(streams, {})
            else:
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

        points_per_sweep = list(info.sweep_sample_counts) or [info.sample_count]
        created = datetime.fromtimestamp(path.stat().st_mtime)
        header = Header(
            type_before_conversion=info.source_type,
            name_before_conversion=path.name,
            creation_date_before_conversion=str(created.date()),
            creation_time_before_conversion=str(created.time()),
            sample_interval_microseconds=1e6 / info.sample_rate,
            sample_rate=info.sample_rate,
            number_of_channels=info.channel_count,
            number_of_sweeps=len(points_per_sweep),
            number_of_points_per_sweep=points_per_sweep,
            channel_info=channel_info,
        )
        return header, MCSDataWriter(info)

    def set_conversion_options(self, options: Optional[Dict[str, Any]] = None) -> None:
        self._options = dict(options or {})
