from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

from ._exceptions import WrongSourceReaderError
from .abstract_source_reader import AbstractDataWriter, AbstractSourceReader
from ephyr.core.header import ChannelInfo, Header

_CHUNK_SAMPLES = 512
_DIGITAL_MIN = -32768
_DIGITAL_MAX = 32767


@dataclass(frozen=True)
class XdatPaths:
    metadata: Path
    data: Path
    timestamp: Optional[Path]


@dataclass(frozen=True)
class XdatChannel:
    index: int
    name: str
    units: str
    probe: str
    prefiltering: str


@dataclass(frozen=True)
class XdatMetadata:
    paths: XdatPaths
    raw: dict
    sample_rate: float
    n_samples: int
    n_total_channels: int
    channels: List[XdatChannel]
    start_datetime: datetime
    quant_scales: np.ndarray
    analog_abs_max: np.ndarray


def _unit_from_label(label: str) -> str:
    raw = (label or "").strip().lower().replace("_", "-")
    aliases = {
        "micro-volts": "uV",
        "microvolts": "uV",
        "uv": "uV",
        "µv": "uV",
        "μv": "uV",
        "volts": "V",
        "volt": "V",
        "v": "V",
        "binary": "uV",
    }
    return aliases.get(raw, "uV")


def _channel_unit(channel_name: str, metadata: dict) -> str:
    sig_units = metadata.get("sapiens_base", {}).get("sigUnits", {})
    if channel_name.startswith("pri_"):
        return _unit_from_label(sig_units.get("sig_units_pri", "micro-volts"))
    if channel_name.startswith("aux_"):
        return _unit_from_label(sig_units.get("sig_units_aux", "volts"))
    if channel_name.startswith("din_"):
        return _unit_from_label(sig_units.get("sig_units_din", "binary"))
    if channel_name.startswith("dout_"):
        return _unit_from_label(sig_units.get("sig_units_dout", "binary"))
    return "uV"


def _xdat_base_from_path(path: Path) -> Tuple[Path, str]:
    name = path.name
    if name.endswith(".xdat.json"):
        return path.parent, name[: -len(".xdat.json")]
    if path.suffix.lower() != ".xdat":
        raise ValueError("Not an XDAT path")
    stem = path.stem
    for suffix in ("_timestamps", "_timestamp", "_data"):
        if stem.endswith(suffix):
            return path.parent, stem[: -len(suffix)]
    return path.parent, stem


def _resolve_xdat_paths(path: Path) -> XdatPaths:
    folder, base = _xdat_base_from_path(path)
    metadata = folder / f"{base}.xdat.json"

    if path.name.endswith(".xdat.json"):
        data_candidates = [folder / f"{base}_data.xdat", folder / f"{base}.xdat"]
    elif path.stem.endswith(("_timestamp", "_timestamps")):
        data_candidates = [folder / f"{base}_data.xdat", folder / f"{base}.xdat"]
    else:
        data_candidates = [path, folder / f"{base}_data.xdat", folder / f"{base}.xdat"]

    timestamp_candidates = [folder / f"{base}_timestamp.xdat", folder / f"{base}_timestamps.xdat"]
    data = next((candidate for candidate in data_candidates if candidate.exists()), data_candidates[0])
    timestamp = next((candidate for candidate in timestamp_candidates if candidate.exists()), None)
    return XdatPaths(metadata=metadata, data=data, timestamp=timestamp)


