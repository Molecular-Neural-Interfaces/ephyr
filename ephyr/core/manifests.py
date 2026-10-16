# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

"""On-disk manifests of the Workspace -> Config -> Record -> Source -> Segment hierarchy."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Type, TypeVar

from pydantic import BaseModel, Field, model_validator

MANIFEST_FORMAT_VERSION = 1
SAMPLES_DTYPE = "<i2"

_ModelT = TypeVar("_ModelT", bound=BaseModel)


def new_uid() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


class SegmentKindEnum(str, Enum):
    SWEEP = "sweep"
    RECORDING = "recording"
    FILE = "file"
    SEGMENT = "segment"
    CONTINUOUS = "continuous"

    @property
    def label(self) -> str:
        return {
            SegmentKindEnum.SWEEP: "Sweep",
            SegmentKindEnum.RECORDING: "Recording",
            SegmentKindEnum.FILE: "File",
            SegmentKindEnum.SEGMENT: "Segment",
            SegmentKindEnum.CONTINUOUS: "Segment",
        }[self]


class ChannelSignature(BaseModel):
    name: str
    units: str = ""


class SourceSignature(BaseModel):
    """Everything that must match between Records of one Config for GUI settings to transfer."""
    sample_rate: float
    dtype: str = SAMPLES_DTYPE
    channels: List[ChannelSignature]

    @property
    def number_of_channels(self) -> int:
        return len(self.channels)


class SourceDescriptive(BaseModel):
    """Informational source properties: compared with a warning only."""
    source_format: str = ""
    segment_kind: SegmentKindEnum = SegmentKindEnum.CONTINUOUS
    probes: List[str] = Field(default_factory=list)
    prefiltering: List[str] = Field(default_factory=list)


class DerivedFrom(BaseModel):
    source_id: str
    relation: str = "resampled"


class SourceSpec(BaseModel):
    source_id: str
    name: str
    derived_from: Optional[DerivedFrom] = None
    signature: SourceSignature
    descriptive: SourceDescriptive = Field(default_factory=SourceDescriptive)


class WorkspaceManifest(BaseModel):
    format: Literal["ephyr-workspace"] = "ephyr-workspace"
    format_version: int = MANIFEST_FORMAT_VERSION
    uid: str = Field(default_factory=new_uid)
    name: str
    created_at: str = Field(default_factory=now_iso)
    configs: List[str] = Field(default_factory=list)


class ConfigManifest(BaseModel):
    format: Literal["ephyr-config"] = "ephyr-config"
    format_version: int = MANIFEST_FORMAT_VERSION
    uid: str = Field(default_factory=new_uid)
    config_id: str
    name: str
    created_at: str = Field(default_factory=now_iso)
    main_source_id: str
    sources: List[SourceSpec] = Field(default_factory=list)
    records: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _main_source_exists(self) -> "ConfigManifest":
        if self.sources and self.source(self.main_source_id) is None:
            raise ValueError(f"Config main source '{self.main_source_id}' is not described in sources")
        return self

    def source(self, source_id: str) -> Optional[SourceSpec]:
        return next((spec for spec in self.sources if spec.source_id == source_id), None)

    @property
    def main_source(self) -> SourceSpec:
        spec = self.source(self.main_source_id)
        if spec is None:
            raise ValueError(f"Config '{self.config_id}' has no main source")
        return spec


class FileFingerprint(BaseModel):
    relpath: str
    size: int
    sha256_sparse: str


class Fingerprint(BaseModel):
    algorithm: str
    digest: str
    files: List[FileFingerprint] = Field(default_factory=list)


class InputInfo(BaseModel):
    input_id: int
    format: str
    kind: Literal["file", "folder"]
    root_name: str
    fingerprint: Fingerprint
    reader_options: Dict[str, Any] = Field(default_factory=dict)


class ChannelCalibration(BaseModel):
    analog_min: float
    analog_max: float
    digital_min: int
    digital_max: int
    impedance_ohm: Optional[float] = None


class SegmentInfo(BaseModel):
    start_sample_idx: int
    number_of_samples: int
    t_start_ms: float = 0.0
    label: Optional[str] = None


class Alignment(BaseModel):
    offset_ms: float = 0.0
    drift_ppm: float = 0.0
    method: Literal["ttl", "manual"] = "manual"


class RecordSource(BaseModel):
    source_id: str
    input_id: int = 0
    t_start_ms: float = 0.0
    alignment: Optional[Alignment] = None
    channels: List[ChannelCalibration]
    segments: List[SegmentInfo]

    @property
    def total_samples(self) -> int:
        return sum(int(segment.number_of_samples) for segment in self.segments)


class RecordManifest(BaseModel):
    format: Literal["ephyr-record"] = "ephyr-record"
    format_version: int = MANIFEST_FORMAT_VERSION
    uid: str = Field(default_factory=new_uid)
    record_id: str
    name: str
    created_at: str = Field(default_factory=now_iso)
    start_datetime: str = ""
    inputs: List[InputInfo] = Field(default_factory=list)
    sources: List[RecordSource] = Field(default_factory=list)

    def source(self, source_id: str) -> Optional[RecordSource]:
        return next((source for source in self.sources if source.source_id == source_id), None)

    def input(self, input_id: int) -> Optional[InputInfo]:
        return next((item for item in self.inputs if item.input_id == input_id), None)


def read_manifest(path: Path, model: Type[_ModelT]) -> _ModelT:
    with open(path, "r", encoding="utf-8") as file:
        return model.model_validate(json.load(file))


def write_manifest(path: Path, manifest: BaseModel) -> None:
    """Write via a temporary file so a crash never leaves a truncated manifest behind."""
    tmp_path = path.with_name(path.name + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as file:
        file.write(manifest.model_dump_json(indent=2))
    os.replace(tmp_path, path)
