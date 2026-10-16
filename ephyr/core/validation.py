# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

"""Comparison of a new recording against the source signatures of Configs."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Sequence, Tuple

from ephyr.core.manifests import (
    SAMPLES_DTYPE,
    ChannelSignature,
    ConfigManifest,
    SourceDescriptive,
    SourceSignature,
    SourceSpec,
)
from ephyr.core.units import canonical_unit_label

SAMPLE_RATE_RELATIVE_TOLERANCE = 1e-6


class SeverityEnum(str, Enum):
    BLOCKING = "blocking"
    WARNING = "warning"


@dataclass(frozen=True)
class Mismatch:
    field: str
    channel: Optional[int]
    expected: str
    actual: str
    severity: SeverityEnum

    @property
    def is_blocking(self) -> bool:
        return self.severity is SeverityEnum.BLOCKING


def build_signature(source_plan) -> SourceSignature:
    return SourceSignature(
        sample_rate=float(source_plan.sample_rate),
        dtype=SAMPLES_DTYPE,
        channels=[
            ChannelSignature(name=channel.name.strip(), units=canonical_unit_label(channel.units))
            for channel in source_plan.channels
        ],
    )


def build_descriptive(source_plan) -> SourceDescriptive:
    return SourceDescriptive(
        source_format=source_plan.source_format,
        segment_kind=source_plan.segment_kind,
        probes=[channel.probe for channel in source_plan.channels],
        prefiltering=[channel.prefiltering for channel in source_plan.channels],
    )


def build_spec(source_plan, source_id: Optional[str] = None, name: Optional[str] = None) -> SourceSpec:
    return SourceSpec(
        source_id=source_id or source_plan.source_id,
        name=name or source_plan.name,
        derived_from=source_plan.derived_from,
        signature=build_signature(source_plan),
        descriptive=build_descriptive(source_plan),
    )


def _rates_equal(expected: float, actual: float) -> bool:
    return abs(expected - actual) <= SAMPLE_RATE_RELATIVE_TOLERANCE * abs(expected)


def compare_signatures(expected: SourceSignature, actual: SourceSignature) -> List[Mismatch]:
    mismatches: List[Mismatch] = []
    blocking = SeverityEnum.BLOCKING
    if not _rates_equal(expected.sample_rate, actual.sample_rate):
        mismatches.append(Mismatch("sample_rate", None, f"{expected.sample_rate:g} Hz",
                                   f"{actual.sample_rate:g} Hz", blocking))
    if expected.dtype != actual.dtype:
        mismatches.append(Mismatch("dtype", None, expected.dtype, actual.dtype, blocking))
    if len(expected.channels) != len(actual.channels):
        mismatches.append(Mismatch("number_of_channels", None, str(len(expected.channels)),
                                   str(len(actual.channels)), blocking))
    for idx, (left, right) in enumerate(zip(expected.channels, actual.channels)):
        if left.name.strip() != right.name.strip():
            mismatches.append(Mismatch("channel_name", idx, left.name, right.name, blocking))
        if canonical_unit_label(left.units) != canonical_unit_label(right.units):
            mismatches.append(Mismatch("units", idx, left.units, right.units, blocking))
    return mismatches


def compare_descriptive(expected: SourceDescriptive, actual: SourceDescriptive) -> List[Mismatch]:
    mismatches: List[Mismatch] = []
    warning = SeverityEnum.WARNING
    if expected.source_format != actual.source_format:
        mismatches.append(Mismatch("source_format", None, expected.source_format, actual.source_format, warning))
    if expected.segment_kind != actual.segment_kind:
        mismatches.append(Mismatch("segment_kind", None, expected.segment_kind.value,
                                   actual.segment_kind.value, warning))
    for field_name in ("probes", "prefiltering"):
        left_values = getattr(expected, field_name)
        right_values = getattr(actual, field_name)
        for idx, (left, right) in enumerate(zip(left_values, right_values)):
            if (left or "").strip() != (right or "").strip():
                mismatches.append(Mismatch(field_name.rstrip("s"), idx, left, right, warning))
    return mismatches


def compare(expected: SourceSpec, actual: SourceSpec) -> List[Mismatch]:
    return compare_signatures(expected.signature, actual.signature) + compare_descriptive(
        expected.descriptive, actual.descriptive
    )


def has_blocking(mismatches: Sequence[Mismatch]) -> bool:
    return any(mismatch.is_blocking for mismatch in mismatches)


@dataclass
class ConfigMatch:
    """Best candidate main source of a new recording for one Config."""
    config: ConfigManifest
    source_id: Optional[str]
    mismatches: List[Mismatch]

    @property
    def is_compatible(self) -> bool:
        return self.source_id is not None and not has_blocking(self.mismatches)


def match_config(config: ConfigManifest, plan) -> ConfigMatch:
    """The plan source whose signature matches the Config main source, or the most similar one."""
    main = config.main_source
    best: Optional[Tuple[int, str, List[Mismatch]]] = None
    for source_plan in plan.sources:
        mismatches = compare(main, build_spec(source_plan))
        score = sum(1 for mismatch in mismatches if mismatch.is_blocking)
        if best is None or score < best[0]:
            best = (score, source_plan.source_id, mismatches)
    if best is None:
        return ConfigMatch(config, None, [Mismatch("sources", None, main.name, "no sources",
                                                   SeverityEnum.BLOCKING)])
    return ConfigMatch(config, best[1], best[2])


def matching_configs(configs: Sequence[ConfigManifest], plan) -> List[ConfigMatch]:
    """Configs whose main source the recording satisfies without blocking mismatches."""
    return [match for match in (match_config(config, plan) for config in configs) if match.is_compatible]


def format_mismatch(mismatch: Mismatch) -> str:
    where = f" (channel {mismatch.channel + 1})" if mismatch.channel is not None else ""
    return f"{mismatch.field}{where}: {mismatch.expected!r} in Config, {mismatch.actual!r} in source"
