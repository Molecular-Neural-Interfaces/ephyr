# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict, Iterator, List, Tuple

import numpy as np
import pyedflib

from ._exceptions import WrongSourceReaderError
from .abstract_source_reader import (
    AbstractDataWriter,
    AbstractSourceReader,
    ChannelPlan,
    ConversionPlan,
    EventPlan,
    PeriodPlan,
    SourcePlan,
    SourceRef,
    contiguous_segments,
)
from ephyr.core.manifests import SegmentKindEnum
from ephyr.core.units import canonical_unit_label

_CHUNK_SAMPLES = 512


def _as_int(value, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _as_float(value, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


class EdfDataWriter(AbstractDataWriter):
    def __init__(self, experiment_path: Path, channel_indexes: List[int], n_samples: int):
        self._experiment_path = experiment_path
        self._channel_indexes = list(channel_indexes)
        self._n_samples = n_samples

    def __iter__(self) -> Iterator[np.ndarray]:
        reader = pyedflib.EdfReader(str(self._experiment_path))
        try:
            for start in range(0, self._n_samples, _CHUNK_SAMPLES):
                width = min(_CHUNK_SAMPLES, self._n_samples - start)
                chunk = np.empty((len(self._channel_indexes), width), dtype=np.int16)
                for row, ch_idx in enumerate(self._channel_indexes):
                    data = reader.readSignal(ch_idx, start, width, digital=True)
                    chunk[row, :] = np.asarray(data, dtype=np.int16)
                yield chunk
        finally:
            reader.close()

    def total_chunks(self) -> int:
        return max(1, (self._n_samples + _CHUNK_SAMPLES - 1) // _CHUNK_SAMPLES)


def _rate_groups(reader: pyedflib.EdfReader) -> List[Tuple[float, List[int]]]:
    """Channels grouped by sample rate, in order of first appearance."""
    groups: Dict[float, List[int]] = {}
    for ch_idx, rate in enumerate(reader.getSampleFrequencies()):
        rate = float(rate)
        if rate <= 0:
            raise ValueError("EDF file has an invalid sample rate")
        groups.setdefault(rate, []).append(ch_idx)
    return list(groups.items())


def _annotations(reader: pyedflib.EdfReader) -> Tuple[List[EventPlan], List[PeriodPlan]]:
    events: List[EventPlan] = []
    periods: List[PeriodPlan] = []
    try:
        onsets, durations, texts = reader.readAnnotations()
    except Exception:
        return events, periods
    for onset, duration, text in zip(onsets, durations, texts):
        label = str(text).strip() or "annotation"
        start_ms = float(onset) * 1000.0
        duration_ms = float(duration) * 1000.0 if duration is not None else 0.0
        if duration_ms > 0:
            periods.append(PeriodPlan(start_t_ms=start_ms, end_t_ms=start_ms + duration_ms, label=label))
        else:
            events.append(EventPlan(t_ms=start_ms, label=label))
    return events, periods


class EdfSourceReader(AbstractSourceReader):
    format_name = "edf"

    @classmethod
    def resolve(cls, path: Path) -> SourceRef:
        if not path.is_file() or path.suffix.lower() != ".edf":
            raise WrongSourceReaderError(cls)
        pyedflib.EdfReader(str(path)).close()
        return SourceRef(format=cls.format_name, kind="file", root=path, name=path.name, files=[path])

    def probe(self, scan: bool = False) -> ConversionPlan:
        path = self.ref.root
        reader = pyedflib.EdfReader(str(path))
        try:
            n_channels = int(reader.signals_in_file)
            if n_channels <= 0:
                raise ValueError(f"EDF file contains no signals: {path}")
            signal_headers = reader.getSignalHeaders()
            labels = reader.getSignalLabels()
            n_samples = [int(n) for n in reader.getNSamples()]
            start_dt = reader.getStartdatetime()
            if not isinstance(start_dt, datetime):
                start_dt = datetime.fromtimestamp(path.stat().st_mtime)

            def channel_plan(ch_idx: int) -> ChannelPlan:
                signal_header = signal_headers[ch_idx]
                return ChannelPlan(
                    name=str(labels[ch_idx] or f"EDF {ch_idx}"),
                    units=canonical_unit_label(str(signal_header.get("dimension", ""))),
                    analog_min=_as_float(signal_header.get("physical_min"), reader.getPhysicalMinimum(ch_idx)),
                    analog_max=_as_float(signal_header.get("physical_max"), reader.getPhysicalMaximum(ch_idx)),
                    digital_min=_as_int(signal_header.get("digital_min"), reader.getDigitalMinimum(ch_idx)),
                    digital_max=_as_int(signal_header.get("digital_max"), reader.getDigitalMaximum(ch_idx)),
                    probe=str(signal_header.get("transducer", "")),
                    prefiltering=str(signal_header.get("prefilter", "") or reader.getPrefilter(ch_idx) or ""),
                )

            groups = _rate_groups(reader)
            main_rate = max(groups, key=lambda group: len(group[1]))[0]
            sources: List[SourcePlan] = []
            for rate, indexes in groups:
                group_samples = min(n_samples[idx] for idx in indexes)
                is_main = rate == main_rate
                sources.append(
                    SourcePlan(
                        source_id="main" if is_main else f"rate_{rate:g}hz".replace(".", "_"),
                        name="Signals" if is_main else f"Signals {rate:g} Hz",
                        sample_rate=rate,
                        channels=[channel_plan(idx) for idx in indexes],
                        segments=contiguous_segments([group_samples], rate),
                        segment_kind=SegmentKindEnum.CONTINUOUS,
                        source_format=self.format_name,
                        writer_factory=lambda indexes=indexes, count=group_samples: EdfDataWriter(path, indexes,
                                                                                                    count),
                    )
                )
            events, periods = _annotations(reader)
        finally:
            reader.close()
        sources.sort(key=lambda plan: plan.source_id != "main")
        return ConversionPlan(
            ref=self.ref,
            sources=sources,
            events=events,
            periods=periods,
            start_datetime=start_dt.isoformat(),
            recording_name=path.stem,
            reader_options=dict(self._options),
        )
