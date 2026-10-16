# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

"""Workspace -> Config -> Record folders: creation, conversion into them, rename and removal."""

from __future__ import annotations

import os
import re
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Generator, List, Optional, Sequence, Tuple

from ephyr import settings
from ephyr.core import layout
from ephyr.core.annotations_io import EventRow, PeriodRow, write_events, write_periods
from ephyr.core.fingerprint import fingerprint_of_ref
from ephyr.core.manifests import (
    ChannelCalibration,
    ConfigManifest,
    Fingerprint,
    InputInfo,
    RecordManifest,
    RecordSource,
    WorkspaceManifest,
    read_manifest,
    write_manifest,
)
from ephyr.core.validation import build_spec, compare_signatures, match_config

_TRANSLIT = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh", "з": "z",
    "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya", "µ": "u", "μ": "u",
})
_SLUG_MAX_LENGTH = 48


class WorkspaceError(Exception):
    pass


class DuplicateRecordError(WorkspaceError):
    def __init__(self, config_id: str, record_id: str, config_name: str, record_name: str):
        super().__init__(f"This recording is already in the workspace: Config '{config_name}', Record '{record_name}'")
        self.config_id = config_id
        self.record_id = record_id


def slugify(name: str, fallback: str) -> str:
    text = (name or "").strip().lower().translate(_TRANSLIT)
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")[:_SLUG_MAX_LENGTH].strip("_")
    return text or fallback


def unique_id(name: str, taken: Sequence[str], fallback: str) -> str:
    base = slugify(name, fallback)
    taken_set = {item.lower() for item in taken}
    candidate = base
    counter = 2
    while candidate.lower() in taken_set:
        candidate = f"{base}_{counter}"
        counter += 1
    return candidate


def _make_writable_and_retry(function, path, _exc_info) -> None:
    os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    function(path)


def remove_tree(path: Path) -> None:
    """rmtree that also removes the read-only sample files."""
    if not path.exists():
        return
    shutil.rmtree(path, onerror=_make_writable_and_retry)


