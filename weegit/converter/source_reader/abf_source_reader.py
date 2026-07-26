from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

import numpy as np
import pyabf

from ._exceptions import WrongSourceReaderError
from .abstract_source_reader import AbstractDataWriter, AbstractSourceReader
from weegit.core.header import ChannelInfo, Header

_CHUNK_SAMPLES = 512
_DIGITAL_MIN = -32768
_DIGITAL_MAX = 32767


def _unit_ascii(unit: str) -> str:
    return (unit or "").strip().replace("µ", "u").replace("μ", "u")


def _sweep_bounds(abf: pyabf.ABF) -> List[Tuple[int, int]]:
    has_multiple_sweeps = abf.sweepCount > 1
    synch = getattr(abf, "_synchArraySection", None)
    if has_multiple_sweeps and synch is not None and len(set(synch.lLength)) > 1:
        starts: List[int] = []
        point_start = 0
        for length in synch.lLength[: abf.sweepCount]:
            starts.append(point_start)
            point_start += int(length) // int(abf.channelCount)
        return [
            (start, start + int(synch.lLength[idx]) // int(abf.channelCount))
            for idx, start in enumerate(starts)
        ]

    return [
        (int(abf.sweepPointCount) * sweep_idx, int(abf.sweepPointCount) * (sweep_idx + 1))
        for sweep_idx in range(int(abf.sweepCount))
    ]


def _abf_datetime(abf: pyabf.ABF, filepath: Path) -> datetime:
    value = getattr(abf, "abfDateTime", None)
    if isinstance(value, datetime):
        return value
    return datetime.fromtimestamp(os.path.getmtime(filepath))


def _data_dtype(abf: pyabf.ABF) -> np.dtype:
    if int(abf.dataPointByteSize) == 2:
        return np.dtype(np.int16)
    if int(abf.dataPointByteSize) == 4:
        return np.dtype(np.float32)
    raise ValueError(f"Unsupported ABF data point size: {abf.dataPointByteSize}")


def _raw_memmap(abf: pyabf.ABF) -> np.memmap:
    dtype = _data_dtype(abf)
    rows = int(abf.dataPointCount) // int(abf.channelCount)
    return np.memmap(
        abf.abfFilePath,
        dtype=dtype,
        mode="r",
        offset=int(abf.dataByteStart),
        shape=(rows, int(abf.channelCount)),
    )


def _physical_chunk(abf: pyabf.ABF, raw_chunk: np.ndarray) -> np.ndarray:
    data = raw_chunk.T.astype(np.float64, copy=False)
    if _data_dtype(abf) == np.dtype(np.int16):
        gains = np.asarray(abf._dataGain, dtype=np.float64)[:, np.newaxis]
        offsets = np.asarray(abf._dataOffset, dtype=np.float64)[:, np.newaxis]
        data = data * gains + offsets
    return data


def _prefiltering(abf: pyabf.ABF, channel_idx: int) -> str:
    parts: List[str] = []
    adc = getattr(abf, "_adcSection", None)
    if adc is not None:
        hp = float(adc.fSignalHighpassFilter[channel_idx] or 0)
        lp = float(adc.fSignalLowpassFilter[channel_idx] or 0)
        telegraph = float(adc.fTelegraphFilter[channel_idx] or 0)
        if hp > 0:
            parts.append(f"HP: {hp:.3f} Hz")
        if lp > 0:
            parts.append(f"LP: {lp:.3f} Hz")
        if telegraph > 0:
            parts.append(f"Telegraph: {telegraph:.3f} Hz")
    else:
        header = getattr(abf, "_headerV1", None)
        if header is not None and getattr(header, "nTelegraphEnable", [0] * abf.channelCount)[channel_idx]:
            telegraph = float(header.fTelegraphFilter[channel_idx] or 0)
            if telegraph > 0:
                parts.append(f"Telegraph: {telegraph:.3f} Hz")
    return ", ".join(parts)


class AbfDataWriter(AbstractDataWriter):
    def __init__(self, abf: pyabf.ABF, sweep_bounds: List[Tuple[int, int]], quant_scales: np.ndarray):
        self._abf = abf
        self._sweep_bounds = sweep_bounds
        self._quant_scales = quant_scales.astype(np.float64)
        self._raw = _raw_memmap(abf)
        self._sweep_idx = 0
        self._sample_pos = 0

    def __iter__(self) -> "AbfDataWriter":
        self._sweep_idx = 0
        self._sample_pos = self._sweep_bounds[0][0] if self._sweep_bounds else 0
        return self

    def __next__(self) -> np.ndarray:
        while self._sweep_idx < len(self._sweep_bounds):
            sweep_start, sweep_end = self._sweep_bounds[self._sweep_idx]
            if self._sample_pos < sweep_start:
                self._sample_pos = sweep_start
            if self._sample_pos >= sweep_end:
                self._sweep_idx += 1
                if self._sweep_idx < len(self._sweep_bounds):
                    self._sample_pos = self._sweep_bounds[self._sweep_idx][0]
                continue

            end = min(self._sample_pos + _CHUNK_SAMPLES, sweep_end)
            physical = _physical_chunk(self._abf, self._raw[self._sample_pos:end, :])
            quantized = np.rint(physical / self._quant_scales[:, np.newaxis])
            np.clip(quantized, _DIGITAL_MIN, _DIGITAL_MAX, out=quantized)
            self._sample_pos = end
            return quantized.astype(np.int16)

        raise StopIteration

    def total_chunks(self, header: Header) -> int:
        total_points = sum(header.number_of_points_per_sweep)
        return max(1, (total_points + _CHUNK_SAMPLES - 1) // _CHUNK_SAMPLES)


class AbfSourceReader(AbstractSourceReader):
    """
    Axon Binary File reader backed by pyABF.

    ABF stores ADC values with per-channel scale/offset. Weegit stores int16 data
    and a zero-centered per-channel scale, so this reader converts physical ABF
    values into int16 while preserving the original channel units in the header.
    """

    def __init__(self, experiment_path: Path):
        super().__init__(experiment_path)
        self._yielded = False

    @classmethod
    def _try_to_open(cls, experiment_path: Path) -> None:
        if not experiment_path.is_file() or experiment_path.suffix.lower() != ".abf":
            raise WrongSourceReaderError(cls)
        try:
            pyabf.ABF(experiment_path, loadData=False)
        except Exception:
            raise WrongSourceReaderError(cls)

    def __iter__(self) -> "AbfSourceReader":
        self._yielded = False
        return self

    def __next__(self) -> Tuple[Header, AbfDataWriter]:
        if self._yielded:
            raise StopIteration
        self._yielded = True

        abf = pyabf.ABF(self._experiment_path, loadData=False)
        sweep_bounds = _sweep_bounds(abf)
        if not sweep_bounds:
            raise ValueError(f"ABF file contains no sweeps: {self._experiment_path}")

        quant_scales, analog_abs_max = self._channel_quantization(abf)
        points_per_sweep = [end - start for start, end in sweep_bounds]
        total_points = sum(points_per_sweep)
        dt = _abf_datetime(abf, self._experiment_path)

        channel_info = ChannelInfo(
            name=[str(name or f"ADC {idx}") for idx, name in enumerate(abf.adcNames)],
            probe=[str(getattr(abf, "protocol", "") or "")] * int(abf.channelCount),
            units=[_unit_ascii(unit) for unit in abf.adcUnits],
            analog_min=(-analog_abs_max).tolist(),
            analog_max=analog_abs_max.tolist(),
            digital_min=[_DIGITAL_MIN] * int(abf.channelCount),
            digital_max=[_DIGITAL_MAX] * int(abf.channelCount),
            prefiltering=[_prefiltering(abf, idx) for idx in range(int(abf.channelCount))],
            number_of_points_per_channel=[total_points] * int(abf.channelCount),
        )

        header = Header(
            type_before_conversion="abf",
            name_before_conversion=self._experiment_path.name,
            creation_date_before_conversion=str(dt.date()),
            creation_time_before_conversion=str(dt.time()),
            sample_interval_microseconds=1e6 / float(abf.dataRate),
            sample_rate=float(abf.dataRate),
            number_of_channels=int(abf.channelCount),
            number_of_sweeps=len(points_per_sweep),
            number_of_points_per_sweep=points_per_sweep,
            channel_info=channel_info,
        )
        return header, AbfDataWriter(abf, sweep_bounds, quant_scales)

    @staticmethod
    def _channel_quantization(abf: pyabf.ABF) -> Tuple[np.ndarray, np.ndarray]:
        raw = _raw_memmap(abf)
        max_abs = np.zeros(int(abf.channelCount), dtype=np.float64)
        for start in range(0, raw.shape[0], _CHUNK_SAMPLES * 1024):
            end = min(start + _CHUNK_SAMPLES * 1024, raw.shape[0])
            physical = _physical_chunk(abf, raw[start:end, :])
            chunk_max = np.nanmax(np.abs(physical), axis=1)
            max_abs = np.maximum(max_abs, chunk_max)

        max_abs[~np.isfinite(max_abs)] = 1.0
        max_abs[max_abs <= 0] = 1.0
        quant_scales = (2.0 * max_abs) / float(_DIGITAL_MAX - _DIGITAL_MIN)
        return quant_scales, max_abs
