# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional, Sequence, Tuple

import numpy as np
from open_ephys.analysis import Session

from ._exceptions import WrongSourceReaderError
from .abstract_source_reader import AbstractSourceReader, AbstractDataWriter
from ephyr.core.header import ChannelInfo, Header

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


def _build_channel_labels(nodes: Sequence[Any], rec_idx: int) -> List[str]:
    labels: List[str] = []
    seen: dict[str, int] = {}
    for node in nodes:
        node_tag = _sanitize_label(os.path.basename(str(node.directory)))
        rec = node.recordings[rec_idx]
        for cont in _continuous_streams(rec):
            m = cont.metadata
            stream_tag = _sanitize_label(str(m.stream_name))
            for ch in m.channel_names:
                base = f"{node_tag}__{stream_tag}__{_sanitize_label(ch)}"
                n = seen.get(base, 0)
                if n:
                    label = f"{base}__{n}"
                else:
                    label = base
                seen[base] = n + 1
                labels.append(label)
    return labels


def _stream_layout(
    nodes: Sequence[Any], rec_idx: int
) -> Tuple[List[Tuple[np.ndarray, int, int]], int, float]:
    """Returns (list of (samples_2d, col_offset, n_ch), n_samples, sample_rate)."""
    layout: List[Tuple[np.ndarray, int, int]] = []
    col = 0
    n_samples: Optional[int] = None
    sample_rate: Optional[float] = None

    for node in nodes:
        rec = node.recordings[rec_idx]
        for cont in _continuous_streams(rec):
            m = cont.metadata
            if sample_rate is None:
                sample_rate = float(m.sample_rate)
            elif abs(float(m.sample_rate) - sample_rate) > 1e-3:
                raise ValueError(
                    "Open Ephys recording has mixed sample rates in continuous streams; "
                    "cannot merge into one Ephyr header."
                )
            samps = cont.samples
            if samps.ndim != 2:
                raise ValueError("Expected continuous samples with shape (n_samples, n_channels)")
            n, c = int(samps.shape[0]), int(samps.shape[1])
            if n_samples is None:
                n_samples = n
            elif n != n_samples:
                raise ValueError(
                    "Open Ephys continuous streams in the same recording have different lengths."
                )
            if c != m.num_channels:
                raise ValueError("Continuous metadata num_channels does not match samples array.")
            layout.append((samps, col, c))
            col += c

    if n_samples is None or sample_rate is None or col == 0:
        raise ValueError("No continuous data in Open Ephys recording.")

    return layout, n_samples, sample_rate


def _channel_phys_meta(nodes: Sequence[Any], rec_idx: int) -> Tuple[
    List[str], List[str], List[str], List[float], List[float], List[int], List[int]
]:
    names: List[str] = []
    probes: List[str] = []
    units: List[str] = []
    analog_min: List[float] = []
    analog_max: List[float] = []
    digital_min: List[int] = []
    digital_max: List[int] = []

    labels = _build_channel_labels(nodes, rec_idx)

    i = 0
    for node in nodes:
        node_tag = os.path.basename(str(node.directory))
        rec = node.recordings[rec_idx]
        for cont in _continuous_streams(rec):
            m = cont.metadata
            probe = f"{m.source_node_name} ({m.stream_name})"
            for bv in m.bit_volts:
                names.append(labels[i])
                probes.append(probe)
                units.append("uV")
                bv_f = float(bv)
                analog_min.append(_DIG_MIN * bv_f)
                analog_max.append(_DIG_MAX * bv_f)
                digital_min.append(_DIG_MIN)
                digital_max.append(_DIG_MAX)
                i += 1
    return names, probes, units, analog_min, analog_max, digital_min, digital_max


