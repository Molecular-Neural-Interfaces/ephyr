# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

import json
import numpy as np
from pathlib import Path
from typing import Tuple

from ._exceptions import WrongSourceReaderError
from .abstract_source_reader import AbstractSourceReader, AbstractDataWriter
from ephyr.core.header import Header, ChannelInfo


class WeegitDataWriter(AbstractDataWriter):
    def __init__(self, header: Header, lfp_path: Path):
        self._header = header
        self._lfp_path = lfp_path
        self._chunk_start = 0
        self._chunk_size = 512
        self._total_samples = sum(self._header.number_of_points_per_sweep)

    def __iter__(self) -> "AbstractDataWriter":
        self._chunk_start = 0
        self._lfp_memmap = np.memmap(self._lfp_path,
                                     dtype='int16',
                                     mode='r',
                                     shape=(self._header.number_of_sweeps,
                                            self._header.number_of_points_per_sweep[0],
                                            self._header.number_of_channels,))
        self._lfp_memmap = self._lfp_memmap.reshape(-1, self._header.number_of_channels)
        return self

    def __next__(self) -> np.typing.NDArray[np.int16]:
        if self._chunk_start == self._total_samples:
            del self._lfp_memmap
            raise StopIteration

        _chunk_end = min(self._chunk_start + self._chunk_size, self._total_samples)
        data = self._lfp_memmap[self._chunk_start:_chunk_end]
        self._chunk_start = _chunk_end
        return data.T.copy(order='C')

    def total_chunks(self, header: Header) -> int:
        total_points = sum(header.number_of_points_per_sweep)
        return max(1, (total_points + self._chunk_size - 1) // self._chunk_size)


class WeegitSourceReader(AbstractSourceReader):
    def __init__(self, experiment_path: Path):
        super().__init__(experiment_path)
        self._header = None

    LFP_EXTENSION = ".lfp"

    @classmethod
    def _try_to_open(cls, experiment_path: Path):
        cls.weegit_paths(experiment_path)

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

    def __iter__(self):
        self._header_num = 0
        return self

    def __next__(self):
        # fixme: we assume that there is only one header for all records
        if self._header_num > 0:
            raise StopIteration

        header_path, lfp_path = self.weegit_paths(self._experiment_path)
        header = self._init_header(header_path)
        data_stream = WeegitDataWriter(header, lfp_path)
        self._header_num += 1
        return header, data_stream

    def _init_header(self, header_path: Path) -> Header:
        with open(header_path) as f:
            header = json.load(f)

        channel_info = ChannelInfo(
            name=header["channelinfo"]["name"],
            probe=header["channelinfo"]["probe"],
            units=header["channelinfo"]["units"],
            analog_min=header["channelinfo"]["analogmin"],
            analog_max=header["channelinfo"]["analogmax"],
            digital_min=header["channelinfo"]["digitalmin"],
            digital_max=header["channelinfo"]["digitalmax"],
            prefiltering=header["channelinfo"]["prefiltering"],
            number_of_points_per_channel=header["channelinfo"]["pts"]
        )

        return Header(
            type_before_conversion=header["type"],
            name_before_conversion=header["name"],
            creation_date_before_conversion=header["date"],
            creation_time_before_conversion=header["time"],
            sample_interval_microseconds=header["si"],
            sample_rate=self.sample_interval_microseconds_to_sample_rate(header["si"]),
            number_of_channels=header["nCh"],
            number_of_sweeps=header["nSw"],
            number_of_points_per_sweep=[header["ptSw"]] * header["nSw"],
            channel_info=channel_info
        )
