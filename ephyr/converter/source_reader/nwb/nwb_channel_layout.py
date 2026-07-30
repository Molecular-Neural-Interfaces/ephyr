# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

"""Build a ChannelsLayout grid from NWB electrode coordinates."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from pynwb import NWBHDF5IO
from pynwb.ecephys import ElectricalSeries

from .nwb_source_reader import _choose_series, _iter_series


def resolve_nwb_source_path(ephyr_folder: Optional[Path], header) -> Optional[Path]:
    """Best-effort locate the original .nwb next to an ephyr experiment folder."""
    if header is None or getattr(header, "type_before_conversion", None) != "nwb":
        return None
    name = str(getattr(header, "name_before_conversion", "") or "")
    source_name = name.split(":", 1)[0].strip()
    if not source_name.lower().endswith(".nwb"):
        source_name = ""

    candidates: List[Path] = []
    if ephyr_folder is not None:
        folder = Path(ephyr_folder)
        parent = folder.parent
        if source_name:
            candidates.append(parent / source_name)
        suffix = "_ephyr"
        if folder.name.endswith(suffix):
            candidates.append(parent / f"{folder.name[: -len(suffix)]}.nwb")

    for path in candidates:
        if path.is_file():
            return path
    return None


def _electrode_xy(series: ElectricalSeries) -> Optional[Tuple[List[float], List[float]]]:
    electrodes = getattr(series, "electrodes", None)
    if electrodes is None:
        return None
    try:
        table = electrodes.table
        indexes = [int(i) for i in electrodes.data[:]]
    except Exception:
        return None

    x_col = next((name for name in ("rel_x", "x") if name in table), None)
    y_col = next((name for name in ("rel_y", "y") if name in table), None)
    if x_col is None or y_col is None:
        return None

    xs: List[float] = []
    ys: List[float] = []
    try:
        for table_idx in indexes:
            xs.append(float(table[x_col].data[table_idx]))
            ys.append(float(table[y_col].data[table_idx]))
    except Exception:
        return None
    if len(xs) != len(ys) or not xs:
        return None
    return xs, ys


def layout_table_from_nwb(
    nwb_path: Path,
    *,
    allowed_channels: Optional[Sequence[int]] = None,
) -> Tuple[List[List[int]], List[int]]:
    """Return ``(layout_table, channel_order)`` from NWB ``rel_x``/``rel_y`` (or ``x``/``y``).

    Empty cells are ``-1``. ``channel_order`` is row-major over occupied cells.
    """
    path = Path(nwb_path)
    if not path.is_file() or path.suffix.lower() != ".nwb":
        raise ValueError(f"Not an NWB file: {path}")

    with NWBHDF5IO(str(path), "r", load_namespaces=True) as io:
        nwbfile = io.read()
        series: Optional[ElectricalSeries] = None
        _ref, chosen = _choose_series(nwbfile)
        if isinstance(chosen, ElectricalSeries):
            series = chosen
        else:
            for _loc, obj in _iter_series(nwbfile):
                if isinstance(obj, ElectricalSeries):
                    series = obj
                    break
        if series is None:
            raise ValueError("NWB file has no ElectricalSeries")
        xy = _electrode_xy(series)
        if xy is None:
            raise ValueError(
                "ElectricalSeries electrodes table has no usable x/y coordinates "
                "(expected rel_x/rel_y or x/y)"
            )
        xs, ys = xy
        n_channels = len(xs)

    allowed = set(int(ch) for ch in allowed_channels) if allowed_channels is not None else None
    pairs: List[Tuple[int, float, float]] = []
    for ch, x, y in zip(range(n_channels), xs, ys):
        if allowed is not None and ch not in allowed:
            continue
        pairs.append((ch, x, y))
    if not pairs:
        raise ValueError("No channels with coordinates match the current group")

    uniq_x = sorted({x for _ch, x, _y in pairs})
    uniq_y = sorted({y for _ch, _x, y in pairs})
    x_to_col = {value: idx for idx, value in enumerate(uniq_x)}
    y_to_row = {value: idx for idx, value in enumerate(uniq_y)}
    rows = len(uniq_y)
    cols = len(uniq_x)
    table = [[-1] * cols for _ in range(rows)]
    for ch, x, y in pairs:
        r = y_to_row[y]
        c = x_to_col[x]
        if table[r][c] >= 0 and table[r][c] != ch:
            raise ValueError(f"Duplicate electrode coordinates for channels {table[r][c]} and {ch}")
        table[r][c] = ch

    order = [table[r][c] for r in range(rows) for c in range(cols) if table[r][c] >= 0]
    if allowed is not None:
        missing = [ch for ch in allowed_channels if ch not in set(order)]
        order.extend(missing)
    return table, order
