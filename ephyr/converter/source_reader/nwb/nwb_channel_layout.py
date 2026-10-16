# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

"""Build a ChannelsLayout grid from NWB electrode coordinates."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from pynwb import NWBHDF5IO
from pynwb.ecephys import ElectricalSeries

from .nwb_source_reader import _choose_series, _iter_series


def resolve_nwb_source_path(source_path: Optional[Path], source_format: str) -> Optional[Path]:
    """The original .nwb of a Record if its last known location on this machine still exists."""
    if source_format != "nwb" or source_path is None:
        return None
    path = Path(source_path)
    return path if path.is_file() and path.suffix.lower() == ".nwb" else None


def _electrode_xy(series: ElectricalSeries) -> Optional[Tuple[List[float], List[float]]]:
    electrodes = getattr(series, "electrodes", None)
    if electrodes is None:
        return None
    try:
        table = electrodes.table
        indexes = [int(i) for i in electrodes.data[:]]
    except Exception:
        return None

    # Prefer probe-relative columns; fall back to absolute ElectrodesTable x/y.
    # NWB absolute (+x posterior, +y inferior, +z right) is for anatomy; MEA/probe
    # face geometry is normally stored in rel_x / rel_y.
    x_col = next((name for name in ("rel_x", "x") if name in table), None)
    y_col = next((name for name in ("rel_y", "y") if name in table), None)
    if x_col is None or y_col is None:
        return None

    xs: List[float] = []
    ys: List[float] = []
    try:
        x_data = table[x_col].data
        y_data = table[y_col].data
        for table_idx in indexes:
            xs.append(float(x_data[table_idx]))
            ys.append(float(y_data[table_idx]))
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

    Grid orientation matches a Cartesian probe map: ``x`` increases to the right,
    ``y`` increases upward (larger ``y`` → top rows). Ephyr draws ``layout_table[0]``
    at the top of the panel, so ``y`` is sorted descending when assigning rows.
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
    # Row 0 is the top of the Ephyr grid → larger Y must come first (Y-up).
    uniq_y = sorted({y for _ch, _x, y in pairs}, reverse=True)
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
