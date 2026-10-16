# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Type

from ._exceptions import WrongSourceReaderError
from .abstract_source_reader import AbstractSourceReader, SourceRef
from .weegit_reader import WeegitSourceReader
from .open_ephys_source_reader import OpenEphysSourceReader
from .intan_rhs_source_reader import IntanRhdSourceReader, IntanRhsSourceReader
from .edf_source_reader import EdfSourceReader
from .abf_source_reader import AbfSourceReader
from .daq_source_reader import DaqSourceReader
from .xdat_source_reader import XdatSourceReader
from .ncs_source_reader import NcsSourceReader
from .mcs_source_reader import MCSSourceReader
from .nwb import NwbSourceReader

_READERS: List[Type[AbstractSourceReader]] = [
    WeegitSourceReader,
    AbfSourceReader,
    EdfSourceReader,
    DaqSourceReader,
    XdatSourceReader,
    NcsSourceReader,
    MCSSourceReader,
    NwbSourceReader,
    OpenEphysSourceReader,
    IntanRhdSourceReader,
    IntanRhsSourceReader,
]


class SourceReaderFactory:
    @staticmethod
    def resolve(path: Path) -> Tuple[Type[AbstractSourceReader], SourceRef]:
        for reader_class in _READERS:
            try:
                return reader_class, reader_class.try_resolve(Path(path))
            except WrongSourceReaderError:
                pass
        raise ValueError(f"Unsupported recording format: {path}")

    @staticmethod
    def get_reader(path: Path, options: Optional[Dict[str, Any]] = None) -> AbstractSourceReader:
        reader_class, ref = SourceReaderFactory.resolve(path)
        reader = reader_class(ref)
        reader.set_conversion_options(options or {})
        return reader

    @staticmethod
    def reader_for_format(source_format: str) -> Optional[Type[AbstractSourceReader]]:
        return next((reader for reader in _READERS if reader.format_name == source_format), None)
