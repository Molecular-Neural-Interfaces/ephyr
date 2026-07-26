from typing import List, Dict, Any, Optional
import numpy as np
from pathlib import Path
from datetime import datetime
import struct
import os

from ._exceptions import WrongSourceReaderError
from .abstract_source_reader import AbstractSourceReader, AbstractDataWriter
from weegit.core.header import Header, ChannelInfo


def _resolve_intan_folder(experiment_path: Path) -> Path:
    if experiment_path.is_dir():
        return experiment_path
    if experiment_path.is_file() and experiment_path.suffix.lower() in {".rhs", ".rhd", ".xml"}:
        return experiment_path.parent
    return experiment_path


class IntanRhsDataWriter(AbstractDataWriter):
    def __init__(self, ordered_rhs_files: List[Path], total_blocks_num: int, expected_channels_count: int):
        self._ordered_rhs_files = ordered_rhs_files
        self._total_blocks_num = total_blocks_num
        self._expected_channels_count = expected_channels_count

        self._cur_header = None
        self._cur_fid = None
        self._cur_filename = None
        self._cur_file_idx = 0
        self._cur_data_idx = 0
        self._cur_filesize = 0
        self._cur_num_blocks = 0
        self._cur_num_samples = 0

    def __iter__(self) -> "AbstractDataWriter":
        self._reset(check_end=False, increment_file_idx=False)
        return self

    def __next__(self) -> np.typing.NDArray[np.int16]:
        if self._cur_file_idx == len(self._ordered_rhs_files):
            raise StopIteration

        if self._cur_fid is None:
            self._cur_filename = self._ordered_rhs_files[self._cur_file_idx]
            self._cur_fid = open(self._cur_filename, "rb")
            self._cur_filesize = os.path.getsize(self._cur_filename)

        if self._cur_header is None:
            self._cur_header = read_header(self._cur_fid)
            data_present, self._cur_filesize, self._cur_num_blocks, self._cur_num_samples = (
                calculate_data_size(self._cur_header, self._cur_filename, self._cur_fid))
            if not data_present:
                self._reset(check_end=False, increment_file_idx=True)

        data = read_one_data_block(self._cur_header, self._cur_fid)
        self._cur_data_idx += 1
        if self._cur_data_idx == self._cur_num_blocks:
            self._reset(check_end=True, increment_file_idx=True)

        amplifier_data = (data['amplifier_data'].astype(np.int32) - 32768).astype(np.int16)
        board_adc_data = (data['board_adc_data'].astype(np.int32) - 32768).astype(np.int16)
        if board_adc_data.size:
            chunk = np.vstack((amplifier_data, board_adc_data))
        else:
            chunk = amplifier_data
        if chunk.shape[0] != self._expected_channels_count:
            raise ValueError(
                f"Unexpected number of channels in rhs block: {chunk.shape[0]} != {self._expected_channels_count}"
            )
        return chunk

    def total_chunks(self, header: Header) -> int:
        return self._total_blocks_num

    def _reset(self, check_end: bool = False, increment_file_idx: bool = False):
        if check_end:
            check_end_of_file(self._cur_filesize, self._cur_fid)

        if increment_file_idx:
            self._cur_file_idx += 1

        if self._cur_fid is not None:
            self._cur_fid.close()

        self._cur_fid = None
        self._cur_header = None
        self._cur_data_idx = 0


class IntanRhsSourceReader(AbstractSourceReader):
    """
    Data formats: https://intantech.com/files/Intan_RHS2000_data_file_formats.pdf
    """
    def __init__(self, experiment_path: Path):
        super().__init__(experiment_path)
        self._source_folder = _resolve_intan_folder(experiment_path)
        self._header = None
        self._group_rhs_files_into_single_sweep = True

    @staticmethod
    def _list_ordered_rhs_files(experiment_path: Path):
        experiment_folder = _resolve_intan_folder(experiment_path)
        if not experiment_folder.is_dir():
            return []

        rhs_files = [item for item in experiment_folder.iterdir() if item.is_file() and item.suffix.lower() == ".rhs"]
        rhs_files.sort(key=lambda x: os.path.getmtime(x))
        return rhs_files

    def get_rhs_files_count(self) -> int:
        return len(self._list_ordered_rhs_files(self._source_folder))

    def get_intan_files_count(self) -> int:
        return self.get_rhs_files_count()

    @classmethod
    def _try_to_open(cls, experiment_path: Path):
        if len(cls._list_ordered_rhs_files(experiment_path)) == 0:
            raise WrongSourceReaderError(cls)

    def __iter__(self):
        self._header_num = 0
        return self

    def __next__(self):
        # fixme: we assume that there is only one header for all records
        if self._header_num > 0:
            raise StopIteration

        ordered_rhs_files = self._list_ordered_rhs_files(self._source_folder)
        header, total_blocks_num = self._init_header(ordered_rhs_files)
        data_stream = IntanRhsDataWriter(ordered_rhs_files, total_blocks_num, header.number_of_channels)
        self._header_num += 1
        return header, data_stream

    def _init_header(self, ordered_rhs_files: List[Path]):
        channels_number: Optional[int] = None
        sample_rate: Optional[float] = None
        channel_names: List[str] = []
        probes: List[str] = []
        units: List[str] = []
        analog_min: List[float] = []
        analog_max: List[float] = []
        digital_min: List[int] = []
        digital_max: List[int] = []
        prefiltering: List[str] = []
        impedance_ohm: List[Optional[float]] = []
        points_per_file: List[int] = []
        date = ""
        time = ""
        total_blocks_num = 0
        first_amplifier_channels = 0
        first_board_adc_channels = 0
        metadata_initialized = False

        def _channel_name(channel: Dict[str, Any]) -> str:
            return (channel.get("custom_channel_name")
                    or channel.get("native_channel_name")
                    or f"Ch{channel.get('native_order', 0)}")

        def _prefiltering_text(rhs_header: Dict[str, Any]) -> str:
            freq = rhs_header.get("frequency_parameters", {})
            hp = freq.get("actual_lower_bandwidth")
            lp = freq.get("actual_upper_bandwidth")
            notch = freq.get("notch_filter_frequency", 0)
            parts = []
            if hp is not None:
                parts.append(f"HP: {hp:.3f} Hz")
            if lp is not None:
                parts.append(f"LP: {lp:.3f} Hz")
            if notch:
                parts.append(f"Notch: {notch:.0f} Hz")
            return ", ".join(parts)

        for idx, rhs_filepath in enumerate(ordered_rhs_files):
            with open(rhs_filepath, "rb") as fid:
                header = read_header(fid)
                data_present, filesize, num_blocks, num_samples = (
                    calculate_data_size(header, rhs_filepath, fid))
                if not data_present:
                    continue

                points_per_file.append(int(num_samples))
                total_blocks_num += num_blocks
                if not metadata_initialized:
                    first_amplifier_channels = int(header['num_amplifier_channels'])
                    first_board_adc_channels = int(header['num_board_adc_channels'])
                    channels_number = first_amplifier_channels + first_board_adc_channels
                    sample_rate = float(header['sample_rate'])
                    filter_str = _prefiltering_text(header)

                    amplifier_channels = list(header.get("amplifier_channels", []))
                    board_adc_channels = list(header.get("board_adc_channels", []))
                    for amplifier_channel in amplifier_channels:
                        channel_names.append(_channel_name(amplifier_channel))
                        probes.append(str(amplifier_channel.get("port_name", "")))
                        units.append("V")
                        analog_min.append(-0.00638976)
                        analog_max.append(0.00638976)
                        digital_min.append(-2 ** 15)
                        digital_max.append(2 ** 15)
                        prefiltering.append(filter_str)
                        impedance_ohm.append(amplifier_channel.get("electrode_impedance_magnitude", None) or None)

                    for adc_channel in board_adc_channels:
                        channel_names.append(_channel_name(adc_channel))
                        probes.append("Board ADC")
                        units.append("V")
                        analog_min.append(-10.24)
                        analog_max.append(10.24)
                        digital_min.append(-2 ** 15)
                        digital_max.append(2 ** 15)
                        prefiltering.append(filter_str)
                        impedance_ohm.append(None)

                    file_creation_time = datetime.fromtimestamp(os.path.getmtime(rhs_filepath))
                    date = str(file_creation_time.date())
                    time = str(file_creation_time.time())
                    metadata_initialized = True
                else:
                    if int(header['num_amplifier_channels']) != first_amplifier_channels:
                        raise ValueError("RHS files have inconsistent amplifier channel count")
                    if int(header['num_board_adc_channels']) != first_board_adc_channels:
                        raise ValueError("RHS files have inconsistent board ADC channel count")
                    if abs(float(header['sample_rate']) - float(sample_rate)) > 1e-9:
                        raise ValueError("RHS files have inconsistent sample rate")

        if channels_number is None or sample_rate is None:
            raise ValueError(f"Failed to parse rhs data from {self._source_folder}")
        if not points_per_file:
            raise ValueError(f"RHS files contain no data: {self._source_folder}")

        if self._group_rhs_files_into_single_sweep:
            points_per_sweep = [sum(points_per_file)]
            sweeps_num = 1
        else:
            points_per_sweep = points_per_file
            sweeps_num = len(points_per_sweep)

        total_points = sum(points_per_sweep)

        channel_info = ChannelInfo(
            name=channel_names,
            probe=probes,
            units=units,
            analog_min=analog_min,
            analog_max=analog_max,
            digital_min=digital_min,
            digital_max=digital_max,
            prefiltering=prefiltering,
            number_of_points_per_channel=[total_points] * channels_number,
            impedance_ohm=impedance_ohm,
        )

        header = Header(
            type_before_conversion="rhs",
            name_before_conversion=self._source_folder.name,
            creation_date_before_conversion=date,
            creation_time_before_conversion=time,
            sample_interval_microseconds=1e6 / sample_rate,
            sample_rate=sample_rate,
            number_of_channels=len(channel_names),
            number_of_sweeps=sweeps_num,
            number_of_points_per_sweep=points_per_sweep,
            channel_info=channel_info
        )
        return header, total_blocks_num

    def set_conversion_options(self, options: Optional[Dict[str, Any]] = None) -> None:
        opts = options or {}
        if "group_rhs_files_into_single_sweep" in opts:
            self._group_rhs_files_into_single_sweep = bool(opts["group_rhs_files_into_single_sweep"])
        if "group_intan_files_into_single_sweep" in opts:
            self._group_rhs_files_into_single_sweep = bool(opts["group_intan_files_into_single_sweep"])


