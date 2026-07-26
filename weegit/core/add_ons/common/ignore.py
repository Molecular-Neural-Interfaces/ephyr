"""Shared helpers to ignore events and periods when analysing signals.

Both rules translate a user selection (event/period vocabulary names) into a
boolean per-sample mask over a processing window. Add-ons use the mask to skip
samples that fall inside artefacts, stimulation windows, bad periods, etc.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from pydantic import BaseModel

from weegit.logger import weegit_logger


class IgnoreEventsRule(BaseModel):
    event_names: List[str]
    before_ms: float
    after_ms: float


class IgnorePeriodsRule(BaseModel):
    period_names: List[str]


def build_valid_mask(
    n_samples: int,
    sample_rate: float,
    *,
    event_times_by_name: Optional[Dict[str, np.ndarray]] = None,
    event_rules: Optional[Sequence[IgnoreEventsRule]] = None,
    period_intervals_s: Optional[Sequence[Tuple[float, float]]] = None,
) -> np.ndarray:
    """Return a boolean mask (True == keep) of length ``n_samples``.

    ``event_times_by_name`` maps an event name to event times in seconds,
    expressed relative to the window start. ``period_intervals_s`` is a list of
    ``(start_s, end_s)`` intervals (also relative to the window start) that
    should be masked out entirely.
    """
    mask = np.ones(int(max(0, n_samples)), dtype=bool)
    if mask.size == 0 or sample_rate <= 0:
        return mask

    try:
        for rule in event_rules or []:
            for event_name in rule.event_names:
                for event_t in (event_times_by_name or {}).get(event_name, []):
                    start_idx = max(0, int((event_t - rule.before_ms / 1000.0) * sample_rate))
                    end_idx = min(mask.size, int((event_t + rule.after_ms / 1000.0) * sample_rate))
                    if end_idx > start_idx:
                        mask[start_idx:end_idx] = False

        for start_s, end_s in period_intervals_s or []:
            start_idx = max(0, int(float(start_s) * sample_rate))
            end_idx = min(mask.size, int(float(end_s) * sample_rate))
            if end_idx > start_idx:
                mask[start_idx:end_idx] = False
    except Exception as e:
        weegit_logger().debug(str(e))

    return mask


__all__ = ["IgnoreEventsRule", "IgnorePeriodsRule", "build_valid_mask"]
