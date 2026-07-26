import json
import os

import numpy as np
from pathlib import Path
from typing import Tuple, Union, List, Optional

from weegit import settings
from weegit.converter.source_reader.source_reader_factory import SourceReaderFactory
from weegit.core.header import Header


class WeegitIO:
    @staticmethod
    def weegit_dir_of_experiment(experiment_folder: Path):
        is_weegit = WeegitIO.is_valid_weegit_folder(experiment_folder)
        if not is_weegit:
            weegit_experiment_folder_path = experiment_folder.parent / f"{experiment_folder.stem}{settings.WEEGIT_FOLDER_SUFFIX}"
        else:
            weegit_experiment_folder_path = experiment_folder

        return is_weegit, weegit_experiment_folder_path

    @staticmethod
    def is_valid_weegit_folder(experiment_folder: Path):
        header_file = experiment_folder / settings.HEADER_FILENAME
        # lfp_file = experiment_folder / settings.LFP_FILENAME
        return os.path.exists(header_file)  # and os.path.exists(lfp_file)

    @staticmethod
    def convert_from_source_to_weegit(
            experiment_path: Path,
            out_dir: Optional[Path] = None,
            reader_options: Optional[dict] = None,
    ):
        reader = SourceReaderFactory.get_reader(experiment_path)
        reader.set_conversion_options(reader_options or {})
        if out_dir is None:
            out_dir = experiment_path.parent / f"{experiment_path.stem}{settings.WEEGIT_FOLDER_SUFFIX}"

        lfp_out_dir = out_dir / settings.SIGNAL_DATA_SUBFOLDER
        add_ons_dir = out_dir / settings.ADD_ONS_SUBFOLDER
        add_ons_data_dir = add_ons_dir / settings.ADD_ONS_DATA_SUBFOLDER
        out_dir.mkdir(exist_ok=True)
        lfp_out_dir.mkdir(exist_ok=True)
        add_ons_dir.mkdir(exist_ok=True)
        add_ons_data_dir.mkdir(exist_ok=True)

        # fixme: assume only one header/data_stream for now. Otherwise will be rewritten
        for header, data_stream in reader:
            header_path = out_dir / settings.HEADER_FILENAME
            with open(header_path, 'w', encoding='utf-8') as f:
                json.dump(header.model_dump(), f, indent=2)

            channel_data_paths = yield from data_stream.to_dest_folder(out_dir, header)
            # out_dirs.append(out_dir)
            for channel_data_path in channel_data_paths:
                os.chmod(channel_data_path, 0o444)  # Readonly

        yield 100

    @staticmethod
    def read_weegit(weegit_experiment_folder: Path,
                    extract_mode: int = 1,
                    extract_vector: Union[List[int], np.ndarray] = None,
                    each_point: int = 1) -> Tuple[Header, Tuple[Tuple[np.memmap, ...], ...]]:
        header_file = weegit_experiment_folder / settings.HEADER_FILENAME
        try:
            with open(header_file, 'r') as f:
                header_data = json.load(f)
                header = Header(**header_data)
        except FileNotFoundError:
            raise FileNotFoundError(f"Header file not found: {header_file}")
        except json.JSONDecodeError:
            raise ValueError(f"Invalid header file format: {header_file}")

        if extract_vector is None:
            extract_vector = [1]

        # Memory map the file for efficient reading
        points_per_sweep = list(header.number_of_points_per_sweep)
        if len(points_per_sweep) != header.number_of_sweeps:
            raise ValueError("Invalid header: number_of_points_per_sweep does not match number_of_sweeps")

        data_memmaps: List[Tuple[np.memmap, ...]] = []
        for sweep_idx, sweep_points in enumerate(points_per_sweep):
            sweep_memmaps: List[np.memmap] = []
            for ch_idx in range(header.number_of_channels):
                channel_lfp_file = (
                    weegit_experiment_folder
                    / settings.SIGNAL_DATA_SUBFOLDER
                    / f"{settings.SIGNAL_DATA_SWEEP_SUBFOLDER_PREFIX}{sweep_idx}"
                    / f"{ch_idx}{settings.SIGNAL_DATA_EXTENSION}"
                )
                data_memmap = np.memmap(
                    channel_lfp_file,
                    dtype='int16',
                    mode='r',
                    shape=(int(sweep_points),),
                )
                sweep_memmaps.append(data_memmap)
            data_memmaps.append(tuple(sweep_memmaps))
        # Handle different extraction modes
        # if extract_mode == 1:  # Extract all
        #     data_memmap = data_memmap[:, :, ::each_point]
        #     # data_memmap = np.transpose(data_memmap[:, ::each_point, :], (2, 0, 1))
        #     # data_memmap = np.transpose(data_memmap[:, ::each_point, :])
        #     # data_memmap = np.squeeze(data_memmap[:, ::each_point, :])
        # elif extract_mode == 2:  # Extract channels
        #     channels = np.array(extract_vector) - 1  # Convert to 0-based indexing
        #     data_memmap = data_memmap[:, channels, ::each_point]
        #     # data_memmap = np.transpose(data_memmap[channels, ::each_point, :], (2, 0, 1))
        #     # data_memmap = np.transpose(data_memmap[channels, ::each_point, :])
        #     # data_memmap = np.squeeze(data_memmap[channels, ::each_point, :])
        # elif extract_mode == 3:  # Extract sweeps
        #     sweeps = np.array(extract_vector) - 1
        #     data_memmap = data_memmap[sweeps, :, ::each_point]
        #     # data_memmap = np.transpose(data_memmap[:, ::each_point, sweeps], (2, 0, 1))
        #     # data_memmap = np.transpose(data_memmap[:, ::each_point, sweeps])
        #     # data_memmap = np.squeeze(data_memmap[:, ::each_point, sweeps])
        # elif extract_mode == 4:  # Extract points
        #     start, end = extract_vector
        #     # Validate and adjust point range
        #     start = max(1, min(start, self.header.ptSw))
        #     end = max(start, min(end, self.header.ptSw))
        #     data = data[:, :, start - 1:end:each_point]
        #     # data = np.transpose(data[:, start - 1:end:each_point, :], (2, 0, 1))
        #     # data = np.transpose(data[:, start - 1:end:each_point, :])
        #     # data = np.squeeze(data[:, start - 1:end:each_point, :])

        return header, tuple(data_memmaps)