class IntanRhdDataWriter(AbstractDataWriter):
    def __init__(self, ordered_rhd_files: List[Path], total_blocks_num: int, expected_channels_count: int):
        self._ordered_rhd_files = ordered_rhd_files
        self._total_blocks_num = total_blocks_num
        self._expected_channels_count = expected_channels_count

        self._cur_header = None
        self._cur_fid = None
        self._cur_filename = None
        self._cur_file_idx = 0
        self._cur_data_idx = 0
        self._cur_filesize = 0
        self._cur_num_blocks = 0

    def __iter__(self) -> "IntanRhdDataWriter":
        self._reset(check_end=False, increment_file_idx=False)
        return self

    def __next__(self) -> np.typing.NDArray[np.int16]:
        while self._cur_file_idx < len(self._ordered_rhd_files):
            if self._cur_fid is None:
                self._cur_filename = self._ordered_rhd_files[self._cur_file_idx]
                self._cur_fid = open(self._cur_filename, "rb")
                self._cur_filesize = os.path.getsize(self._cur_filename)

            if self._cur_header is None:
                self._cur_header = read_rhd_header(self._cur_fid)
                data_present, _, self._cur_num_blocks, _ = calculate_rhd_data_size(
                    self._cur_header, self._cur_filename, self._cur_fid
                )
                if not data_present:
                    self._reset(check_end=False, increment_file_idx=True)
                    continue

            data = read_one_rhd_data_block(self._cur_header, self._cur_fid)
            self._cur_data_idx += 1
            if self._cur_data_idx == self._cur_num_blocks:
                self._reset(check_end=True, increment_file_idx=True)

            amplifier_data = (data["amplifier_data"].astype(np.int32) - 32768).astype(np.int16)
            board_adc_data = (data["board_adc_data"].astype(np.int32) - 32768).astype(np.int16)
            if board_adc_data.size:
                chunk = np.vstack((amplifier_data, board_adc_data))
            else:
                chunk = amplifier_data
            if chunk.shape[0] != self._expected_channels_count:
                raise ValueError(
                    f"Unexpected number of channels in rhd block: {chunk.shape[0]} != {self._expected_channels_count}"
                )
            return chunk

        raise StopIteration

    def total_chunks(self, header: Header) -> int:
        return self._total_blocks_num

    def _reset(self, check_end: bool = False, increment_file_idx: bool = False):
        if check_end:
            check_end_of_file(self._cur_filesize, self._cur_fid)

        if increment_file_idx:
            self._cur_file_idx += 1

        if self._cur_fid is not None:
            self._cur_fid.close()

        self._cur_fid = None
        self._cur_header = None
        self._cur_data_idx = 0


