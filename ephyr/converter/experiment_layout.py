# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path

from ephyr import settings


def sweep_dirname(sweep_idx: int) -> str:
    return f"{settings.SIGNAL_DATA_SWEEP_SUBFOLDER_PREFIX}{int(sweep_idx)}"


def channel_samples_filename(channel_idx: int) -> str:
    return f"{settings.SIGNAL_DATA_CHANNEL_FILE_PREFIX}{int(channel_idx)}{settings.SIGNAL_DATA_EXTENSION}"


def sweep_dir(experiment_folder: Path, sweep_idx: int) -> Path:
    return experiment_folder / settings.SIGNAL_DATA_SUBFOLDER / sweep_dirname(sweep_idx)


def channel_samples_path(experiment_folder: Path, sweep_idx: int, channel_idx: int) -> Path:
    return sweep_dir(experiment_folder, sweep_idx) / channel_samples_filename(channel_idx)
