# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

from enum import Enum
from typing import List, Optional


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