class IntanRhdSourceReader(AbstractSourceReader):
    """
    Data formats: https://intantech.com/files/Intan_RHD2000_data_file_formats.pdf
    """
    def __init__(self, experiment_path: Path):
        super().__init__(experiment_path)
        self._source_folder = _resolve_intan_folder(experiment_path)
        self._header_num = 0
        self._group_rhd_files_into_single_sweep = True

    @staticmethod
    def _list_ordered_rhd_files(experiment_path: Path):
        experiment_folder = _resolve_intan_folder(experiment_path)
        if not experiment_folder.is_dir():
            return []

        rhd_files = [item for item in experiment_folder.iterdir() if item.is_file() and item.suffix.lower() == ".rhd"]
        rhd_files.sort(key=lambda x: os.path.getmtime(x))
        return rhd_files

    def get_rhd_files_count(self) -> int:
        return len(self._list_ordered_rhd_files(self._source_folder))

    def get_intan_files_count(self) -> int:
        return self.get_rhd_files_count()

    @classmethod
    def _try_to_open(cls, experiment_path: Path):
        rhd_files = cls._list_ordered_rhd_files(experiment_path)
        if not rhd_files:
            raise WrongSourceReaderError(cls)
        try:
            with open(rhd_files[0], "rb") as fid:
                read_rhd_header(fid)
        except Exception:
            raise WrongSourceReaderError(cls)

    def __iter__(self):
        self._header_num = 0
        return self

    def __next__(self):
        if self._header_num > 0:
            raise StopIteration

        ordered_rhd_files = self._list_ordered_rhd_files(self._source_folder)
        header, total_blocks_num = self._init_header(ordered_rhd_files)
        data_stream = IntanRhdDataWriter(ordered_rhd_files, total_blocks_num, header.number_of_channels)
        self._header_num += 1
        return header, data_stream

    def _init_header(self, ordered_rhd_files: List[Path]):
        channels_number: Optional[int] = None
        sample_rate: Optional[float] = None
        channel_names: List[str] = []
        probes: List[str] = []
        units: List[str] = []
        analog_min: List[float] = []
        analog_max: List[float] = []
        digital_min: List[int] = []
        digital_max: List[int] = []
        prefiltering: List[str] = []
        impedance_ohm: List[Optional[float]] = []
        points_per_file: List[int] = []
        date = ""
        time = ""
        total_blocks_num = 0
        first_amplifier_channels = 0
        first_board_adc_channels = 0
        metadata_initialized = False

        def _channel_name(channel: Dict[str, Any]) -> str:
            return (channel.get("custom_channel_name")
                    or channel.get("native_channel_name")
                    or f"Ch{channel.get('native_order', 0)}")

        def _prefiltering_text(rhd_header: Dict[str, Any]) -> str:
            freq = rhd_header.get("frequency_parameters", {})
            hp = freq.get("actual_lower_bandwidth")
            lp = freq.get("actual_upper_bandwidth")
            notch = freq.get("notch_filter_frequency", 0)
            parts = []
            if hp is not None:
                parts.append(f"HP: {hp:.3f} Hz")
            if lp is not None:
                parts.append(f"LP: {lp:.3f} Hz")
            if notch:
                parts.append(f"Notch: {notch:.0f} Hz")
            return ", ".join(parts)

        for rhd_filepath in ordered_rhd_files:
            with open(rhd_filepath, "rb") as fid:
                header = read_rhd_header(fid)
                data_present, _, num_blocks, num_samples = calculate_rhd_data_size(header, rhd_filepath, fid)
                if not data_present:
                    continue

                points_per_file.append(int(num_samples))
                total_blocks_num += num_blocks
                if not metadata_initialized:
                    first_amplifier_channels = int(header["num_amplifier_channels"])
                    first_board_adc_channels = int(header["num_board_adc_channels"])
                    channels_number = first_amplifier_channels + first_board_adc_channels
                    sample_rate = float(header["sample_rate"])
                    filter_str = _prefiltering_text(header)

                    for amplifier_channel in header.get("amplifier_channels", []):
                        channel_names.append(_channel_name(amplifier_channel))
                        probes.append(str(amplifier_channel.get("port_name", "")))
                        units.append("V")
                        analog_min.append(-0.00638976)
                        analog_max.append(0.006389565)
                        digital_min.append(-2 ** 15)
                        digital_max.append(2 ** 15 - 1)
                        prefiltering.append(filter_str)
                        impedance_ohm.append(amplifier_channel.get("electrode_impedance_magnitude", None) or None)

                    board_adc_scale = rhd_board_adc_scale_volts(header)
                    for adc_channel in header.get("board_adc_channels", []):
                        channel_names.append(_channel_name(adc_channel))
                        probes.append("Board ADC")
                        units.append("V")
                        analog_min.append(-2 ** 15 * board_adc_scale)
                        analog_max.append((2 ** 15 - 1) * board_adc_scale)
                        digital_min.append(-2 ** 15)
                        digital_max.append(2 ** 15 - 1)
                        prefiltering.append(filter_str)
                        impedance_ohm.append(None)

                    file_creation_time = datetime.fromtimestamp(os.path.getmtime(rhd_filepath))
                    date = str(file_creation_time.date())
                    time = str(file_creation_time.time())
                    metadata_initialized = True
                else:
                    if int(header["num_amplifier_channels"]) != first_amplifier_channels:
                        raise ValueError("RHD files have inconsistent amplifier channel count")
                    if int(header["num_board_adc_channels"]) != first_board_adc_channels:
                        raise ValueError("RHD files have inconsistent board ADC channel count")
                    if abs(float(header["sample_rate"]) - float(sample_rate)) > 1e-9:
                        raise ValueError("RHD files have inconsistent sample rate")

        if channels_number is None or sample_rate is None:
            raise ValueError(f"Failed to parse rhd data from {self._source_folder}")
        if not points_per_file:
            raise ValueError(f"RHD files contain no data: {self._source_folder}")

        if self._group_rhd_files_into_single_sweep:
            points_per_sweep = [sum(points_per_file)]
            sweeps_num = 1
        else:
            points_per_sweep = points_per_file
            sweeps_num = len(points_per_sweep)

        total_points = sum(points_per_sweep)
        channel_info = ChannelInfo(
            name=channel_names,
            probe=probes,
            units=units,
            analog_min=analog_min,
            analog_max=analog_max,
            digital_min=digital_min,
            digital_max=digital_max,
            prefiltering=prefiltering,
            number_of_points_per_channel=[total_points] * channels_number,
            impedance_ohm=impedance_ohm,
        )

        header = Header(
            type_before_conversion="rhd",
            name_before_conversion=self._source_folder.name,
            creation_date_before_conversion=date,
            creation_time_before_conversion=time,
            sample_interval_microseconds=1e6 / sample_rate,
            sample_rate=sample_rate,
            number_of_channels=len(channel_names),
            number_of_sweeps=sweeps_num,
            number_of_points_per_sweep=points_per_sweep,
            channel_info=channel_info,
        )
        return header, total_blocks_num

    def set_conversion_options(self, options: Optional[Dict[str, Any]] = None) -> None:
        opts = options or {}
        if "group_rhd_files_into_single_sweep" in opts:
            self._group_rhd_files_into_single_sweep = bool(opts["group_rhd_files_into_single_sweep"])
        if "group_intan_files_into_single_sweep" in opts:
            self._group_rhd_files_into_single_sweep = bool(opts["group_intan_files_into_single_sweep"])


def read_rhd_header(fid):
    check_rhd_magic_number(fid)
    header = {}
    read_version_number(header, fid)
    header["num_samples_per_data_block"] = 60 if header["version"]["major"] == 1 else 128
    read_rhd_sample_rate_and_freq_settings(header, fid)
    read_notch_filter_frequency(header, fid)
    read_impedance_test_frequencies(header, fid)
    create_rhd_frequency_parameters(header)
    read_notes(header, fid)
    read_rhd_optional_header_fields(header, fid)
    initialize_rhd_channels(header)
    read_rhd_signal_summary(header, fid)
    return header


