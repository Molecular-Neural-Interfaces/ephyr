from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import pyedflib

from ._exceptions import WrongSourceReaderError
from .abstract_source_reader import AbstractSourceReader, AbstractDataWriter
from weegit.core.header import Header, ChannelInfo

_CHUNK_SAMPLES = 512


def _unit_ascii(unit: str) -> str:
    return (unit or "").strip().replace("µ", "u").replace("μ", "u")


def _same_sample_rate(sample_rates: np.ndarray) -> float:
    if len(sample_rates) == 0:
        raise ValueError("EDF file contains no signals")
    sample_rate = float(sample_rates[0])
    if sample_rate <= 0:
        raise ValueError("EDF file has invalid sample rate")
    if not np.allclose(sample_rates.astype(float), sample_rate, rtol=0, atol=1e-9):
        raise ValueError(
            "EDF signals have different sample rates; Weegit currently supports one sample rate per experiment."
        )
    return sample_rate


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
    def __init__(self, experiment_path: Path, n_channels: int, n_samples: int):
        self._experiment_path = experiment_path
        self._n_channels = n_channels
        self._n_samples = n_samples
        self._sample_pos = 0
        self._reader: Optional[pyedflib.EdfReader] = None

    def __iter__(self) -> "EdfDataWriter":
        self._sample_pos = 0
        self._reader = pyedflib.EdfReader(str(self._experiment_path))
        return self

    def __next__(self) -> np.ndarray:
        if self._reader is None:
            self._reader = pyedflib.EdfReader(str(self._experiment_path))
        if self._sample_pos >= self._n_samples:
            self._reader.close()
            self._reader = None
            raise StopIteration

        end = min(self._sample_pos + _CHUNK_SAMPLES, self._n_samples)
        width = end - self._sample_pos
        chunk = np.empty((self._n_channels, width), dtype=np.int16)
        for ch_idx in range(self._n_channels):
            data = self._reader.readSignal(ch_idx, self._sample_pos, width, digital=True)
            chunk[ch_idx, :] = np.asarray(data, dtype=np.int16)
        self._sample_pos = end
        return chunk

    def total_chunks(self, header: Header) -> int:
        total_points = sum(header.number_of_points_per_sweep)
        return max(1, (total_points + _CHUNK_SAMPLES - 1) // _CHUNK_SAMPLES)


class EdfSourceReader(AbstractSourceReader):
    def __init__(self, experiment_path: Path):
        super().__init__(experiment_path)
        self._yielded = False

    @classmethod
    def _try_to_open(cls, experiment_path: Path) -> None:
        if not experiment_path.is_file() or experiment_path.suffix.lower() != ".edf":
            raise WrongSourceReaderError(cls)
        try:
            reader = pyedflib.EdfReader(str(experiment_path))
            reader.close()
        except Exception:
            raise WrongSourceReaderError(cls)

    def __iter__(self) -> "EdfSourceReader":
        self._yielded = False
        return self

    def __next__(self) -> Tuple[Header, EdfDataWriter]:
        if self._yielded:
            raise StopIteration
        self._yielded = True

        reader = pyedflib.EdfReader(str(self._experiment_path))
        try:
            header, n_channels, n_samples = self._init_header(reader)
        finally:
            reader.close()

        return header, EdfDataWriter(self._experiment_path, n_channels, n_samples)

    def _init_header(self, reader: pyedflib.EdfReader) -> Tuple[Header, int, int]:
        n_channels = int(reader.signals_in_file)
        if n_channels <= 0:
            raise ValueError(f"EDF file contains no signals: {self._experiment_path}")

        sample_rate = _same_sample_rate(reader.getSampleFrequencies())
        n_samples_per_channel = [int(n) for n in reader.getNSamples()]
        if len(set(n_samples_per_channel)) != 1:
            raise ValueError(
                "EDF signals have different sample counts; Weegit currently supports aligned signals only."
            )
        n_samples = n_samples_per_channel[0]
        signal_headers = reader.getSignalHeaders()
        start_dt = reader.getStartdatetime()
        if not isinstance(start_dt, datetime):
            start_dt = datetime.fromtimestamp(self._experiment_path.stat().st_mtime)

        names: List[str] = []
        units: List[str] = []
        probes: List[str] = []
        analog_min: List[float] = []
        analog_max: List[float] = []
        digital_min: List[int] = []
        digital_max: List[int] = []
        prefiltering: List[str] = []

        labels = reader.getSignalLabels()
        for ch_idx in range(n_channels):
            signal_header = signal_headers[ch_idx]
            names.append(str(labels[ch_idx] or f"EDF {ch_idx}"))
            units.append(_unit_ascii(str(signal_header.get("dimension", ""))))
            probes.append(str(signal_header.get("transducer", "")))
            analog_min.append(_as_float(signal_header.get("physical_min"), reader.getPhysicalMinimum(ch_idx)))
            analog_max.append(_as_float(signal_header.get("physical_max"), reader.getPhysicalMaximum(ch_idx)))
            digital_min.append(_as_int(signal_header.get("digital_min"), reader.getDigitalMinimum(ch_idx)))
            digital_max.append(_as_int(signal_header.get("digital_max"), reader.getDigitalMaximum(ch_idx)))
            prefiltering.append(str(signal_header.get("prefilter", "") or reader.getPrefilter(ch_idx) or ""))

        channel_info = ChannelInfo(
            name=names,
            probe=probes,
            units=units,
            analog_min=analog_min,
            analog_max=analog_max,
            digital_min=digital_min,
            digital_max=digital_max,
            prefiltering=prefiltering,
            number_of_points_per_channel=n_samples_per_channel,
        )

        header = Header(
            type_before_conversion="edf",
            name_before_conversion=self._experiment_path.name,
            creation_date_before_conversion=str(start_dt.date()),
            creation_time_before_conversion=str(start_dt.time()),
            sample_interval_microseconds=1e6 / sample_rate,
            sample_rate=sample_rate,
            number_of_channels=n_channels,
            number_of_sweeps=1,
            number_of_points_per_sweep=[n_samples],
            channel_info=channel_info,
        )
        return header, n_channels, n_samples
