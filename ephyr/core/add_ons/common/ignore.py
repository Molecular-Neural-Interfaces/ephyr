# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

"""Shared helpers for event/period sample masks.

Selected events and periods can either be ignored (excluded from analysis) or
applied (analysis restricted to those windows). An empty selection means no
filter for that source.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from pydantic import BaseModel

from ephyr.logger import ephyr_logger

SELECTION_MODE_IGNORE = "ignore"
SELECTION_MODE_APPLY = "apply"
SELECTION_MODES = (SELECTION_MODE_IGNORE, SELECTION_MODE_APPLY)


class IgnoreEventsRule(BaseModel):
    """Window around named events (kept name for backward compatibility)."""

    event_names: List[str]
    before_ms: float
    after_ms: float


class IgnorePeriodsRule(BaseModel):
    period_names: List[str]


def _mark_event_windows(
    mask: np.ndarray,
    sample_rate: float,
    event_times_by_name: Dict[str, np.ndarray],
    event_rules: Sequence[IgnoreEventsRule],
    value: bool,
) -> None:
    for rule in event_rules or []:
        for event_name in rule.event_names:
            for event_t in (event_times_by_name or {}).get(event_name, []):
                start_idx = max(0, int((event_t - rule.before_ms / 1000.0) * sample_rate))
                end_idx = min(mask.size, int((event_t + rule.after_ms / 1000.0) * sample_rate))
                if end_idx > start_idx:
                    mask[start_idx:end_idx] = value


def _mark_period_windows(
    mask: np.ndarray,
    sample_rate: float,
    period_intervals_s: Sequence[Tuple[float, float]],
    value: bool,
) -> None:
    for start_s, end_s in period_intervals_s or []:
        start_idx = max(0, int(float(start_s) * sample_rate))
        end_idx = min(mask.size, int(float(end_s) * sample_rate))
        if end_idx > start_idx:
            mask[start_idx:end_idx] = value


def build_valid_mask(
    n_samples: int,
    sample_rate: float,
    *,
    event_times_by_name: Optional[Dict[str, np.ndarray]] = None,
    event_rules: Optional[Sequence[IgnoreEventsRule]] = None,
    events_mode: str = SELECTION_MODE_IGNORE,
    period_intervals_s: Optional[Sequence[Tuple[float, float]]] = None,
    periods_mode: str = SELECTION_MODE_IGNORE,
) -> np.ndarray:
    """Return a boolean mask (True == keep) of length ``n_samples``.

    ``events_mode`` / ``periods_mode`` are ``"ignore"`` (exclude windows) or
    ``"apply"`` (keep only those windows). When both sources use ``apply``,
    their windows are unioned. Ignore filters are applied after apply filters.
    Empty selections leave that source unconstrained.
    """
    mask = np.ones(int(max(0, n_samples)), dtype=bool)
    if mask.size == 0 or sample_rate <= 0:
        return mask

    events_mode = str(events_mode or SELECTION_MODE_IGNORE).strip().lower()
    periods_mode = str(periods_mode or SELECTION_MODE_IGNORE).strip().lower()
    if events_mode not in SELECTION_MODES:
        events_mode = SELECTION_MODE_IGNORE
    if periods_mode not in SELECTION_MODES:
        periods_mode = SELECTION_MODE_IGNORE

    try:
        has_event_apply = (
            events_mode == SELECTION_MODE_APPLY
            and bool(event_rules)
            and any(rule.event_names for rule in event_rules)
        )
        has_period_apply = periods_mode == SELECTION_MODE_APPLY and bool(period_intervals_s)

        if has_event_apply or has_period_apply:
            apply_mask = np.zeros(mask.size, dtype=bool)
            if has_event_apply:
                _mark_event_windows(apply_mask, sample_rate, event_times_by_name or {}, event_rules or [], True)
            if has_period_apply:
                _mark_period_windows(apply_mask, sample_rate, period_intervals_s or [], True)
            mask &= apply_mask

        if events_mode == SELECTION_MODE_IGNORE and event_rules:
            _mark_event_windows(mask, sample_rate, event_times_by_name or {}, event_rules, False)

        if periods_mode == SELECTION_MODE_IGNORE and period_intervals_s:
            _mark_period_windows(mask, sample_rate, period_intervals_s, False)
    except Exception as e:
        ephyr_logger().debug(str(e))

    return mask


__all__ = [
    "IgnoreEventsRule",
    "IgnorePeriodsRule",
    "SELECTION_MODE_APPLY",
    "SELECTION_MODE_IGNORE",
    "SELECTION_MODES",
    "build_valid_mask",
]
