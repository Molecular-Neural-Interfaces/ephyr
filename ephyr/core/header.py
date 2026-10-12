# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

from enum import Enum
from typing import Iterable, List, Optional
from pydantic import BaseModel, Field, model_validator


class PhysicalQuantityEnum(str, Enum):
    VOLTAGE = "Voltage"
    CURRENT = "Current"
    UNKNOWN = "Unknown"


_PREFIX_EXPONENTS = {
    "k": 3,
    "": 0,
    "m": -3,
    "u": -6,
    "n": -9,
    "p": -12,
    "f": -15,
}


class SignalUnitEnum(str, Enum):
    KILOVOLT = "kV"
    VOLT = "V"
    MILLIVOLT = "mV"
    MICROVOLT = "uV"
    NANOVOLT = "nV"
    PICOVOLT = "pV"
    AMPERE = "A"
    MILLIAMPERE = "mA"
    MICROAMPERE = "uA"
    NANOAMPERE = "nA"
    PICOAMPERE = "pA"
    FEMTOAMPERE = "fA"

    @classmethod
    def values(cls) -> List[str]:
        return [member.value for member in cls]

    @classmethod
    def of_quantity(cls, quantity: PhysicalQuantityEnum) -> List["SignalUnitEnum"]:
        return [member for member in cls if member.quantity is quantity]

    @property
    def quantity(self) -> PhysicalQuantityEnum:
        if self.value.endswith("V"):
            return PhysicalQuantityEnum.VOLTAGE
        return PhysicalQuantityEnum.CURRENT

    @property
    def display_symbol(self) -> str:
        return self.value.replace("u", "µ", 1) if self.value.startswith("u") else self.value

    @property
    def si_exponent(self) -> int:
        return _PREFIX_EXPONENTS[self.value[:-1]]

    @property
    def si_factor(self) -> float:
        return 10.0 ** self.si_exponent

    def factor_to(self, other: "SignalUnitEnum") -> Optional[float]:
        """Multiplier converting a value in this unit into `other`, None if quantities differ."""
        if self.quantity is not other.quantity:
            return None
        return 10.0 ** (self.si_exponent - other.si_exponent)


_BASE_UNIT_ALIASES = {
    "V": ("v", "volt", "volts"),
    "A": ("a", "amp", "amps", "ampere", "amperes"),
}
_PREFIX_ALIASES = {
    "k": ("k", "kilo", "kilo-"),
    "": ("",),
    "m": ("m", "milli", "milli-"),
    "u": ("u", "µ", "μ", "micro", "micro-"),
    "n": ("n", "nano", "nano-"),
    "p": ("p", "pico", "pico-"),
    "f": ("f", "femto", "femto-"),
}


def _build_unit_aliases() -> dict:
    aliases = {}
    for base, base_names in _BASE_UNIT_ALIASES.items():
        for prefix, prefix_names in _PREFIX_ALIASES.items():
            try:
                unit = SignalUnitEnum(f"{prefix}{base}")
            except ValueError:
                continue
            for prefix_name in prefix_names:
                for base_name in base_names:
                    # Single-letter prefixes only combine with single-letter symbols ("mv", not "mvolt").
                    if len(prefix_name) == 1 and len(base_name) > 1:
                        continue
                    aliases[f"{prefix_name}{base_name}"] = unit
    return aliases


_UNIT_ALIASES = _build_unit_aliases()


def parse_unit(raw: Optional[str]) -> Optional[SignalUnitEnum]:
    """Known voltage/current unit for a raw label, or None for unknown units."""
    text = (raw or "").strip()
    if not text:
        return None
    if text in SignalUnitEnum.values():
        return SignalUnitEnum(text)
    return _UNIT_ALIASES.get(text.lower())


def canonical_unit_label(raw: Optional[str]) -> str:
    """ASCII label for known units ("uV", "pA"), otherwise the stripped raw label."""
    unit = parse_unit(raw)
    if unit is not None:
        return unit.value
    return (raw or "").strip()


def unit_display_label(raw: Optional[str]) -> str:
    unit = parse_unit(raw)
    if unit is not None:
        return unit.display_symbol
    return (raw or "").strip()


def unit_quantity(raw: Optional[str]) -> PhysicalQuantityEnum:
    unit = parse_unit(raw)
    return unit.quantity if unit is not None else PhysicalQuantityEnum.UNKNOWN


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

    def rescale_units(self, channel_indexes: Iterable[int], target: SignalUnitEnum) -> None:
        """Re-express channels in `target` by rescaling the analog range; stored samples are untouched.

        Channels whose unit is unknown or of a different quantity are left as is.
        """
        for idx in channel_indexes:
            if idx >= len(self.units or []):
                continue
            unit = parse_unit(self.units[idx])
            factor = unit.factor_to(target) if unit is not None else None
            if factor is None:
                continue
            if idx < len(self.analog_min or []):
                self.analog_min[idx] = float(self.analog_min[idx]) * factor
            if idx < len(self.analog_max or []):
                self.analog_max[idx] = float(self.analog_max[idx]) * factor
            self.units[idx] = target.value


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

    def channel_unit_label(self, channel_idx: int) -> str:
        units = self.channel_info.units or []
        return units[channel_idx] if 0 <= channel_idx < len(units) else ""

    def channel_unit(self, channel_idx: int) -> Optional[SignalUnitEnum]:
        return parse_unit(self.channel_unit_label(channel_idx))

    def channel_unit_display(self, channel_idx: int) -> str:
        return unit_display_label(self.channel_unit_label(channel_idx))

    def channel_quantity(self, channel_idx: int) -> PhysicalQuantityEnum:
        return unit_quantity(self.channel_unit_label(channel_idx))

    def common_unit_display(self, channel_indexes: Optional[Iterable[int]] = None) -> str:
        """Display unit shared by all given channels (all channels by default), "" if they differ."""
        if channel_indexes is None:
            channel_indexes = range(self.number_of_channels)
        units = {self.channel_unit_display(idx) for idx in channel_indexes}
        return units.pop() if len(units) == 1 else ""
