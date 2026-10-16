# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

import json
from datetime import datetime
from pathlib import Path
from typing import Iterator, Tuple

import numpy as np

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


class WeegitDataWriter(AbstractDataWriter):
    """Samples of a .lfp file are stored as (sweeps, points, channels)."""

    _CHUNK_SIZE = 512

    def __init__(self, lfp_path: Path, n_sweeps: int, points_per_sweep: int, n_channels: int):
        self._lfp_path = lfp_path
        self._n_sweeps = n_sweeps
        self._points_per_sweep = points_per_sweep
        self._n_channels = n_channels

    @property
    def _total_samples(self) -> int:
        return self._n_sweeps * self._points_per_sweep

    def __iter__(self) -> Iterator[np.ndarray]:
        samples = np.memmap(self._lfp_path, dtype="int16", mode="r",
                            shape=(self._total_samples, self._n_channels))
        for start in range(0, self._total_samples, self._CHUNK_SIZE):
            end = min(start + self._CHUNK_SIZE, self._total_samples)
            yield samples[start:end].T.copy(order="C")

    def total_chunks(self) -> int:
        return max(1, (self._total_samples + self._CHUNK_SIZE - 1) // self._CHUNK_SIZE)


class WeegitSourceReader(AbstractSourceReader):
    format_name = "weegit"
    LFP_EXTENSION = ".lfp"

    @classmethod
    def _resolve_lfp_path(cls, experiment_path: Path) -> Path:
        if experiment_path.is_file():
            if experiment_path.name.endswith(cls.LFP_EXTENSION):
                return experiment_path
            raise WrongSourceReaderError(cls)

        if not experiment_path.is_dir():
            raise WrongSourceReaderError(cls)

        # A folder may hold several recordings: only an unambiguous one is accepted,
        # otherwise the user has to point at the exact .lfp file.
        lfp_files = sorted(experiment_path.glob(f"*{cls.LFP_EXTENSION}"))
        if len(lfp_files) != 1:
            raise WrongSourceReaderError(cls)
        return lfp_files[0]

    @classmethod
    def weegit_paths(cls, experiment_path: Path) -> Tuple[Path, Path]:
        lfp_path = cls._resolve_lfp_path(experiment_path)
        record_name = lfp_path.name[: -len(cls.LFP_EXTENSION)]

        for header_name in (f"{record_name}.header.json", f"{record_name}.json"):
            header_path = lfp_path.parent / header_name
            if header_path.is_file():
                return header_path, lfp_path

        raise WrongSourceReaderError(cls)

    @classmethod
    def resolve(cls, path: Path) -> SourceRef:
        header_path, lfp_path = cls.weegit_paths(path)
        return SourceRef(format=cls.format_name, kind="file", root=lfp_path, name=lfp_path.name,
                         files=[lfp_path, header_path])

    def probe(self, scan: bool = False) -> ConversionPlan:
        header_path, lfp_path = self.weegit_paths(self.ref.root)
        with open(header_path) as f:
            header = json.load(f)
        info = header["channelinfo"]
        sample_rate = 1e6 / float(header["si"])
        n_channels = int(header["nCh"])
        n_sweeps = int(header["nSw"])
        points = int(header["ptSw"])
        channels = [
            ChannelPlan(
                name=str(info["name"][idx]),
                units=canonical_unit_label(info["units"][idx]),
                analog_min=float(info["analogmin"][idx]),
                analog_max=float(info["analogmax"][idx]),
                digital_min=int(info["digitalmin"][idx]),
                digital_max=int(info["digitalmax"][idx]),
                probe=str(info["probe"][idx]),
                prefiltering=str(info["prefiltering"][idx]),
            )
            for idx in range(n_channels)
        ]
        source = SourcePlan(
            source_id="main",
            name="LFP",
            sample_rate=sample_rate,
            channels=channels,
            segments=contiguous_segments([points] * n_sweeps, sample_rate),
            segment_kind=SegmentKindEnum.SWEEP if n_sweeps > 1 else SegmentKindEnum.CONTINUOUS,
            source_format=str(header.get("type") or self.format_name),
            writer_factory=lambda: WeegitDataWriter(lfp_path, n_sweeps, points, n_channels),
        )
        start = ""
        try:
            start = datetime.fromisoformat(f"{header['date']}T{header['time']}").isoformat()
        except (KeyError, ValueError):
            pass
        return ConversionPlan(
            ref=self.ref,
            sources=[source],
            start_datetime=start,
            recording_name=str(header.get("name") or lfp_path.stem),
            reader_options=dict(self._options),
        )
