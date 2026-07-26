"""Group-shared helpers for the Labeling utils add-ons."""

from __future__ import annotations

from weegit.core.add_ons import WeegitAddOnMixin


class LabelingUtilsBase(WeegitAddOnMixin):
    """Base for labeling add-ons (event detection, ...)."""


__all__ = ["LabelingUtilsBase"]
