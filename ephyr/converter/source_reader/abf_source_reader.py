# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

import numpy as np
import pyabf

from ._exceptions import WrongSourceReaderError
from .abstract_source_reader import (
    AbstractDataWriter,
    AbstractSourceReader,
    ChannelPlan,
    ConversionPlan,
    SourcePlan,
    SourceRef,
    contiguous_segments,
)
from ephyr.core.manifests import SegmentKindEnum
from ephyr.core.units import canonical_unit_label

_CHUNK_SAMPLES = 512
_DIGITAL_MIN = -32768
_DIGITAL_MAX = 32767


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

    def total_chunks(self) -> int:
        total_points = sum(end - start for start, end in self._sweep_bounds)
        return max(1, (total_points + _CHUNK_SAMPLES - 1) // _CHUNK_SAMPLES)


class AbfSourceReader(AbstractSourceReader):
    """
    Axon Binary File reader backed by pyABF.

    ABF stores ADC values with per-channel scale/offset. Ephyr stores int16 data
    and a zero-centered per-channel scale, so this reader converts physical ABF
    values into int16 while preserving the original channel units.
    """

    format_name = "abf"

    @classmethod
    def resolve(cls, path: Path) -> SourceRef:
        if not path.is_file() or path.suffix.lower() != ".abf":
            raise WrongSourceReaderError(cls)
        pyabf.ABF(path, loadData=False)
        return SourceRef(format=cls.format_name, kind="file", root=path, name=path.name, files=[path])

    def probe(self, scan: bool = False) -> ConversionPlan:
        path = self.ref.root
        abf = pyabf.ABF(path, loadData=False)
        sweep_bounds = _sweep_bounds(abf)
        if not sweep_bounds:
            raise ValueError(f"ABF file contains no sweeps: {path}")

        n_channels = int(abf.channelCount)
        if scan:
            quant_scales, analog_abs_max = self._channel_quantization(abf)
        else:
            analog_abs_max = np.ones(n_channels, dtype=np.float64)
            quant_scales = (2.0 * analog_abs_max) / float(_DIGITAL_MAX - _DIGITAL_MIN)
        points_per_sweep = [end - start for start, end in sweep_bounds]
        sample_rate = float(abf.dataRate)
        sweep_interval_ms = float(getattr(abf, "sweepIntervalSec", 0.0) or 0.0) * 1000.0
        t_starts = [idx * sweep_interval_ms for idx in range(len(points_per_sweep))] if sweep_interval_ms > 0 else None
        protocol = str(getattr(abf, "protocol", "") or "")

        channels = [
            ChannelPlan(
                name=str(name or f"ADC {idx}"),
                units=canonical_unit_label(abf.adcUnits[idx]),
                analog_min=-float(analog_abs_max[idx]),
                analog_max=float(analog_abs_max[idx]),
                digital_min=_DIGITAL_MIN,
                digital_max=_DIGITAL_MAX,
                probe=protocol,
                prefiltering=_prefiltering(abf, idx),
            )
            for idx, name in enumerate(abf.adcNames)
        ]
        segment_kind = SegmentKindEnum.SWEEP if len(points_per_sweep) > 1 else SegmentKindEnum.CONTINUOUS
        source = SourcePlan(
            source_id="main",
            name="ADC",
            sample_rate=sample_rate,
            channels=channels,
            segments=contiguous_segments(points_per_sweep, sample_rate, t_starts),
            segment_kind=segment_kind,
            source_format=self.format_name,
            writer_factory=lambda: AbfDataWriter(abf, sweep_bounds, quant_scales),
        )
        return ConversionPlan(
            ref=self.ref,
            sources=[source],
            start_datetime=_abf_datetime(abf, path).isoformat(),
            recording_name=path.stem,
            reader_options=dict(self._options),
        )

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