def disk_usage(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                pass
    return total


def format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


@dataclass(frozen=True)
class RecordLocation:
    config_id: str
    record_id: str


def find_workspace_root(path: Path) -> Optional[Path]:
    """Workspace folder containing `path`: the manifest itself, the folder, or anything inside it."""
    path = Path(path).expanduser().resolve()
    if path.is_file() and path.name == settings.WORKSPACE_MANIFEST_FILENAME:
        return path.parent
    candidate = path if path.is_dir() else path.parent
    for folder in (candidate, *candidate.parents):
        if layout.workspace_manifest_path(folder).is_file():
            return folder
    return None


class Workspace:
    def __init__(self, root: Path, manifest: WorkspaceManifest):
        self.root = Path(root)
        self.manifest = manifest
        self._configs: Dict[str, ConfigManifest] = {}
        self._records: Dict[Tuple[str, str], RecordManifest] = {}
        self.reload()

    # ----- creation and opening -----

    @staticmethod
    def default_folder_name(name: str) -> str:
        return f"{slugify(name, 'workspace')}{settings.EPHYR_FOLDER_SUFFIX}"

    @classmethod
    def create(cls, parent: Path, name: str) -> "Workspace":
        root = Path(parent) / cls.default_folder_name(name)
        if root.exists() and any(root.iterdir()):
            raise WorkspaceError(f"Folder already exists and is not empty: {root}")
        if find_workspace_root(Path(parent)) is not None:
            raise WorkspaceError("A workspace cannot be created inside another workspace")
        root.mkdir(parents=True, exist_ok=True)
        layout.configs_dir(root).mkdir(exist_ok=True)
        manifest = WorkspaceManifest(name=name.strip() or root.name)
        write_manifest(layout.workspace_manifest_path(root), manifest)
        return cls(root, manifest)

    @classmethod
    def open(cls, path: Path) -> "Workspace":
        root = find_workspace_root(path)
        if root is None:
            raise WorkspaceError(f"Not an Ephyr workspace: {path}")
        manifest = read_manifest(layout.workspace_manifest_path(root), WorkspaceManifest)
        return cls(root, manifest)

    def reload(self) -> None:
        self.manifest = read_manifest(layout.workspace_manifest_path(self.root), WorkspaceManifest)
        self._configs.clear()
        self._records.clear()
        for config_id in self.manifest.configs:
            path = layout.config_manifest_path(self.root, config_id)
            if not path.is_file():
                continue
            config = read_manifest(path, ConfigManifest)
            self._configs[config_id] = config
            for record_id in config.records:
                record_path = layout.record_manifest_path(self.record_dir(config_id, record_id))
                if record_path.is_file():
                    self._records[(config_id, record_id)] = read_manifest(record_path, RecordManifest)

    # ----- queries -----

    @property
    def name(self) -> str:
        return self.manifest.name

    @property
    def manifest_path(self) -> Path:
        return layout.workspace_manifest_path(self.root)

    def configs(self) -> List[ConfigManifest]:
        return [self._configs[config_id] for config_id in self.manifest.configs if config_id in self._configs]

    def config(self, config_id: str) -> Optional[ConfigManifest]:
        return self._configs.get(config_id)

    def records(self, config_id: str) -> List[RecordManifest]:
        config = self.config(config_id)
        if config is None:
            return []
        return [self._records[(config_id, rid)] for rid in config.records if (config_id, rid) in self._records]

    def record(self, config_id: str, record_id: str) -> Optional[RecordManifest]:
        return self._records.get((config_id, record_id))

    def record_by_uid(self, uid: str) -> Optional[RecordLocation]:
        for (config_id, record_id), record in self._records.items():
            if record.uid == uid:
                return RecordLocation(config_id, record_id)
        return None

    def config_dir(self, config_id: str) -> Path:
        return layout.config_dir(self.root, config_id)

    def record_dir(self, config_id: str, record_id: str) -> Path:
        return layout.record_dir(self.root, config_id, record_id)

    def find_duplicate(self, fingerprint: Fingerprint) -> Optional[RecordLocation]:
        for (config_id, record_id), record in self._records.items():
            for item in record.inputs:
                if (item.fingerprint.algorithm == fingerprint.algorithm
                        and item.fingerprint.digest == fingerprint.digest):
                    return RecordLocation(config_id, record_id)
        return None

    def ensure_not_duplicate(self, fingerprint: Fingerprint) -> None:
        duplicate = self.find_duplicate(fingerprint)
        if duplicate is None:
            return
        config = self.config(duplicate.config_id)
        record = self.record(duplicate.config_id, duplicate.record_id)
        raise DuplicateRecordError(
            duplicate.config_id,
            duplicate.record_id,
            config.name if config else duplicate.config_id,
            record.name if record else duplicate.record_id,
        )

    def sessions_count(self, config_id: str, record_id: Optional[str] = None) -> int:
        record_ids = [record_id] if record_id else [record.record_id for record in self.records(config_id)]
        total = 0
        for rid in record_ids:
            folder = layout.sessions_dir(self.record_dir(config_id, rid))
            if folder.is_dir():
                total += sum(1 for item in folder.iterdir() if item.is_dir())
        return total

    # ----- saving -----

    def _save_workspace(self) -> None:
        write_manifest(self.manifest_path, self.manifest)

    def save_config(self, config: ConfigManifest) -> None:
        write_manifest(layout.config_manifest_path(self.root, config.config_id), config)
        self._configs[config.config_id] = config

    def save_record(self, config_id: str, record: RecordManifest) -> None:
        folder = self.record_dir(config_id, record.record_id)
        write_manifest(layout.record_manifest_path(folder), record)
        self._records[(config_id, record.record_id)] = record

    # ----- rename -----

    def rename_workspace(self, name: str) -> None:
        self.manifest.name = name.strip() or self.manifest.name
        self._save_workspace()

    def rename_config(self, config_id: str, name: str) -> None:
        config = self._require_config(config_id)
        config.name = name.strip() or config.name
        self.save_config(config)

    def rename_record(self, config_id: str, record_id: str, name: str) -> None:
        record = self._require_record(config_id, record_id)
        record.name = name.strip() or record.name
        self.save_record(config_id, record)

    def rename_source(self, config_id: str, source_id: str, name: str) -> None:
        config = self._require_config(config_id)
        spec = config.source(source_id)
        if spec is None:
            raise WorkspaceError(f"Unknown source '{source_id}'")
        spec.name = name.strip() or spec.name
        self.save_config(config)

    # ----- removal -----

    def remove_config(self, config_id: str) -> None:
        self._require_config(config_id)
        self.manifest.configs = [cid for cid in self.manifest.configs if cid != config_id]
        self._save_workspace()
        remove_tree(self.config_dir(config_id))
        self._configs.pop(config_id, None)
        for key in [key for key in self._records if key[0] == config_id]:
            self._records.pop(key)

    def remove_record(self, config_id: str, record_id: str) -> None:
        config = self._require_config(config_id)
        config.records = [rid for rid in config.records if rid != record_id]
        self.save_config(config)
        remove_tree(self.record_dir(config_id, record_id))
        self._records.pop((config_id, record_id), None)

    def remove_source(self, config_id: str, record_id: str, source_id: str) -> None:
        config = self._require_config(config_id)
        if source_id == config.main_source_id:
            raise WorkspaceError("The main source of a Config cannot be removed")
        record = self._require_record(config_id, record_id)
        record.sources = [source for source in record.sources if source.source_id != source_id]
        used_inputs = {source.input_id for source in record.sources}
        record.inputs = [item for item in record.inputs if item.input_id in used_inputs]
        self.save_record(config_id, record)
        remove_tree(layout.source_dir(self.record_dir(config_id, record_id), source_id))
        still_used = any(other.source(source_id) is not None for other in self.records(config_id))
        if not still_used:
            config.sources = [spec for spec in config.sources if spec.source_id != source_id]
            self.save_config(config)

    def _require_config(self, config_id: str) -> ConfigManifest:
        config = self.config(config_id)
        if config is None:
            raise WorkspaceError(f"Unknown Config '{config_id}'")
        return config

    def _require_record(self, config_id: str, record_id: str) -> RecordManifest:
        record = self.record(config_id, record_id)
        if record is None:
            raise WorkspaceError(f"Unknown Record '{record_id}'")
        return record

    # ----- conversion -----

    @staticmethod
    def fingerprint(plan) -> Fingerprint:
        return fingerprint_of_ref(plan.ref)

    def add_config(
        self,
        plan,
        config_name: str,
        record_name: str,
        main_source_id: str,
        fingerprint: Optional[Fingerprint] = None,
    ) -> Generator[float, None, RecordLocation]:
        """Create a Config from the plan sources and convert the plan into its first Record."""
        fingerprint = fingerprint or self.fingerprint(plan)
        self.ensure_not_duplicate(fingerprint)
        if plan.source(main_source_id) is None:
            raise WorkspaceError(f"Unknown main source '{main_source_id}'")
        config_id = unique_id(config_name, self._existing_ids(layout.configs_dir(self.root), self.manifest.configs),
                              "config")
        config = ConfigManifest(
            config_id=config_id,
            name=config_name.strip() or config_id,
            main_source_id=main_source_id,
            sources=[build_spec(source_plan) for source_plan in plan.sources],
        )
        self.config_dir(config_id).mkdir(parents=True, exist_ok=False)
        layout.records_dir(self.root, config_id).mkdir(exist_ok=True)
        self.save_config(config)
        self.manifest.configs.append(config_id)
        self._save_workspace()
        try:
            record_id = yield from self._convert_record(config, plan, record_name,
                                                        {sp.source_id: sp.source_id for sp in plan.sources},
                                                        fingerprint)
        except BaseException:
            self.remove_config(config_id)
            raise
        return RecordLocation(config_id, record_id)

    def add_record(
        self,
        config_id: str,
        plan,
        record_name: str,
        fingerprint: Optional[Fingerprint] = None,
    ) -> Generator[float, None, RecordLocation]:
        """Convert the plan into a new Record of an existing Config; the caller validated the main source."""
        config = self._require_config(config_id)
        fingerprint = fingerprint or self.fingerprint(plan)
        self.ensure_not_duplicate(fingerprint)
        match = match_config(config, plan)
        if not match.is_compatible:
            raise WorkspaceError("The recording does not match the main source of this Config")
        mapping = self._map_sources(config, plan, match.source_id)
        record_id = yield from self._convert_record(config, plan, record_name, mapping, fingerprint)
        return RecordLocation(config_id, record_id)

    def add_source(
        self,
        config_id: str,
        record_id: str,
        plan,
        source_ids: Sequence[str],
        fingerprint: Optional[Fingerprint] = None,
    ) -> Generator[float, None, List[str]]:
        """Import sources of another recording into an existing Record as additional sources."""
        config = self._require_config(config_id)
        record = self._require_record(config_id, record_id)
        fingerprint = fingerprint or self.fingerprint(plan)
        self.ensure_not_duplicate(fingerprint)
        selected = [plan.source(source_id) for source_id in source_ids]
        selected = [source_plan for source_plan in selected if source_plan is not None]
        if not selected:
            raise WorkspaceError("No sources selected")

        taken = [spec.source_id for spec in config.sources]
        new_ids: List[str] = []
        for source_plan in selected:
            existing = next(
                (spec for spec in config.sources
                 if spec.source_id not in [s.source_id for s in record.sources]
                 and not compare_signatures(spec.signature, build_spec(source_plan).signature)),
                None,
            )
            if existing is not None:
                new_ids.append(existing.source_id)
                continue
            new_id = unique_id(source_plan.name or source_plan.source_id, taken + new_ids, "source")
            new_ids.append(new_id)

        input_id = max((item.input_id for item in record.inputs), default=-1) + 1
        folder = self.record_dir(config_id, record_id)
        written_dirs: List[Path] = []
        try:
            total = sum(sp.total_samples * sp.number_of_channels for sp in selected) or 1
            done = 0
            for source_plan, new_id in zip(selected, new_ids):
                target = layout.source_dir(folder, new_id)
                written_dirs.append(target)
                weight = source_plan.total_samples * source_plan.number_of_channels
                for fraction in self._write_source(folder, new_id, source_plan):
                    yield (done + fraction * weight) / total
                done += weight
        except BaseException:
            for target in written_dirs:
                remove_tree(target)
            raise

        record.inputs.append(self._input_info(plan, input_id, fingerprint))
        for source_plan, new_id in zip(selected, new_ids):
            record.sources.append(self._record_source(source_plan, new_id, input_id))
            if config.source(new_id) is None:
                spec = build_spec(source_plan, source_id=new_id)
                spec.derived_from = None
                config.sources.append(spec)
        self.save_record(config_id, record)
        self.save_config(config)
        yield 1.0
        return new_ids

    def _map_sources(self, config: ConfigManifest, plan, main_plan_source_id: str) -> Dict[str, str]:
        """Plan source id -> Config source id; unknown additional sources get new Config sources."""
        mapping = {main_plan_source_id: config.main_source_id}
        used = {config.main_source_id}
        for source_plan in plan.sources:
            if source_plan.source_id == main_plan_source_id:
                continue
            signature = build_spec(source_plan).signature
            target = next(
                (spec.source_id for spec in config.sources
                 if spec.source_id not in used and not compare_signatures(spec.signature, signature)),
                None,
            )
            if target is None:
                target = unique_id(source_plan.source_id, [spec.source_id for spec in config.sources] + list(used),
                                   "source")
            mapping[source_plan.source_id] = target
            used.add(target)
        return mapping

    @staticmethod
    def _existing_ids(folder: Path, listed: Sequence[str]) -> List[str]:
        on_disk = [item.name.removesuffix(settings.PARTIAL_RECORD_SUFFIX) for item in folder.iterdir()] \
            if folder.is_dir() else []
        return list(listed) + on_disk

    @staticmethod
    def _input_info(plan, input_id: int, fingerprint: Fingerprint) -> InputInfo:
        return InputInfo(
            input_id=input_id,
            format=plan.ref.format,
            kind=plan.ref.kind,
            root_name=plan.ref.name,
            fingerprint=fingerprint,
            reader_options=dict(plan.reader_options),
        )

    @staticmethod
    def _record_source(source_plan, source_id: str, input_id: int) -> RecordSource:
        return RecordSource(
            source_id=source_id,
            input_id=input_id,
            t_start_ms=float(source_plan.t_start_ms),
            alignment=None,
            channels=[
                ChannelCalibration(
                    analog_min=float(channel.analog_min),
                    analog_max=float(channel.analog_max),
                    digital_min=int(channel.digital_min),
                    digital_max=int(channel.digital_max),
                    impedance_ohm=channel.impedance_ohm,
                )
                for channel in source_plan.channels
            ],
            segments=list(source_plan.segments),
        )

    @staticmethod
    def _write_source(record_folder: Path, source_id: str, source_plan) -> Generator[float, None, None]:
        target = layout.source_dir(record_folder, source_id)
        paths = [layout.channel_samples_path(record_folder, source_id, idx)
                 for idx in range(source_plan.number_of_channels)]
        writer = source_plan.writer_factory()
        yield from writer.to_dest_folder(target, paths, source_plan.total_samples)
        for path in paths:
            os.chmod(path, 0o444)

    def _convert_record(
        self,
        config: ConfigManifest,
        plan,
        record_name: str,
        mapping: Dict[str, str],
        fingerprint: Fingerprint,
    ) -> Generator[float, None, str]:
        records_folder = layout.records_dir(self.root, config.config_id)
        records_folder.mkdir(parents=True, exist_ok=True)
        record_name = record_name.strip() or plan.recording_name or plan.ref.name
        record_id = unique_id(record_name, self._existing_ids(records_folder, config.records), "record")
        partial = records_folder / f"{record_id}{settings.PARTIAL_RECORD_SUFFIX}"
        final = records_folder / record_id
        remove_tree(partial)
        partial.mkdir()
        try:
            total = sum(sp.total_samples * sp.number_of_channels for sp in plan.sources) or 1
            done = 0
            for source_plan in plan.sources:
                weight = source_plan.total_samples * source_plan.number_of_channels
                for fraction in self._write_source(partial, mapping[source_plan.source_id], source_plan):
                    yield min((done + fraction * weight) / total, 0.99)
                done += weight

            write_events(layout.source_events_path(partial), [
                EventRow(id=idx, t_ms=event.t_ms, label=event.label,
                         source_id=mapping.get(event.source_id, event.source_id) if event.source_id else None,
                         channel=event.channel, value=event.value, extra=dict(event.extra))
                for idx, event in enumerate(sorted(plan.events, key=lambda item: item.t_ms))
            ])
            write_periods(layout.source_periods_path(partial), [
                PeriodRow(id=idx, start_t_ms=period.start_t_ms, end_t_ms=period.end_t_ms, label=period.label,
                          source_id=mapping.get(period.source_id, period.source_id) if period.source_id else None,
                          channel=period.channel, value=period.value, extra=dict(period.extra))
                for idx, period in enumerate(sorted(plan.periods, key=lambda item: item.start_t_ms))
            ])
            layout.sessions_dir(partial).mkdir(exist_ok=True)
            layout.add_ons_data_dir(partial).mkdir(parents=True, exist_ok=True)

            record = RecordManifest(
                record_id=record_id,
                name=record_name,
                start_datetime=plan.start_datetime,
                inputs=[self._input_info(plan, 0, fingerprint)],
                sources=[self._record_source(sp, mapping[sp.source_id], 0) for sp in plan.sources],
            )
            write_manifest(layout.record_manifest_path(partial), record)
            os.replace(partial, final)
        except BaseException:
            remove_tree(partial)
            raise

        for source_plan in plan.sources:
            target_id = mapping[source_plan.source_id]
            if config.source(target_id) is None:
                spec = build_spec(source_plan, source_id=target_id)
                if spec.derived_from is not None:
                    spec.derived_from.source_id = mapping.get(spec.derived_from.source_id,
                                                              spec.derived_from.source_id)
                config.sources.append(spec)
        config.records.append(record_id)
        self.save_config(config)
        self._records[(config.config_id, record_id)] = record
        yield 1.0
        return record_id
