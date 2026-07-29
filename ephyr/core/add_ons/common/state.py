# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

"""Session-scoped, disk-backed parameter persistence for add-ons.

Add-on dialogs should remember the values a user entered last time so they do
not have to re-type every parameter on each open. State is stored as JSON under
``$SESSION/add_ons/data/ephyr/<scope>.json`` so it survives app restarts and
development reloads, while staying scoped to a single experiment session.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from ephyr.logger import ephyr_logger

COMMON_SCOPE = "common"


class SessionParamStore:
    """Read/write small JSON parameter dictionaries scoped to a session.

    A ``scope`` is a logical namespace (a filename stem). Use ``COMMON_SCOPE``
    for selections shared between add-ons (channel group, channels, ignore
    rules, selected preprocessing pipeline) and a per-add-on scope for
    add-on-specific parameters (thresholds, plot toggles, ...).
    """

    def __init__(self, base_dir: Path):
        self._base_dir = Path(base_dir)
        self._cache: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def from_add_on_data_dir(cls, add_on_data_dir: Path) -> "SessionParamStore":
        # run() receives ``.../add_ons/data/<module_name>``; the shared ephyr
        # folder lives next to the per-module folders.
        return cls(Path(add_on_data_dir).parent / "ephyr")

    def _path(self, scope: str) -> Path:
        return self._base_dir / f"{scope}.json"

    def get_all(self, scope: str) -> Dict[str, Any]:
        if scope in self._cache:
            return self._cache[scope]
        values: Dict[str, Any] = {}
        path = self._path(scope)
        if path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    values = loaded
            except Exception as e:
                ephyr_logger().debug(str(e))
        self._cache[scope] = values
        return values

    def get(self, scope: str, key: str, default: Optional[Any] = None) -> Any:
        return self.get_all(scope).get(key, default)

    def update(self, scope: str, values: Dict[str, Any]) -> None:
        current = dict(self.get_all(scope))
        current.update(values or {})
        self._cache[scope] = current
        try:
            self._base_dir.mkdir(parents=True, exist_ok=True)
            self._path(scope).write_text(
                json.dumps(current, ensure_ascii=True, indent=2), encoding="utf-8"
            )
        except Exception as e:
            ephyr_logger().debug(str(e))


__all__ = ["SessionParamStore", "COMMON_SCOPE"]
