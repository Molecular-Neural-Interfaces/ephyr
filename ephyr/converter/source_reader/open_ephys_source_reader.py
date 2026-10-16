# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, List, Optional, Sequence, Tuple

import numpy as np
from open_ephys.analysis import Session

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

_CHUNK_SAMPLES = 512
_DIG_MIN = -32768
_DIG_MAX = 32767


def _candidate_session_paths(path: Path) -> List[Path]:
    if path.is_dir():
        candidates = [path]
        candidates.extend(path.parents)
    else:
        candidates = [path.parent]
        candidates.extend(path.parent.parents)

    result: List[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        result.append(candidate)
        if len(result) >= 8:
            break
    return result


def _open_session(path: Path) -> Tuple[Session, Path]:
    last_error: Optional[Exception] = None
    for candidate in _candidate_session_paths(path):
        try:
            return Session(str(candidate)), candidate
        except Exception as exc:
            last_error = exc
    raise ValueError(f"Failed to open Open Ephys session from {path}: {last_error}")


def _session_record_nodes(session: Session) -> List[Any]:
    """Session exposes either recordnodes (multi Record Node dirs) or flat recordings."""
    rns = getattr(session, "recordnodes", None)
    if rns:
        return list(rns)

    recs = getattr(session, "recordings", None)
    if not recs:
        return []

    class _SingleRecordNode:
        def __init__(self, directory: str, recordings: list):
            self.directory = directory
            self.recordings = recordings

    return [_SingleRecordNode(session.directory, recs)]


def _continuous_streams(recording) -> list:
    cdict = recording.continuous
    if cdict is None or len(cdict) == 0:
        return []
    return list(cdict)


def _sanitize_label(part: str) -> str:
    return re.sub(r"\s+", "_", part.strip())


_StreamLayout = List[Tuple[np.ndarray, int, int]]


class _StreamGroup:
    """Continuous streams of one sample rate across Record Nodes; one Ephyr source."""

    def __init__(self, sample_rate: float):
        self.sample_rate = sample_rate
        self.stream_keys: List[str] = []
        self.channel_plans: List[ChannelPlan] = []
        # One layout per recording: (samples (n, c), first channel row, channel count).
        self.layouts: List[_StreamLayout] = []
        self.points: List[int] = []
        self.t_starts_s: List[Optional[float]] = []


def _first_time_s(cont, sample_rate: float) -> Optional[float]:
    for attr in ("timestamps", "sample_numbers"):
        values = getattr(cont, attr, None)
        if values is None or len(values) == 0:
            continue
        first = float(values[0])
        if attr == "timestamps" and first >= 0:
            return first
        if attr == "sample_numbers":
            return first / sample_rate
    return None


def _stream_key(node, cont) -> str:
    return f"{_sanitize_label(os.path.basename(str(node.directory)))}__{_sanitize_label(str(cont.metadata.stream_name))}"


def _build_groups(nodes: Sequence[Any]) -> List[_StreamGroup]:
    n_rec = len(nodes[0].recordings)
    groups: List[_StreamGroup] = []

    def group_for(rate: float) -> _StreamGroup:
        for group in groups:
            if abs(group.sample_rate - rate) <= 1e-3:
                return group
        group = _StreamGroup(rate)
        groups.append(group)
        return group

    seen_labels: dict[str, int] = {}
    for rec_idx in range(n_rec):
        per_group: dict[int, _StreamLayout] = {}
        per_group_keys: dict[int, List[str]] = {}
        per_group_time: dict[int, Optional[float]] = {}
        for node in nodes:
            for cont in _continuous_streams(node.recordings[rec_idx]):
                metadata = cont.metadata
                rate = float(metadata.sample_rate)
                group = group_for(rate)
                gid = groups.index(group)
                samples = cont.samples
                if samples.ndim != 2 or int(samples.shape[1]) != int(metadata.num_channels):
                    raise ValueError("Open Ephys continuous samples do not match their metadata")
                layout = per_group.setdefault(gid, [])
                row = sum(n_ch for _, _, n_ch in layout)
                layout.append((samples, row, int(samples.shape[1])))
                key = _stream_key(node, cont)
                per_group_keys.setdefault(gid, []).append(key)
                if per_group_time.get(gid) is None:
                    per_group_time[gid] = _first_time_s(cont, rate)
                if rec_idx == 0:
                    group.stream_keys.append(key)
                    probe = f"{metadata.source_node_name} ({metadata.stream_name})"
                    for name, bit_volts in zip(metadata.channel_names, metadata.bit_volts):
                        base = f"{key}__{_sanitize_label(name)}"
                        count = seen_labels.get(base, 0)
                        seen_labels[base] = count + 1
                        bv = float(bit_volts)
                        group.channel_plans.append(
                            ChannelPlan(
                                name=f"{base}__{count}" if count else base,
                                units="uV",
                                analog_min=_DIG_MIN * bv,
                                analog_max=_DIG_MAX * bv,
                                digital_min=_DIG_MIN,
                                digital_max=_DIG_MAX,
                                probe=probe,
                            )
                        )
        for gid, group in enumerate(groups):
            if per_group_keys.get(gid, []) != group.stream_keys:
                raise ValueError("Open Ephys recordings of one session have different continuous streams")
            layout = per_group[gid]
            group.layouts.append(layout)
            group.points.append(min(int(samples.shape[0]) for samples, _, _ in layout))
            group.t_starts_s.append(per_group_time.get(gid))
    if not groups:
        raise ValueError("No continuous data in Open Ephys recording.")
    return groups


def _ttl_annotations(nodes: Sequence[Any], t0_s: float, sample_rate: float) -> Tuple[List[EventPlan], List[PeriodPlan]]:
    events: List[EventPlan] = []
    periods: List[PeriodPlan] = []
    for node in nodes:
        for recording in node.recordings:
            try:
                frame = recording.events
            except Exception:
                frame = None
            if frame is None or len(frame) == 0:
                continue
            opened: dict[Tuple[str, int], float] = {}
            for row in frame.itertuples(index=False):
                timestamp = float(getattr(row, "timestamp", -1))
                time_s = timestamp if timestamp >= 0 else float(row.sample_number) / sample_rate
                t_ms = (time_s - t0_s) * 1000.0
                line = int(row.line)
                stream = str(getattr(row, "stream_name", ""))
                label = f"TTL {line}"
                if int(row.state) == 1:
                    events.append(EventPlan(t_ms=t_ms, label=label, value="1", extra={"stream": stream}))
                    opened[(stream, line)] = t_ms
                else:
                    start = opened.pop((stream, line), None)
                    if start is not None and t_ms > start:
                        periods.append(PeriodPlan(start_t_ms=start, end_t_ms=t_ms, label=label,
                                                  extra={"stream": stream}))
    return events, periods


class OpenEphysDataWriter(AbstractDataWriter):
    """Yields int16 chunks shaped (n_channels, n_samples_in_chunk), recording after recording."""

    def __init__(self, layouts: List[_StreamLayout], points: List[int], total_channels: int):
        self._layouts = layouts
        self._points = points
        self._total_channels = total_channels

    def __iter__(self) -> Iterator[np.ndarray]:
        for layout, n_samples in zip(self._layouts, self._points):
            for start in range(0, n_samples, _CHUNK_SAMPLES):
                end = min(start + _CHUNK_SAMPLES, n_samples)
                block = np.empty((self._total_channels, end - start), dtype=np.int16)
                for samples, row, n_ch in layout:
                    values = np.rint(samples[start:end, :].T)
                    np.clip(values, _DIG_MIN, _DIG_MAX, out=values)
                    block[row:row + n_ch, :] = values.astype(np.int16, copy=False)
                yield block

    def total_chunks(self) -> int:
        return max(1, sum((points + _CHUNK_SAMPLES - 1) // _CHUNK_SAMPLES for points in self._points))


def _session_files(root: Path) -> List[Path]:
    return sorted(item for item in root.rglob("*") if item.is_file() and not item.name.startswith("."))


class OpenEphysSourceReader(AbstractSourceReader):
    """
    Open Ephys session folders via open-ephys-python-tools (Session / RecordNode / Recording).

    Recordings become segments; continuous streams with different sample rates become separate sources.
    Data formats: https://open-ephys.github.io/gui-docs/User-Manual/Data-formats/index.html
    """

    format_name = "openephys"

    @classmethod
    def resolve(cls, path: Path) -> SourceRef:
        session, root = _open_session(path)
        nodes = _session_record_nodes(session)
        if not nodes or not nodes[0].recordings:
            raise WrongSourceReaderError(cls)
        n_rec = len(nodes[0].recordings)
        for node in nodes:
            if len(node.recordings) != n_rec:
                raise WrongSourceReaderError(cls)
            for recording in node.recordings:
                if not _continuous_streams(recording):
                    raise WrongSourceReaderError(cls)
        return SourceRef(format=cls.format_name, kind="folder", root=root, name=root.name,
                         files=_session_files(root))

    def probe(self, scan: bool = False) -> ConversionPlan:
        root = self.ref.root
        session = Session(str(root))
        nodes = _session_record_nodes(session)
        groups = _build_groups(nodes)
        groups.sort(key=lambda group: (-len(group.channel_plans), -group.sample_rate))
        main = groups[0]
        t0_s = next((value for value in main.t_starts_s if value is not None), 0.0)

        sources: List[SourcePlan] = []
        for idx, group in enumerate(groups):
            t_starts = None
            if all(value is not None for value in group.t_starts_s):
                t_starts = [(value - t0_s) * 1000.0 for value in group.t_starts_s]
            segments = contiguous_segments(group.points, group.sample_rate, t_starts)
            sources.append(
                SourcePlan(
                    source_id="main" if idx == 0 else f"rate_{group.sample_rate:g}hz".replace(".", "_"),
                    name=", ".join(group.stream_keys) or f"{group.sample_rate:g} Hz",
                    sample_rate=group.sample_rate,
                    channels=group.channel_plans,
                    segments=segments,
                    segment_kind=SegmentKindEnum.RECORDING if len(segments) > 1 else SegmentKindEnum.CONTINUOUS,
                    source_format=self.format_name,
                    writer_factory=lambda group=group: OpenEphysDataWriter(
                        group.layouts, group.points, len(group.channel_plans)
                    ),
                )
            )

        events, periods = _ttl_annotations(nodes, t0_s, main.sample_rate)
        start_datetime = ""
        try:
            start_datetime = datetime.strptime(root.name, "%Y-%m-%d_%H-%M-%S").isoformat()
        except ValueError:
            pass
        return ConversionPlan(
            ref=self.ref,
            sources=sources,
            events=events,
            periods=periods,
            start_datetime=start_datetime,
            recording_name=root.name,
            reader_options=dict(self._options),
        )