class OpenEphysDataWriter(AbstractDataWriter):
    """Yields int16 chunks shaped (n_channels, n_samples_in_chunk) in acquisition order."""

    def __init__(
        self,
        sweep_layouts: List[List[Tuple[np.ndarray, int, int]]],
        total_channels: int,
    ):
        self._sweep_layouts = sweep_layouts
        self._total_channels = total_channels
        self._sweep_idx = 0
        self._sample_pos = 0
        self._layout: List[Tuple[np.ndarray, int, int]] = []
        self._n_samples_in_sweep = 0

    def __iter__(self) -> OpenEphysDataWriter:
        self._sweep_idx = 0
        self._sample_pos = 0
        self._layout = []
        self._n_samples_in_sweep = 0
        return self

    def __next__(self) -> np.ndarray:
        while self._sweep_idx < len(self._sweep_layouts):
            if not self._layout:
                self._layout = self._sweep_layouts[self._sweep_idx]
                if not self._layout:
                    self._sweep_idx += 1
                    continue
                self._n_samples_in_sweep = int(self._layout[0][0].shape[0])
                self._sample_pos = 0

            if self._sample_pos >= self._n_samples_in_sweep:
                self._sweep_idx += 1
                self._layout = []
                continue

            end = min(self._sample_pos + _CHUNK_SAMPLES, self._n_samples_in_sweep)
            width = end - self._sample_pos
            block = np.empty((self._total_channels, width), dtype=np.int16)
            t0, t1 = self._sample_pos, end
            for samps, col_off, n_ch in self._layout:
                values = np.rint(samps[t0:t1, :].T)
                np.clip(values, _DIG_MIN, _DIG_MAX, out=values)
                block[col_off : col_off + n_ch, :] = values.astype(np.int16, copy=False)
            self._sample_pos = end
            return block

        raise StopIteration

    def total_chunks(self, header: Header) -> int:
        total_points = sum(header.number_of_points_per_sweep)
        return max(1, (total_points + _CHUNK_SAMPLES - 1) // _CHUNK_SAMPLES)


class OpenEphysSourceReader(AbstractSourceReader):
    """
    Open Ephys session folders via open-ephys-python-tools (Session / RecordNode / Recording).

    Data formats: https://open-ephys.github.io/gui-docs/User-Manual/Data-formats/index.html
    """

    def __init__(self, experiment_path: Path):
        super().__init__(experiment_path)
        self._yielded = False
        self._session_path = _open_session(experiment_path)[1]

    @classmethod
    def _try_to_open(cls, experiment_path: Path) -> None:
        try:
            session, _ = _open_session(experiment_path)
        except Exception:
            raise WrongSourceReaderError(cls)
        nodes = _session_record_nodes(session)
        if not nodes:
            raise WrongSourceReaderError(cls)
        try:
            n_rec = len(nodes[0].recordings)
            if n_rec == 0:
                raise WrongSourceReaderError(cls)
            for node in nodes:
                if len(node.recordings) != n_rec:
                    raise WrongSourceReaderError(cls)
            for rec_idx in range(n_rec):
                for node in nodes:
                    if not _continuous_streams(node.recordings[rec_idx]):
                        raise WrongSourceReaderError(cls)
        except WrongSourceReaderError:
            raise
        except Exception:
            raise WrongSourceReaderError(cls)

    def __iter__(self) -> OpenEphysSourceReader:
        self._yielded = False
        return self

    def __next__(self) -> Tuple[Header, OpenEphysDataWriter]:
        if self._yielded:
            raise StopIteration
        self._yielded = True

        session = Session(str(self._session_path))
        nodes = _session_record_nodes(session)
        if not nodes:
            raise StopIteration

        n_rec = len(nodes[0].recordings)
        sweep_layouts: List[List[Tuple[np.ndarray, int, int]]] = []
        points_per_sweep: List[int] = []
        sample_rate: Optional[float] = None

        for rec_idx in range(n_rec):
            layout, n_samp, sr = _stream_layout(nodes, rec_idx)
            sweep_layouts.append(layout)
            points_per_sweep.append(n_samp)
            if sample_rate is None:
                sample_rate = sr
            elif abs(sr - sample_rate) > 1e-3:
                raise ValueError("Open Ephys recordings have inconsistent sample rates across files.")

        total_ch = sum(n_ch for _, _, n_ch in sweep_layouts[0])
        for rec_idx in range(1, n_rec):
            ch_here = sum(n_ch for _, _, n_ch in sweep_layouts[rec_idx])
            if ch_here != total_ch:
                raise ValueError(
                    "Open Ephys recordings have different channel counts; cannot build one Ephyr experiment."
                )

        names0, probes0, units0, amin0, amax0, dmin0, dmax0 = _channel_phys_meta(nodes, 0)
        if len(names0) != total_ch:
            raise ValueError("Channel metadata mismatch.")

        for rec_idx in range(1, n_rec):
            names_i, _, _, _, _, _, _ = _channel_phys_meta(nodes, rec_idx)
            if names_i != names0:
                raise ValueError(
                    "Channel layout differs between Open Ephys recordings; expected the same streams and names."
                )

        total_points = sum(points_per_sweep)
        channel_info = ChannelInfo(
            name=names0,
            probe=probes0,
            units=units0,
            analog_min=amin0,
            analog_max=amax0,
            digital_min=dmin0,
            digital_max=dmax0,
            prefiltering=[""] * total_ch,
            number_of_points_per_channel=[total_points] * total_ch,
        )

        date_str = ""
        time_str = ""
        try:
            dt = datetime.strptime(Path(self._session_path).name, "%Y-%m-%d_%H-%M-%S")
            date_str = str(dt.date())
            time_str = str(dt.time())
        except ValueError:
            pass

        header = Header(
            type_before_conversion="openephys",
            name_before_conversion=Path(self._session_path).name,
            creation_date_before_conversion=date_str,
            creation_time_before_conversion=time_str,
            sample_interval_microseconds=1e6 / float(sample_rate),
            sample_rate=float(sample_rate),
            number_of_channels=total_ch,
            number_of_sweeps=n_rec,
            number_of_points_per_sweep=points_per_sweep,
            channel_info=channel_info,
        )

        writer = OpenEphysDataWriter(sweep_layouts, total_ch)
        return header, writer