def check_rhd_magic_number(fid):
    magic_number, = struct.unpack("<I", fid.read(4))
    if magic_number != int("c6912702", 16):
        raise UnrecognizedFileError("Unrecognized file type.")


def read_rhd_sample_rate_and_freq_settings(header, fid):
    header["sample_rate"], = struct.unpack("<f", fid.read(4))
    (
        header["dsp_enabled"],
        header["actual_dsp_cutoff_frequency"],
        header["actual_lower_bandwidth"],
        header["actual_upper_bandwidth"],
        header["desired_dsp_cutoff_frequency"],
        header["desired_lower_bandwidth"],
        header["desired_upper_bandwidth"],
    ) = struct.unpack("<hffffff", fid.read(26))


def read_rhd_optional_header_fields(header, fid):
    version = header["version"]
    header["num_temp_sensor_channels"] = 0
    if (version["major"] == 1 and version["minor"] >= 1) or version["major"] > 1:
        header["num_temp_sensor_channels"], = struct.unpack("<h", fid.read(2))

    header["eval_board_mode"] = 0
    if (version["major"] == 1 and version["minor"] >= 3) or version["major"] > 1:
        header["eval_board_mode"], = struct.unpack("<h", fid.read(2))

    header["reference_channel"] = ""
    if version["major"] > 1:
        header["reference_channel"] = read_qstring(fid)


def create_rhd_frequency_parameters(header):
    freq = {}
    freq["amplifier_sample_rate"] = header["sample_rate"]
    freq["aux_input_sample_rate"] = header["sample_rate"] / 4
    freq["supply_voltage_sample_rate"] = header["sample_rate"] / header["num_samples_per_data_block"]
    freq["board_adc_sample_rate"] = header["sample_rate"]
    freq["board_dig_in_sample_rate"] = header["sample_rate"]
    copy_from_header(header, freq, "desired_dsp_cutoff_frequency")
    copy_from_header(header, freq, "actual_dsp_cutoff_frequency")
    copy_from_header(header, freq, "dsp_enabled")
    copy_from_header(header, freq, "desired_lower_bandwidth")
    copy_from_header(header, freq, "actual_lower_bandwidth")
    copy_from_header(header, freq, "desired_upper_bandwidth")
    copy_from_header(header, freq, "actual_upper_bandwidth")
    copy_from_header(header, freq, "notch_filter_frequency")
    copy_from_header(header, freq, "desired_impedance_test_frequency")
    copy_from_header(header, freq, "actual_impedance_test_frequency")
    header["frequency_parameters"] = freq


def initialize_rhd_channels(header):
    header["spike_triggers"] = []
    header["amplifier_channels"] = []
    header["aux_input_channels"] = []
    header["supply_voltage_channels"] = []
    header["board_adc_channels"] = []
    header["board_dig_in_channels"] = []
    header["board_dig_out_channels"] = []


def read_rhd_signal_summary(header, fid):
    number_of_signal_groups, = struct.unpack("<h", fid.read(2))
    for signal_group in range(1, number_of_signal_groups + 1):
        read_rhd_signal_group(header, fid, signal_group)
    header["num_amplifier_channels"] = len(header["amplifier_channels"])
    header["num_aux_input_channels"] = len(header["aux_input_channels"])
    header["num_supply_voltage_channels"] = len(header["supply_voltage_channels"])
    header["num_board_adc_channels"] = len(header["board_adc_channels"])
    header["num_board_dig_in_channels"] = len(header["board_dig_in_channels"])
    header["num_board_dig_out_channels"] = len(header["board_dig_out_channels"])


def read_rhd_signal_group(header, fid, signal_group):
    signal_group_name = read_qstring(fid)
    signal_group_prefix = read_qstring(fid)
    signal_group_enabled, signal_group_num_channels, _ = struct.unpack("<hhh", fid.read(6))

    if signal_group_num_channels <= 0 or signal_group_enabled <= 0:
        for _ in range(signal_group_num_channels):
            skip_rhd_channel(fid)
        return

    for _ in range(signal_group_num_channels):
        new_channel = {
            "port_name": signal_group_name,
            "port_prefix": signal_group_prefix,
            "port_number": signal_group,
            "native_channel_name": read_qstring(fid),
            "custom_channel_name": read_qstring(fid),
        }
        (
            new_channel["native_order"],
            new_channel["custom_order"],
            signal_type,
            channel_enabled,
            new_channel["chip_channel"],
            new_channel["board_stream"],
        ) = struct.unpack("<hhhhhh", fid.read(12))
        new_trigger_channel = {}
        (
            new_trigger_channel["voltage_trigger_mode"],
            new_trigger_channel["voltage_threshold"],
            new_trigger_channel["digital_trigger_channel"],
            new_trigger_channel["digital_edge_polarity"],
        ) = struct.unpack("<hhhh", fid.read(8))
        (
            new_channel["electrode_impedance_magnitude"],
            new_channel["electrode_impedance_phase"],
        ) = struct.unpack("<ff", fid.read(8))

        if channel_enabled:
            append_new_rhd_channel(header, new_channel, new_trigger_channel, signal_type)


def skip_rhd_channel(fid):
    read_qstring(fid)
    read_qstring(fid)
    fid.read(12 + 8 + 8)


def append_new_rhd_channel(header, new_channel, new_trigger_channel, signal_type):
    if signal_type == 0:
        header["amplifier_channels"].append(new_channel)
        header["spike_triggers"].append(new_trigger_channel)
    elif signal_type == 1:
        header["aux_input_channels"].append(new_channel)
    elif signal_type == 2:
        header["supply_voltage_channels"].append(new_channel)
    elif signal_type == 3:
        header["board_adc_channels"].append(new_channel)
    elif signal_type == 4:
        header["board_dig_in_channels"].append(new_channel)
    elif signal_type == 5:
        header["board_dig_out_channels"].append(new_channel)
    else:
        raise UnknownChannelTypeError("Unknown RHD channel type.")


def rhd_board_adc_scale_volts(header) -> float:
    board_mode = int(header.get("eval_board_mode", 0))
    if board_mode == 1:
        return 152.59e-6
    if board_mode == 13:
        return 312.5e-6
    return 50.354e-6


