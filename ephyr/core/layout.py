# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

"""Paths inside a workspace folder; manifests store only the ids these paths are built from."""

from pathlib import Path

from ephyr import settings


def workspace_manifest_path(workspace_root: Path) -> Path:
    return workspace_root / settings.WORKSPACE_MANIFEST_FILENAME


def configs_dir(workspace_root: Path) -> Path:
    return workspace_root / settings.CONFIGS_SUBFOLDER


def config_dir(workspace_root: Path, config_id: str) -> Path:
    return configs_dir(workspace_root) / config_id


def config_manifest_path(workspace_root: Path, config_id: str) -> Path:
    return config_dir(workspace_root, config_id) / settings.CONFIG_MANIFEST_FILENAME


def records_dir(workspace_root: Path, config_id: str) -> Path:
    return config_dir(workspace_root, config_id) / settings.RECORDS_SUBFOLDER


def record_dir(workspace_root: Path, config_id: str, record_id: str) -> Path:
    return records_dir(workspace_root, config_id) / record_id


def record_manifest_path(record_folder: Path) -> Path:
    return record_folder / settings.RECORD_MANIFEST_FILENAME


def source_dir(record_folder: Path, source_id: str) -> Path:
    return record_folder / settings.SOURCES_SUBFOLDER / source_id


def channel_samples_filename(channel_idx: int) -> str:
    return f"{settings.SIGNAL_DATA_CHANNEL_FILE_PREFIX}{int(channel_idx)}{settings.SIGNAL_DATA_EXTENSION}"


def channel_samples_path(record_folder: Path, source_id: str, channel_idx: int) -> Path:
    return source_dir(record_folder, source_id) / channel_samples_filename(channel_idx)


def source_annotations_dir(record_folder: Path) -> Path:
    return record_folder / settings.SOURCE_ANNOTATIONS_SUBFOLDER


def source_events_path(record_folder: Path) -> Path:
    return source_annotations_dir(record_folder) / settings.EVENTS_FILENAME


def source_periods_path(record_folder: Path) -> Path:
    return source_annotations_dir(record_folder) / settings.PERIODS_FILENAME


def sessions_dir(record_folder: Path) -> Path:
    return record_folder / settings.SESSIONS_SUBFOLDER


def session_dir(record_folder: Path, session_name: str) -> Path:
    return sessions_dir(record_folder) / session_name


def add_ons_data_dir(record_folder: Path) -> Path:
    return record_folder / settings.ADD_ONS_SUBFOLDER / settings.ADD_ONS_DATA_SUBFOLDER
