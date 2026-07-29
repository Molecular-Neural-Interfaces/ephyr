# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field, model_validator


class VoltageUnitEnum(str, Enum):
    KILOVOLT = "kV"
    VOLT = "V"
    MILLIVOLT = "mV"
    MICROVOLT = "uV"
    NANOVOLT = "nV"
    PICOVOLT = "pV"

    @classmethod
    def values(cls) -> List[str]:
        return [member.value for member in cls]

    @classmethod
    def normalize(cls, value: Optional[str]) -> "VoltageUnitEnum":
        raw = (value or "").strip()
        lowered = raw.lower()
        aliases = {
            "kv": cls.KILOVOLT,
            "v": cls.VOLT,
            "mv": cls.MILLIVOLT,
            "uv": cls.MICROVOLT,
            "µv": cls.MICROVOLT,
            "μv": cls.MICROVOLT,
            "nv": cls.NANOVOLT,
            "pv": cls.PICOVOLT,
        }
        return aliases.get(lowered, cls.MICROVOLT)

    def to_uv_multiplier(self) -> float:
        if self is VoltageUnitEnum.KILOVOLT:
            return 1_000_000_000.0
        if self is VoltageUnitEnum.VOLT:
            return 1_000_000.0
        if self is VoltageUnitEnum.MILLIVOLT:
            return 1_000.0
        if self is VoltageUnitEnum.MICROVOLT:
            return 1.0
        if self is VoltageUnitEnum.NANOVOLT:
            return 0.001
        if self is VoltageUnitEnum.PICOVOLT:
            return 0.000001
        return 1.0


class ChannelInfo(BaseModel):
    name: List[str]
    probe: Optional[List[str]] = Field(default_factory=list)
    units: Optional[List[str]] = Field(default_factory=list)
    analog_min: Optional[List[float]] = Field(default_factory=list)
    analog_max: Optional[List[float]] = Field(default_factory=list)
    digital_min: Optional[List[int]] = Field(default_factory=list)
    digital_max: Optional[List[int]] = Field(default_factory=list)
    prefiltering: Optional[List[str]] = Field(default_factory=list)
    number_of_points_per_channel: Optional[List[int]] = Field(default_factory=list)
    impedance_ohm: Optional[List[Optional[float]]] = Field(default_factory=list)


class Header(BaseModel):
    type_before_conversion: str
    name_before_conversion: str
    creation_date_before_conversion: str
    creation_time_before_conversion: str
    sample_interval_microseconds: float
    sample_rate: float
    number_of_channels: int
    number_of_sweeps: int = 1
    number_of_points_per_sweep: List[int]
    channel_info: ChannelInfo = Field(default_factory=ChannelInfo)

    @model_validator(mode="after")
    def validate_sweep_points(self) -> "Header":
        if self.number_of_sweeps < 1:
            raise ValueError("number_of_sweeps must be positive")
        if len(self.number_of_points_per_sweep) != self.number_of_sweeps:
            raise ValueError("number_of_points_per_sweep length must match number_of_sweeps")
        if any(points < 0 for points in self.number_of_points_per_sweep):
            raise ValueError("number_of_points_per_sweep cannot contain negative values")
        return self
