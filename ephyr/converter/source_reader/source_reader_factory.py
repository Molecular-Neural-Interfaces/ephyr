# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

from ._exceptions import WrongSourceReaderError
from .weegit_reader import WeegitSourceReader
from .open_ephys_source_reader import OpenEphysSourceReader
from .intan_rhs_source_reader import IntanRhdSourceReader, IntanRhsSourceReader
from .edf_source_reader import EdfSourceReader
from .abf_source_reader import AbfSourceReader
from .daq_source_reader import DaqSourceReader
from .xdat_source_reader import XdatSourceReader
from .ncs_source_reader import NcsSourceReader
from .nwb_source_reader import NwbSourceReader
from pathlib import Path


class SourceReaderFactory:
    @staticmethod
    def get_reader(experiment_path: Path):
        for reader_class in (WeegitSourceReader,
                             AbfSourceReader,
                             EdfSourceReader,
                             DaqSourceReader,
                             XdatSourceReader,
                             NcsSourceReader,
                             NwbSourceReader,
                             OpenEphysSourceReader,
                             IntanRhdSourceReader,
                             IntanRhsSourceReader,):
            try:
                reader_class.try_to_open(experiment_path)
                return reader_class(experiment_path)
            except WrongSourceReaderError:
                pass

        raise ValueError(f"Unsupported experiment format: {experiment_path}")