def _load_metadata(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _parse_start_datetime(raw: str, fallback: Path) -> datetime:
    if raw:
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            pass
    return datetime.fromtimestamp(fallback.stat().st_mtime)


def _selected_channel_indexes(bio_map: dict, n_total_channels: int) -> List[int]:
    selected = bio_map.get("is_selected")
    if isinstance(selected, list) and len(selected) == n_total_channels:
        indexes = [idx for idx, value in enumerate(selected) if bool(value)]
        if indexes:
            return indexes
    return list(range(n_total_channels))


def _prefiltering(metadata: dict, channel: XdatChannel) -> str:
    filters = metadata.get("sapiens_base", {}).get("sig_proc_spec", {}).get("hardware", [])
    port = channel.probe
    parts: List[str] = []
    for spec in filters:
        if spec.get("port") != port:
            continue
        freq = spec.get("freqSpec")
        if spec.get("type") == "BANDPASS" and isinstance(freq, list) and len(freq) >= 2:
            parts.append(f"BP: {float(freq[0]):.3f}-{float(freq[1]):.3f} Hz")
    notch_filters = metadata.get("sapiens_base", {}).get("sig_proc_spec", {}).get("software_stage_1", [])
    for spec in notch_filters:
        if spec.get("port") != port:
            continue
        freq = spec.get("freqSpec")
        if spec.get("type") == "NOTCH" and isinstance(freq, list) and freq:
            parts.append(f"Notch: {float(freq[0]):.3f} Hz")
    return ", ".join(parts)


def _channels_from_metadata(metadata: dict) -> List[XdatChannel]:
    status = metadata.get("status", {})
    shape = status.get("shape") or []
    if len(shape) != 2:
        raise ValueError("XDAT metadata is missing status.shape")
    n_total_channels = int(shape[1])
    bio_map = metadata.get("sapiens_base", {}).get("biointerface_map", {})
    names = list(bio_map.get("chan_name") or [f"ch_{idx}" for idx in range(n_total_channels)])
    probes = list(bio_map.get("port") or [""] * n_total_channels)
    indexes = _selected_channel_indexes(bio_map, n_total_channels)

    channels: List[XdatChannel] = []
    for idx in indexes:
        name = str(names[idx] if idx < len(names) else f"ch_{idx}")
        probe = str(probes[idx] if idx < len(probes) else "")
        channel = XdatChannel(
            index=idx,
            name=name,
            units=_channel_unit(name, metadata),
            probe=probe,
            prefiltering="",
        )
        channels.append(
            XdatChannel(
                index=channel.index,
                name=channel.name,
                units=channel.units,
                probe=channel.probe,
                prefiltering=_prefiltering(metadata, channel),
            )
        )
    return channels


def _validate_files(paths: XdatPaths, n_samples: int, n_total_channels: int) -> None:
    if not paths.metadata.exists():
        raise ValueError(f"XDAT metadata file not found: {paths.metadata}")
    if not paths.data.exists():
        raise ValueError(f"XDAT data file not found: {paths.data}")
    expected_data_size = n_samples * n_total_channels * np.dtype(np.float32).itemsize
    actual_data_size = paths.data.stat().st_size
    if actual_data_size != expected_data_size:
        raise ValueError(
            f"XDAT data size mismatch: expected {expected_data_size} bytes, got {actual_data_size}"
        )
    if paths.timestamp is not None:
        expected_timestamp_size = n_samples * np.dtype(np.int64).itemsize
        actual_timestamp_size = paths.timestamp.stat().st_size
        if actual_timestamp_size != expected_timestamp_size:
            raise ValueError(
                f"XDAT timestamp size mismatch: expected {expected_timestamp_size} bytes, "
                f"got {actual_timestamp_size}"
            )


def _raw_memmap(metadata: XdatMetadata) -> np.memmap:
    return np.memmap(
        metadata.paths.data,
        dtype=np.float32,
        mode="r",
        shape=(metadata.n_samples, metadata.n_total_channels),
    )


def _scan_quantization(metadata: XdatMetadata) -> Tuple[np.ndarray, np.ndarray]:
    raw = _raw_memmap(metadata)
    indexes = [channel.index for channel in metadata.channels]
    max_abs = np.zeros(len(indexes), dtype=np.float64)
    chunk_size = _CHUNK_SAMPLES * 1024
    for start in range(0, metadata.n_samples, chunk_size):
        end = min(start + chunk_size, metadata.n_samples)
        chunk = np.asarray(raw[start:end, :][:, indexes], dtype=np.float64)
        if chunk.size == 0:
            continue
        chunk_max = np.nanmax(np.abs(chunk), axis=0)
        max_abs = np.maximum(max_abs, chunk_max)
    max_abs[~np.isfinite(max_abs)] = 1.0
    max_abs[max_abs <= 0] = 1.0
    scales = (2.0 * max_abs) / float(_DIGITAL_MAX - _DIGITAL_MIN)
    return scales, max_abs


def _parse_xdat(path: Path, *, scan_quantization: bool) -> XdatMetadata:
    paths = _resolve_xdat_paths(path)
    raw = _load_metadata(paths.metadata)
    status = raw.get("status", {})
    shape = status.get("shape") or []
    if len(shape) != 2:
        raise ValueError("XDAT metadata is missing status.shape")
    n_samples = int(status.get("num_smpl") or shape[0])
    n_total_channels = int(shape[1])
    sample_rate = float(status.get("samp_freq") or 0)
    if n_samples <= 0 or n_total_channels <= 0 or sample_rate <= 0:
        raise ValueError("XDAT metadata has invalid sample count, channel count, or sample rate")
    _validate_files(paths, n_samples, n_total_channels)

    metadata = XdatMetadata(
        paths=paths,
        raw=raw,
        sample_rate=sample_rate,
        n_samples=n_samples,
        n_total_channels=n_total_channels,
        channels=_channels_from_metadata(raw),
        start_datetime=_parse_start_datetime(str(status.get("start_time", "")), paths.metadata),
        quant_scales=np.ones(1, dtype=np.float64),
        analog_abs_max=np.ones(1, dtype=np.float64),
    )
    if not scan_quantization:
        return metadata
    scales, analog_abs_max = _scan_quantization(metadata)
    return XdatMetadata(
        paths=metadata.paths,
        raw=metadata.raw,
        sample_rate=metadata.sample_rate,
        n_samples=metadata.n_samples,
        n_total_channels=metadata.n_total_channels,
        channels=metadata.channels,
        start_datetime=metadata.start_datetime,
        quant_scales=scales,
        analog_abs_max=analog_abs_max,
    )


class XdatDataWriter(AbstractDataWriter):
    def __init__(self, metadata: XdatMetadata):
        self._metadata = metadata
        self._raw = _raw_memmap(metadata)
        self._sample_pos = 0
        self._indexes = [channel.index for channel in metadata.channels]

    def __iter__(self) -> "XdatDataWriter":
        self._sample_pos = 0
        return self

    def __next__(self) -> np.ndarray:
        if self._sample_pos >= self._metadata.n_samples:
            raise StopIteration
        end = min(self._sample_pos + _CHUNK_SAMPLES, self._metadata.n_samples)
        chunk = np.asarray(self._raw[self._sample_pos:end, :][:, self._indexes], dtype=np.float64)
        quantized = np.rint(chunk / self._metadata.quant_scales[np.newaxis, :])
        np.clip(quantized, _DIGITAL_MIN, _DIGITAL_MAX, out=quantized)
        self._sample_pos = end
        return quantized.T.astype(np.int16)

    def total_chunks(self, header: Header) -> int:
        total_points = sum(header.number_of_points_per_sweep)
        return max(1, (total_points + _CHUNK_SAMPLES - 1) // _CHUNK_SAMPLES)


class XdatSourceReader(AbstractSourceReader):
    def __init__(self, experiment_path: Path):
        super().__init__(experiment_path)
        self._yielded = False

    @classmethod
    def _try_to_open(cls, experiment_path: Path) -> None:
        if not (
            experiment_path.is_file()
            and (experiment_path.suffix.lower() == ".xdat" or experiment_path.name.endswith(".xdat.json"))
        ):
            raise WrongSourceReaderError(cls)
        try:
            _parse_xdat(experiment_path, scan_quantization=False)
        except Exception:
            raise WrongSourceReaderError(cls)

    def __iter__(self) -> "XdatSourceReader":
        self._yielded = False
        return self

    def __next__(self) -> Tuple[Header, XdatDataWriter]:
        if self._yielded:
            raise StopIteration
        self._yielded = True

        metadata = _parse_xdat(self._experiment_path, scan_quantization=True)
        total_channels = len(metadata.channels)
        channel_info = ChannelInfo(
            name=[channel.name for channel in metadata.channels],
            probe=[channel.probe for channel in metadata.channels],
            units=[channel.units for channel in metadata.channels],
            analog_min=(-metadata.analog_abs_max).tolist(),
            analog_max=metadata.analog_abs_max.tolist(),
            digital_min=[_DIGITAL_MIN] * total_channels,
            digital_max=[_DIGITAL_MAX] * total_channels,
            prefiltering=[channel.prefiltering for channel in metadata.channels],
            number_of_points_per_channel=[metadata.n_samples] * total_channels,
        )

        header = Header(
            type_before_conversion="xdat",
            name_before_conversion=metadata.paths.data.name,
            creation_date_before_conversion=str(metadata.start_datetime.date()),
            creation_time_before_conversion=str(metadata.start_datetime.time()),
            sample_interval_microseconds=1e6 / metadata.sample_rate,
            sample_rate=metadata.sample_rate,
            number_of_channels=total_channels,
            number_of_sweeps=1,
            number_of_points_per_sweep=[metadata.n_samples],
            channel_info=channel_info,
        )
        return header, XdatDataWriter(metadata)
