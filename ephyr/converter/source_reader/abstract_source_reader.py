# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Literal, Optional

import numpy as np

from ephyr.core.manifests import DerivedFrom, SegmentInfo, SegmentKindEnum
from ._exceptions import WrongSourceReaderError

SourceKind = Literal["file", "folder"]


@dataclass(frozen=True)
class SourceRef:
    """Canonical root of a recording on disk.

    `root` is the folder for multi-file formats (NCS, Intan, Open Ephys) or the main file otherwise.
    `files` are every file the conversion reads; they define the content fingerprint.
    """
    format: str
    kind: SourceKind
    root: Path
    name: str
    files: List[Path]

    def relpath(self, path: Path) -> str:
        """Location of a source file that does not depend on where the recording lies or how its root is named."""
        if self.kind == "folder":
            return Path(path).relative_to(self.root).as_posix()
        stem = self.root.name
        for suffix in reversed(self.root.suffixes):
            stem = stem[: -len(suffix)] if stem.endswith(suffix) else stem
        name = Path(path).name
        return name[len(stem):] if stem and name.startswith(stem) else name


@dataclass
class ChannelPlan:
    name: str
    units: str
    analog_min: float
    analog_max: float
    digital_min: int = -32768
    digital_max: int = 32767
    probe: str = ""
    prefiltering: str = ""
    impedance_ohm: Optional[float] = None


@dataclass
class EventPlan:
    t_ms: float
    label: str
    source_id: Optional[str] = None
    channel: Optional[int] = None
    value: Optional[str] = None
    extra: Dict[str, str] = field(default_factory=dict)


@dataclass
class PeriodPlan:
    start_t_ms: float
    end_t_ms: float
    label: str
    source_id: Optional[str] = None
    channel: Optional[int] = None
    value: Optional[str] = None
    extra: Dict[str, str] = field(default_factory=dict)


class AbstractDataWriter(ABC):
    """Yields int16 chunks of shape (n_channels, n) that run over all segments of one source back to back."""

    @abstractmethod
    def __iter__(self) -> Iterator[np.ndarray]:
        raise NotImplementedError

    @abstractmethod
    def total_chunks(self) -> int:
        raise NotImplementedError

    def to_dest_folder(self, dest_folder: Path, channel_paths: List[Path], total_samples: int) -> Iterator[float]:
        """Write one file per channel; yields the fraction of chunks done."""
        dest_folder.mkdir(parents=True, exist_ok=True)
        n_channels = len(channel_paths)
        total_chunks = max(1, int(self.total_chunks()))
        files = [open(path, "wb") for path in channel_paths]
        written = 0
        try:
            for processed, chunk in enumerate(self, start=1):
                if chunk.ndim != 2 or chunk.shape[0] != n_channels:
                    raise ValueError(
                        f"Reader produced a chunk of shape {chunk.shape}, expected ({n_channels}, n)"
                    )
                take = min(int(chunk.shape[1]), total_samples - written)
                if take < chunk.shape[1]:
                    raise ValueError("Reader produced more samples than its segments describe")
                block = np.ascontiguousarray(chunk, dtype="<i2")
                for ch_idx, file in enumerate(files):
                    file.write(block[ch_idx].tobytes())
                written += take
                yield min(processed / total_chunks, 1.0)
        finally:
            for file in files:
                file.close()
        if written != total_samples:
            raise ValueError(f"Reader produced {written} samples, its segments describe {total_samples}")


@dataclass
class SourcePlan:
    source_id: str
    name: str
    sample_rate: float
    channels: List[ChannelPlan]
    segments: List[SegmentInfo]
    segment_kind: SegmentKindEnum
    source_format: str
    writer_factory: Callable[[], AbstractDataWriter]
    derived_from: Optional[DerivedFrom] = None
    t_start_ms: float = 0.0

    @property
    def total_samples(self) -> int:
        return sum(int(segment.number_of_samples) for segment in self.segments)

    @property
    def number_of_channels(self) -> int:
        return len(self.channels)


@dataclass
class ConversionPlan:
    ref: SourceRef
    sources: List[SourcePlan]
    events: List[EventPlan] = field(default_factory=list)
    periods: List[PeriodPlan] = field(default_factory=list)
    start_datetime: str = ""
    recording_name: str = ""
    reader_options: Dict[str, Any] = field(default_factory=dict)

    def source(self, source_id: str) -> Optional[SourcePlan]:
        return next((plan for plan in self.sources if plan.source_id == source_id), None)


@dataclass(frozen=True)
class ReaderOption:
    """Boolean conversion option shown in the add dialogs."""
    key: str
    label: str
    default: bool = False


def contiguous_segments(points: List[int], sample_rate: float, t_starts_ms: Optional[List[float]] = None,
                        labels: Optional[List[Optional[str]]] = None) -> List[SegmentInfo]:
    """Segments stored back to back; without explicit starts they follow each other without gaps.

    A start that falls inside the previous segment is moved to its end: Record time must not overlap.
    """
    segments: List[SegmentInfo] = []
    start_sample = 0
    t_cursor = float(t_starts_ms[0]) if t_starts_ms else 0.0
    for idx, n_samples in enumerate(points):
        t_start = max(float(t_starts_ms[idx]), t_cursor) if t_starts_ms is not None else t_cursor
        segments.append(
            SegmentInfo(
                start_sample_idx=start_sample,
                number_of_samples=int(n_samples),
                t_start_ms=t_start,
                label=labels[idx] if labels is not None else None,
            )
        )
        start_sample += int(n_samples)
        t_cursor = t_start + int(n_samples) * 1000.0 / sample_rate
    return segments


class AbstractSourceReader(ABC):
    format_name: str = ""

    def __init__(self, ref: SourceRef):
        self._ref = ref
        self._options: Dict[str, Any] = {}

    @property
    def ref(self) -> SourceRef:
        return self._ref

    @classmethod
    def try_resolve(cls, path: Path) -> SourceRef:
        try:
            return cls.resolve(Path(path))
        except WrongSourceReaderError:
            raise
        except Exception:
            raise WrongSourceReaderError(cls)

    @classmethod
    @abstractmethod
    def resolve(cls, path: Path) -> SourceRef:
        """Canonical root for any path inside a recording; raises WrongSourceReaderError for other formats."""
        raise NotImplementedError

    @abstractmethod
    def probe(self, scan: bool = False) -> ConversionPlan:
        """Sources, segments and annotations from metadata.

        Without `scan` readers whose calibration depends on the signal peak may report a provisional
        range; signatures are always exact.
        """
        raise NotImplementedError

    @classmethod
    def conversion_options(cls) -> List[ReaderOption]:
        return []

    def set_conversion_options(self, options: Optional[Dict[str, Any]] = None) -> None:
        self._options = dict(options or {})