def get_rhd_bytes_per_data_block(header):
    samples_per_block = header["num_samples_per_data_block"]
    bytes_per_block = samples_per_block * 4
    bytes_per_block += samples_per_block * 2 * header["num_amplifier_channels"]
    bytes_per_block += (samples_per_block // 4) * 2 * header["num_aux_input_channels"]
    bytes_per_block += 2 * header["num_supply_voltage_channels"]
    bytes_per_block += 2 * header["num_temp_sensor_channels"]
    bytes_per_block += samples_per_block * 2 * header["num_board_adc_channels"]
    if header["num_board_dig_in_channels"] > 0:
        bytes_per_block += samples_per_block * 2
    if header["num_board_dig_out_channels"] > 0:
        bytes_per_block += samples_per_block * 2
    return bytes_per_block


def calculate_rhd_data_size(header, filename, fid):
    bytes_per_block = get_rhd_bytes_per_data_block(header)
    filesize = os.path.getsize(filename)
    bytes_remaining = filesize - fid.tell()
    data_present = bytes_remaining > 0
    if bytes_remaining % bytes_per_block != 0:
        raise FileSizeError(
            "Something is wrong with RHD file size: should have a whole number of data blocks"
        )
    num_blocks = int(bytes_remaining / bytes_per_block)
    num_samples = int(header["num_samples_per_data_block"] * num_blocks)
    return data_present, filesize, num_blocks, num_samples


def read_one_rhd_data_block(header, fid):
    samples_per_block = header["num_samples_per_data_block"]
    block_data = {
        "amplifier_data": np.zeros(
            [header["num_amplifier_channels"], samples_per_block], dtype=np.uint16
        ),
        "board_adc_data": np.zeros(
            [header["num_board_adc_channels"], samples_per_block], dtype=np.uint16
        ),
    }

    np.fromfile(fid, dtype="<i4", count=samples_per_block)
    read_rhd_uint16_matrix(fid, block_data["amplifier_data"], samples_per_block)
    skip_rhd_uint16(fid, (samples_per_block // 4) * header["num_aux_input_channels"])
    skip_rhd_uint16(fid, header["num_supply_voltage_channels"])
    skip_rhd_uint16(fid, header["num_temp_sensor_channels"])
    read_rhd_uint16_matrix(fid, block_data["board_adc_data"], samples_per_block)
    if header["num_board_dig_in_channels"] > 0:
        skip_rhd_uint16(fid, samples_per_block)
    if header["num_board_dig_out_channels"] > 0:
        skip_rhd_uint16(fid, samples_per_block)
    return block_data


def read_rhd_uint16_matrix(fid, dest, samples_per_block):
    num_channels = dest.shape[0]
    if num_channels < 1:
        return
    tmp = np.fromfile(fid, dtype="<u2", count=samples_per_block * num_channels)
    dest[:, :] = tmp.reshape(num_channels, samples_per_block)


def skip_rhd_uint16(fid, count):
    if count > 0:
        fid.seek(2 * int(count), os.SEEK_CUR)


def find_channel_in_group(channel_name, signal_group):
    """Finds a channel with this name in this group, returning whether or not
    it's present and, if so, the position of this channel in signal_group.
    """
    for count, this_channel in enumerate(signal_group):
        if this_channel['custom_channel_name'] == channel_name:
            return True, count
    return False, 0


def find_channel_in_header(channel_name, header):
    """Looks through all present signal groups in header, searching for
    'channel_name'. If found, return the signal group and the index of that
    channel within the group.
    """
    signal_group_name = ''
    if 'amplifier_channels' in header:
        channel_found, channel_index = find_channel_in_group(
            channel_name, header['amplifier_channels'])
        if channel_found:
            signal_group_name = 'amplifier_channels'

    if not channel_found and 'dc_amplifier_channels' in header:
        channel_found, channel_index = find_channel_in_group(
            channel_name, header['dc_amplifier_channels'])
        if channel_found:
            signal_group_name = 'dc_amplifier_channels'

    if not channel_found and 'stim_channels' in header:
        channel_found, channel_index = find_channel_in_group(
            channel_name, header['stim_channels'])
        if channel_found:
            signal_group_name = 'stim_channels'

    if not channel_found and 'amp_settle_channels' in header:
        channel_found, channel_index = find_channel_in_group(
            channel_name, header['amp_settle_channels'])
        if channel_found:
            signal_group_name = 'amp_settle_channels'

    if not channel_found and 'charge_recovery_channels' in header:
        channel_found, channel_index = find_channel_in_group(
            channel_name, header['charge_recovery_channels'])
        if channel_found:
            signal_group_name = 'charge_recovery_channels'

    if not channel_found and 'compliance_limit_channels' in header:
        channel_found, channel_index = find_channel_in_group(
            channel_name, header['compliance_limit_channels'])
        if channel_found:
            signal_group_name = 'compliance_limit_channels'

    if not channel_found and 'board_adc_channels' in header:
        channel_found, channel_index = find_channel_in_group(
            channel_name, header['board_adc_channels'])
        if channel_found:
            signal_group_name = 'board_adc_channels'

    if not channel_found and 'board_dac_channels' in header:
        channel_found, channel_index = find_channel_in_group(
            channel_name, header['board_dac_channels'])
        if channel_found:
            signal_group_name = 'board_dac_channels'

    if not channel_found and 'board_dig_in_channels' in header:
        channel_found, channel_index = find_channel_in_group(
            channel_name, header['board_dig_in_channels'])
        if channel_found:
            signal_group_name = 'board_dig_in_channels'

    if not channel_found and 'board_dig_out_channels' in header:
        channel_found, channel_index = find_channel_in_group(
            channel_name, header['board_dig_out_channels'])
        if channel_found:
            signal_group_name = 'board_dig_out_channels'

    if channel_found:
        return True, signal_group_name, channel_index

    return False, '', 0


def read_header(fid):
    """Reads the Intan File Format header from the given file.
    """
    check_magic_number(fid)

    header = {}

    read_version_number(header, fid)
    set_num_samples_per_data_block(header)

    read_sample_rate(header, fid)
    read_freq_settings(header, fid)

    read_notch_filter_frequency(header, fid)
    read_impedance_test_frequencies(header, fid)
    read_amp_settle_mode(header, fid)
    read_charge_recovery_mode(header, fid)

    create_frequency_parameters(header)

    read_stim_step_size(header, fid)
    read_recovery_current_limit(header, fid)
    read_recovery_target_voltage(header, fid)

    read_notes(header, fid)
    read_dc_amp_saved(header, fid)
    read_eval_board_mode(header, fid)
    read_reference_channel(header, fid)

    initialize_channels(header)
    read_signal_summary(header, fid)

    return header


def check_magic_number(fid):
    """Checks magic number at beginning of file to verify this is an Intan
    Technologies RHS data file.
    """
    magic_number, = struct.unpack('<I', fid.read(4))
    if magic_number != int('d69127ac', 16):
        raise UnrecognizedFileError('Unrecognized file type.')


def read_version_number(header, fid):
    """Reads version number (major and minor) from fid. Stores them into
    header['version']['major'] and header['version']['minor'].
    """
    version = {}
    (version['major'], version['minor']) = struct.unpack('<hh', fid.read(4))
    header['version'] = version


def set_num_samples_per_data_block(header):
    """Determines how many samples are present per data block (always 128 for
    RHS files)
    """
    header['num_samples_per_data_block'] = 128


def read_sample_rate(header, fid):
    """Reads sample rate from fid. Stores it into header['sample_rate'].
    """
    header['sample_rate'], = struct.unpack('<f', fid.read(4))


def read_freq_settings(header, fid):
    """Reads amplifier frequency settings from fid. Stores them in 'header'
    dict.
    """
    (header['dsp_enabled'],
     header['actual_dsp_cutoff_frequency'],
     header['actual_lower_bandwidth'],
     header['actual_lower_settle_bandwidth'],
     header['actual_upper_bandwidth'],
     header['desired_dsp_cutoff_frequency'],
     header['desired_lower_bandwidth'],
     header['desired_lower_settle_bandwidth'],
     header['desired_upper_bandwidth']) = struct.unpack('<hffffffff',
                                                        fid.read(34))


def read_notch_filter_frequency(header, fid):
    """Reads notch filter mode from fid, and stores frequency (in Hz) in
    'header' dict.
    """
    notch_filter_mode, = struct.unpack('<h', fid.read(2))
    header['notch_filter_frequency'] = 0
    if notch_filter_mode == 1:
        header['notch_filter_frequency'] = 50
    elif notch_filter_mode == 2:
        header['notch_filter_frequency'] = 60


def read_impedance_test_frequencies(header, fid):
    """Reads desired and actual impedance test frequencies from fid, and stores
    them (in Hz) in 'freq' dicts.
    """
    (header['desired_impedance_test_frequency'],
     header['actual_impedance_test_frequency']) = (
         struct.unpack('<ff', fid.read(8)))


def read_amp_settle_mode(header, fid):
    """Reads amp settle mode from fid, and stores it in 'header' dict.
    """
    header['amp_settle_mode'], = struct.unpack('<h', fid.read(2))


def read_charge_recovery_mode(header, fid):
    """Reads charge recovery mode from fid, and stores it in 'header' dict.
    """
    header['charge_recovery_mode'], = struct.unpack('<h', fid.read(2))


def create_frequency_parameters(header):
    """Copy various frequency-related parameters (set in other functions) to
    the dict at header['frequency_parameters'].
    """
    freq = {}
    freq['amplifier_sample_rate'] = header['sample_rate']
    freq['board_adc_sample_rate'] = header['sample_rate']
    freq['board_dig_in_sample_rate'] = header['sample_rate']
    copy_from_header(header, freq, 'desired_dsp_cutoff_frequency')
    copy_from_header(header, freq, 'actual_dsp_cutoff_frequency')
    copy_from_header(header, freq, 'dsp_enabled')
    copy_from_header(header, freq, 'desired_lower_bandwidth')
    copy_from_header(header, freq, 'desired_lower_settle_bandwidth')
    copy_from_header(header, freq, 'actual_lower_bandwidth')
    copy_from_header(header, freq, 'actual_lower_settle_bandwidth')
    copy_from_header(header, freq, 'desired_upper_bandwidth')
    copy_from_header(header, freq, 'actual_upper_bandwidth')
    copy_from_header(header, freq, 'notch_filter_frequency')
    copy_from_header(header, freq, 'desired_impedance_test_frequency')
    copy_from_header(header, freq, 'actual_impedance_test_frequency')
    header['frequency_parameters'] = freq


def copy_from_header(header, freq_params, key):
    """Copy from header
    """
    freq_params[key] = header[key]


def read_stim_step_size(header, fid):
    """Reads stim step size from fid, and stores it in 'header' dict.
    """
    header['stim_step_size'], = struct.unpack('f', fid.read(4))


def read_recovery_current_limit(header, fid):
    """Reads charge recovery current limit from fid, and stores it in 'header'
    dict.
    """
    header['recovery_current_limit'], = struct.unpack('f', fid.read(4))


def read_recovery_target_voltage(header, fid):
    """Reads charge recovery target voltage from fid, and stores it in 'header'
    dict.
    """
    header['recovery_target_voltage'], = struct.unpack('f', fid.read(4))


def read_notes(header, fid):
    """Reads notes as QStrings from fid, and stores them as strings in
    header['notes'] dict.
    """
    header['notes'] = {'note1': read_qstring(fid),
                       'note2': read_qstring(fid),
                       'note3': read_qstring(fid)}


def read_dc_amp_saved(header, fid):
    """Reads whether DC amp data was saved from fid, and stores it in 'header'
    dict.
    """
    header['dc_amplifier_data_saved'], = struct.unpack('<h', fid.read(2))


def read_eval_board_mode(header, fid):
    """Stores eval board mode in header['eval_board_mode'].
    """
    header['eval_board_mode'], = struct.unpack('<h', fid.read(2))


def read_reference_channel(header, fid):
    """Reads name of reference channel as QString from fid, and stores it as
    a string in header['reference_channel'].
    """
    header['reference_channel'] = read_qstring(fid)


def initialize_channels(header):
    """Creates empty lists for each type of data channel and stores them in
    'header' dict.
    """
    header['spike_triggers'] = []
    header['amplifier_channels'] = []
    header['board_adc_channels'] = []
    header['board_dac_channels'] = []
    header['board_dig_in_channels'] = []
    header['board_dig_out_channels'] = []


def read_signal_summary(header, fid):
    """Reads signal summary from data file header and stores information for
    all signal groups and their channels in 'header' dict.
    """
    number_of_signal_groups, = struct.unpack('<h', fid.read(2))
    for signal_group in range(1, number_of_signal_groups + 1):
        add_signal_group_information(header, fid, signal_group)
    add_num_channels(header)


def add_signal_group_information(header, fid, signal_group):
    """Adds information for a signal group and all its channels to 'header'
    dict.
    """
    signal_group_name = read_qstring(fid)
    signal_group_prefix = read_qstring(fid)
    (signal_group_enabled, signal_group_num_channels, _) = struct.unpack(
        '<hhh', fid.read(6))

    if signal_group_num_channels > 0 and signal_group_enabled > 0:
        for _ in range(0, signal_group_num_channels):
            add_channel_information(header, fid, signal_group_name,
                                    signal_group_prefix, signal_group)


def add_channel_information(header, fid, signal_group_name,
                            signal_group_prefix, signal_group):
    """Reads a new channel's information from fid and appends it to 'header'
    dict.
    """
    (new_channel, new_trigger_channel, channel_enabled,
     signal_type) = read_new_channel(
         fid, signal_group_name, signal_group_prefix, signal_group)
    append_new_channel(header, new_channel, new_trigger_channel,
                       channel_enabled, signal_type)


def read_new_channel(fid, signal_group_name, signal_group_prefix,
                     signal_group):
    """Reads a new channel's information from fid.
    """
    new_channel = {'port_name': signal_group_name,
                   'port_prefix': signal_group_prefix,
                   'port_number': signal_group}
    new_channel['native_channel_name'] = read_qstring(fid)
    new_channel['custom_channel_name'] = read_qstring(fid)
    (new_channel['native_order'],
     new_channel['custom_order'],
     signal_type, channel_enabled,
     new_channel['chip_channel'],
     _,  # ignore command_stream
     new_channel['board_stream']) = (
         struct.unpack('<hhhhhHh', fid.read(14)))
    new_trigger_channel = {}
    (new_trigger_channel['voltage_trigger_mode'],
     new_trigger_channel['voltage_threshold'],
     new_trigger_channel['digital_trigger_channel'],
     new_trigger_channel['digital_edge_polarity']) = (
         struct.unpack('<hhhh', fid.read(8)))
    (new_channel['electrode_impedance_magnitude'],
     new_channel['electrode_impedance_phase']) = (
         struct.unpack('<ff', fid.read(8)))

    return new_channel, new_trigger_channel, channel_enabled, signal_type


def append_new_channel(header, new_channel, new_trigger_channel,
                       channel_enabled, signal_type):
    """"Appends 'new_channel' to 'header' dict depending on if channel is
    enabled and the signal type.
    """
    if not channel_enabled:
        return

    if signal_type == 0:
        header['amplifier_channels'].append(new_channel)
        header['spike_triggers'].append(new_trigger_channel)
    elif signal_type == 1:
        raise UnknownChannelTypeError('No aux input signals in RHS format.')
    elif signal_type == 2:
        raise UnknownChannelTypeError('No Vdd signals in RHS format.')
    elif signal_type == 3:
        header['board_adc_channels'].append(new_channel)
    elif signal_type == 4:
        header['board_dac_channels'].append(new_channel)
    elif signal_type == 5:
        header['board_dig_in_channels'].append(new_channel)
    elif signal_type == 6:
        header['board_dig_out_channels'].append(new_channel)
    else:
        raise UnknownChannelTypeError('Unknown channel type.')


def add_num_channels(header):
    """Adds channel numbers for all signal types to 'header' dict.
    """
    header['num_amplifier_channels'] = len(header['amplifier_channels'])
    header['num_board_adc_channels'] = len(header['board_adc_channels'])
    header['num_board_dac_channels'] = len(header['board_dac_channels'])
    header['num_board_dig_in_channels'] = len(header['board_dig_in_channels'])
    header['num_board_dig_out_channels'] = len(
        header['board_dig_out_channels'])


def header_to_result(header, result):
    """Merges header information from .rhs file into a common 'result' dict.
    If any fields have been allocated but aren't relevant (for example, no
    channels of this type exist), does not copy those entries into 'result'.
    """
    stim_parameters = {}
    stim_parameters['stim_step_size'] = header['stim_step_size']
    stim_parameters['charge_recovery_current_limit'] = \
        header['recovery_current_limit']
    stim_parameters['charge_recovery_target_voltage'] = \
        header['recovery_target_voltage']
    stim_parameters['amp_settle_mode'] = header['amp_settle_mode']
    stim_parameters['charge_recovery_mode'] = header['charge_recovery_mode']
    result['stim_parameters'] = stim_parameters

    result['notes'] = header['notes']

    if header['num_amplifier_channels'] > 0:
        result['spike_triggers'] = header['spike_triggers']
        result['amplifier_channels'] = header['amplifier_channels']

    result['notes'] = header['notes']
    result['frequency_parameters'] = header['frequency_parameters']
    result['reference_channel'] = header['reference_channel']

    if header['num_board_adc_channels'] > 0:
        result['board_adc_channels'] = header['board_adc_channels']

    if header['num_board_dac_channels'] > 0:
        result['board_dac_channels'] = header['board_dac_channels']

    if header['num_board_dig_in_channels'] > 0:
        result['board_dig_in_channels'] = header['board_dig_in_channels']

    if header['num_board_dig_out_channels'] > 0:
        result['board_dig_out_channels'] = header['board_dig_out_channels']

    return result


def plural(number_of_items):
    """Utility function to pluralize words based on the number of items.
    """
    if number_of_items == 1:
        return ''
    return 's'


def get_bytes_per_data_block(header):
    """Calculates the number of bytes in each 128 sample datablock."""
    # RHS files always have 128 samples per data block.
    # Use this number along with numbers of channels to accrue a sum of how
    # many bytes each data block should contain.
    num_samples_per_data_block = 128

    # Timestamps (one channel always present): Start with 4 bytes per sample.
    bytes_per_block = bytes_per_signal_type(
        num_samples_per_data_block,
        1,
        4)

    # Amplifier data: Add 2 bytes per sample per enabled amplifier channel.
    bytes_per_block += bytes_per_signal_type(
        num_samples_per_data_block,
        header['num_amplifier_channels'],
        2)

    # DC Amplifier data (absent if flag was off).
    if header['dc_amplifier_data_saved']:
        bytes_per_block += bytes_per_signal_type(
            num_samples_per_data_block,
            header['num_amplifier_channels'],
            2)

    # Stimulation data: Add 2 bytes per sample per enabled amplifier channel.
    bytes_per_block += bytes_per_signal_type(
        num_samples_per_data_block,
        header['num_amplifier_channels'],
        2)

    # Analog inputs: Add 2 bytes per sample per enabled analog input channel.
    bytes_per_block += bytes_per_signal_type(
        num_samples_per_data_block,
        header['num_board_adc_channels'],
        2)

    # Analog outputs: Add 2 bytes per sample per enabled analog output channel.
    bytes_per_block += bytes_per_signal_type(
        num_samples_per_data_block,
        header['num_board_dac_channels'],
        2)

    # Digital inputs: Add 2 bytes per sample.
    # Note that if at least 1 channel is enabled, a single 16-bit sample
    # is saved, with each bit corresponding to an individual channel.
    if header['num_board_dig_in_channels'] > 0:
        bytes_per_block += bytes_per_signal_type(
            num_samples_per_data_block,
            1,
            2)

    # Digital outputs: Add 2 bytes per sample.
    # Note that if at least 1 channel is enabled, a single 16-bit sample
    # is saved, with each bit corresponding to an individual channel.
    if header['num_board_dig_out_channels'] > 0:
        bytes_per_block += bytes_per_signal_type(
            num_samples_per_data_block,
            1,
            2)

    return bytes_per_block


def bytes_per_signal_type(num_samples, num_channels, bytes_per_sample):
    """Calculates the number of bytes, per data block, for a signal type
    provided the number of samples (per data block), the number of enabled
    channels, and the size of each sample in bytes.
    """
    return num_samples * num_channels * bytes_per_sample


def read_one_data_block(header, fid):
    """Reads one 128 sample data block from fid and returns it as a dictionary.
    """
    samples_per_block = header['num_samples_per_data_block']

    # Create a new dictionary for this block
    block_data = {}

    # Initialize arrays for this block with int16 dtype
    block_data['t'] = np.zeros(samples_per_block, np.int_)
    block_data['amplifier_data'] = np.zeros(
        [header['num_amplifier_channels'], samples_per_block], dtype=np.uint16)

    if header['dc_amplifier_data_saved']:
        block_data['dc_amplifier_data'] = np.zeros(
            [header['num_amplifier_channels'], samples_per_block], dtype=np.uint16)

    block_data['stim_data_raw'] = np.zeros(
        [header['num_amplifier_channels'], samples_per_block], dtype=np.uint16)
    block_data['stim_data'] = np.zeros(
        [header['num_amplifier_channels'], samples_per_block], dtype=np.uint16)

    block_data['board_adc_data'] = np.zeros(
        [header['num_board_adc_channels'], samples_per_block], dtype=np.uint16)

    block_data['board_dac_data'] = np.zeros(
        [header['num_board_dac_channels'], samples_per_block], dtype=np.uint16)

    block_data['board_dig_in_data'] = np.zeros(
        [header['num_board_dig_in_channels'], samples_per_block], dtype=np.bool_)
    block_data['board_dig_in_raw'] = np.zeros(samples_per_block, dtype=np.uint)

    block_data['board_dig_out_data'] = np.zeros(
        [header['num_board_dig_out_channels'], samples_per_block], dtype=np.bool_)
    block_data['board_dig_out_raw'] = np.zeros(samples_per_block, dtype=np.uint)

    # Read data into the block_data dictionary
    read_timestamps(fid, block_data, 0, samples_per_block)
    read_analog_signals(fid, block_data, 0, samples_per_block, header)
    read_digital_signals(fid, block_data, 0, samples_per_block, header)

    return block_data


def read_timestamps(fid, data, index, num_samples):
    """Reads timestamps from binary file as a NumPy array, indexing them
    into 'data'.
    """
    start = index
    end = start + num_samples
    format_sign = 'i'
    format_expression = '<' + format_sign * num_samples
    read_length = 4 * num_samples
    data['t'][start:end] = np.array(struct.unpack(
        format_expression, fid.read(read_length)))


def read_analog_signals(fid, data, index, samples_per_block, header):
    """Reads all analog signal types present in RHD files: amplifier_data,
    aux_input_data, supply_voltage_data, temp_sensor_data, and board_adc_data,
    into 'data' dict.
    """

    read_analog_signal_type(fid,
                            data['amplifier_data'],
                            index,
                            samples_per_block,
                            header['num_amplifier_channels'])

    if header['dc_amplifier_data_saved']:
        read_analog_signal_type(fid,
                                data['dc_amplifier_data'],
                                index,
                                samples_per_block,
                                header['num_amplifier_channels'])

    read_analog_signal_type(fid,
                            data['stim_data_raw'],
                            index,
                            samples_per_block,
                            header['num_amplifier_channels'])

    read_analog_signal_type(fid,
                            data['board_adc_data'],
                            index,
                            samples_per_block,
                            header['num_board_adc_channels'])

    read_analog_signal_type(fid,
                            data['board_dac_data'],
                            index,
                            samples_per_block,
                            header['num_board_dac_channels'])


def read_digital_signals(fid, data, index, samples_per_block, header):
    """Reads all digital signal types present in RHD files: board_dig_in_raw
    and board_dig_out_raw, into 'data' dict.
    """

    read_digital_signal_type(fid,
                             data['board_dig_in_raw'],
                             index,
                             samples_per_block,
                             header['num_board_dig_in_channels'])

    read_digital_signal_type(fid,
                             data['board_dig_out_raw'],
                             index,
                             samples_per_block,
                             header['num_board_dig_out_channels'])


def read_analog_signal_type(fid, dest, start, num_samples, num_channels):
    """Reads data from binary file as a NumPy array, indexing them into
    'dest', which should be an analog signal type within 'data', for example
    data['amplifier_data'] or data['aux_input_data']. Each sample is assumed
    to be of dtype 'uint16'.
    """

    if num_channels < 1:
        return
    end = start + num_samples
    tmp = np.fromfile(fid, dtype='uint16', count=num_samples*num_channels)
    dest[range(num_channels), start:end] = (
        tmp.reshape(num_channels, num_samples))


def read_digital_signal_type(fid, dest, start, num_samples, num_channels):
    """Reads data from binary file as a NumPy array, indexing them into
    'dest', which should be a digital signal type within 'data', either
    data['board_dig_in_raw'] or data['board_dig_out_raw'].
    """

    if num_channels < 1:
        return
    end = start + num_samples
    dest[start:end] = np.array(struct.unpack(
        '<' + 'H' * num_samples, fid.read(2 * num_samples)))


def read_qstring(fid):
    """Reads Qt style QString.

    The first 32-bit unsigned number indicates the length of the string
    (in bytes). If this number equals 0xFFFFFFFF, the string is null.

    Strings are stored as unicode.
    """
    length, = struct.unpack('<I', fid.read(4))
    if length == int('ffffffff', 16):
        return ""

    if length > (os.fstat(fid.fileno()).st_size - fid.tell() + 1):
        raise QStringError('Length too long.')

    # Convert length from bytes to 16-bit Unicode words.
    length = int(length / 2)

    data = []
    for _ in range(0, length):
        c, = struct.unpack('<H', fid.read(2))
        data.append(c)

    a = ''.join([chr(c) for c in data])

    return a


def calculate_data_size(header, filename, fid):
    """Calculates how much data is present in this file. Returns:
    data_present: Bool, whether any data is present in file
    filesize: Int, size (in bytes) of file
    num_blocks: Int, number of 60 or 128-sample data blocks present
    num_samples: Int, number of samples present in file
    """
    bytes_per_block = get_bytes_per_data_block(header)

    # Determine filesize and if any data is present.
    filesize = os.path.getsize(filename)
    data_present = False
    bytes_remaining = filesize - fid.tell()
    if bytes_remaining > 0:
        data_present = True

    # If the file size is somehow different than expected, raise an error.
    if bytes_remaining % bytes_per_block != 0:
        raise FileSizeError(
            'Something is wrong with file size : '
            'should have a whole number of data blocks')

    # Calculate how many data blocks are present.
    num_blocks = int(bytes_remaining / bytes_per_block)

    num_samples = calculate_num_samples(header, num_blocks)

    return data_present, filesize, num_blocks, num_samples


def calculate_num_samples(header, num_data_blocks):
    """Calculates number of samples in file (per channel).
    """
    return int(header['num_samples_per_data_block'] * num_data_blocks)


def advance_index(index, samples_per_block):
    """Advances index used for data access by suitable values per data block.
    """
    # For RHS, all signals sampled at the same sample rate:
    # Index should be incremented by samples_per_block every data block.
    index += samples_per_block
    return index


def check_end_of_file(filesize, fid):
    """Checks that the end of the file was reached at the expected position.
    If not, raise FileSizeError.
    """
    bytes_remaining = filesize - fid.tell()
    if bytes_remaining != 0:
        raise FileSizeError('Error: End of file not reached.')


class UnrecognizedFileError(Exception):
    """Exception returned when reading a file as an RHS header yields an
    invalid magic number (indicating this is not an RHS header file).
    """


class UnknownChannelTypeError(Exception):
    """Exception returned when a channel field in RHS header does not have
    a recognized signal_type value. Accepted values are:
    0: amplifier channel
    1: aux input channel (RHD only, invalid for RHS)
    2: supply voltage channel (RHD only, invalid for RHS)
    3: board adc channel
    4: board dac channel
    5: dig in channel
    6: dig out channel
    """


class FileSizeError(Exception):
    """Exception returned when file reading fails due to the file size
    being invalid or the calculated file size differing from the actual
    file size.
    """


class QStringError(Exception):
    """Exception returned when reading a QString fails because it is too long.
    """


class ChannelNotFoundError(Exception):
    """Exception returned when plotting fails due to the specified channel
    not being found.
    """
