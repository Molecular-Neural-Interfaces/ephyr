# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

from abc import ABC, abstractmethod
from pathlib import Path
from abc import ABC, abstractmethod
from typing import Any, Tuple, List, Dict, Optional

import numpy as np

from ephyr import settings
from ephyr.core.header import Header
from ._exceptions import WrongSourceReaderError


class AbstractDataWriter(ABC):
    @abstractmethod
    def __iter__(self) -> "AbstractDataWriter":
        raise NotImplemented

    def __next__(self) -> np.ndarray[np.int16]:
        raise NotImplemented

    def to_dest_folder(self, dest_folder: Path, header: Header) -> List[Path]:
        total_chunks = self.total_chunks(header)
        points_per_sweep = list(header.number_of_points_per_sweep)
        if len(points_per_sweep) != header.number_of_sweeps:
            raise ValueError("Header is inconsistent: number_of_points_per_sweep does not match number_of_sweeps")
        if any(points < 0 for points in points_per_sweep):
            raise ValueError("Header is inconsistent: negative points per sweep")

        sweep_dirs = [
            dest_folder / settings.SIGNAL_DATA_SUBFOLDER / f"{settings.SIGNAL_DATA_SWEEP_SUBFOLDER_PREFIX}{sweep_idx}"
                      for sweep_idx in range(header.number_of_sweeps)]
        for sweep_dir in sweep_dirs:
            sweep_dir.mkdir(parents=True, exist_ok=True)

        channel_filepaths = []
        for sweep_idx in range(header.number_of_sweeps):
            for ch_idx in range(header.number_of_channels):
                channel_filepaths.append(
                    dest_folder / settings.SIGNAL_DATA_SUBFOLDER / f"{settings.SIGNAL_DATA_SWEEP_SUBFOLDER_PREFIX}{sweep_idx}" / f"{ch_idx}{settings.SIGNAL_DATA_EXTENSION}"
                )

        if header.number_of_sweeps == 0:
            return channel_filepaths

        current_sweep_idx = 0
        current_points_written = 0
        current_files: Optional[List[Any]] = None

        def open_sweep_files(sweep_idx: int) -> List[Any]:
            return [
                open(
                    dest_folder / settings.SIGNAL_DATA_SUBFOLDER / f"{settings.SIGNAL_DATA_SWEEP_SUBFOLDER_PREFIX}{sweep_idx}" / f"{ch_idx}{settings.SIGNAL_DATA_EXTENSION}",
                    "wb",
                )
                for ch_idx in range(header.number_of_channels)
            ]

        def close_sweep_files(files_to_close: Optional[List[Any]]) -> None:
            if not files_to_close:
                return
            for file in files_to_close:
                file.close()

        # Skip zero-length sweeps by creating empty files.
        while current_sweep_idx < header.number_of_sweeps and points_per_sweep[current_sweep_idx] == 0:
            empty_files = open_sweep_files(current_sweep_idx)
            close_sweep_files(empty_files)
            current_sweep_idx += 1

        if current_sweep_idx < header.number_of_sweeps:
            current_files = open_sweep_files(current_sweep_idx)

        processed_chunks = 0
        for i, chunk in enumerate(self):
            if chunk.ndim != 2 or chunk.shape[0] != header.number_of_channels:
                close_sweep_files(current_files)
                raise ValueError("DataWriter yielded invalid chunk shape")

            if current_files is None:
                close_sweep_files(current_files)
                raise ValueError("DataWriter produced more samples than sweeps can store")

            chunk_start = 0
            chunk_width = int(chunk.shape[1])
            while chunk_start < chunk_width:
                target_points = points_per_sweep[current_sweep_idx]
                remaining_in_sweep = target_points - current_points_written
                if remaining_in_sweep < 0:
                    close_sweep_files(current_files)
                    raise ValueError("Internal sweep writer state is inconsistent")
                take = min(remaining_in_sweep, chunk_width - chunk_start)
                if take > 0:
                    chunk_slice = chunk[:, chunk_start:chunk_start + take]
                    for ch_idx in range(header.number_of_channels):
                        current_files[ch_idx].write(chunk_slice[ch_idx, :].astype(np.int16).tobytes())
                    chunk_start += take
                    current_points_written += take

                if current_points_written == target_points:
                    close_sweep_files(current_files)
                    current_files = None
                    current_sweep_idx += 1
                    current_points_written = 0
                    while current_sweep_idx < header.number_of_sweeps and points_per_sweep[current_sweep_idx] == 0:
                        empty_files = open_sweep_files(current_sweep_idx)
                        close_sweep_files(empty_files)
                        current_sweep_idx += 1
                    if current_sweep_idx < header.number_of_sweeps:
                        current_files = open_sweep_files(current_sweep_idx)

            processed_chunks += 1
            if total_chunks > 0:
                yield min(int((processed_chunks / total_chunks) * 100), 99)
            else:
                yield 99

        close_sweep_files(current_files)

        if current_sweep_idx != header.number_of_sweeps:
            raise ValueError("Data stream ended before all sweep files were filled")

        return channel_filepaths

    @abstractmethod
    def total_chunks(self, header: Header) -> int:
        raise NotImplemented


class AbstractSourceReader(ABC):
    def __init__(self, experiment_path: Path):
        self._experiment_path = experiment_path

    @classmethod
    def try_to_open(cls, experiment_path):
        try:
            cls._try_to_open(experiment_path)
        except Exception:
            raise WrongSourceReaderError(cls)

    @abstractmethod
    def __iter__(self) -> "AbstractSourceReader":
        raise NotImplemented

    @abstractmethod
    def __next__(self) -> Tuple[Header, AbstractDataWriter]:
        raise NotImplemented

    @classmethod
    @abstractmethod
    def _try_to_open(cls, experiment_path):
        raise NotImplemented

    @classmethod
    def sample_interval_microseconds_to_sample_rate(cls, sample_interval_ms: float) -> float:
        sample_interval_seconds = sample_interval_ms / 1_000_000.0
        return 1.0 / sample_interval_seconds

    def set_conversion_options(self, options: Optional[Dict[str, Any]] = None) -> None:
        _ = options or {}
