# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

"""Restore channel list order from the original source format."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

from ephyr.core.header import Header

_EPHYR_SUFFIX = "_ephyr"


def natural_key(value: str) -> Tuple:
    parts = re.split(r"(\d+)", str(value))
    key: List = []
    for part in parts:
        if part.isdigit():
            key.append(int(part))
        else:
            key.append(part.lower())
    return tuple(key)


def apply_preferred_order(current: Sequence[int], preferred: Sequence[int]) -> List[int]:
    """Reorder ``current`` to follow ``preferred``, keeping unknown indices at the end."""
    current_set = set(int(ch) for ch in current)
    ordered = [int(ch) for ch in preferred if int(ch) in current_set]
    seen = set(ordered)
    ordered.extend(int(ch) for ch in current if int(ch) not in seen)
    if set(ordered) != current_set or len(ordered) != len(current):
        raise ValueError("Imported channel order does not match the current group")
    return ordered


def resolve_source_path(ephyr_folder: Optional[Path], header: Optional[Header]) -> Optional[Path]:
    """Best-effort locate the original source next to an ephyr experiment folder."""
    if header is None or ephyr_folder is None:
        return None
    folder = Path(ephyr_folder)
    parent = folder.parent
    src_type = str(header.type_before_conversion or "").lower()
    name = str(header.name_before_conversion or "").split(":", 1)[0].strip()
    candidates: List[Path] = []

    if name:
        candidates.append(parent / name)

    stem = folder.name[: -len(_EPHYR_SUFFIX)] if folder.name.endswith(_EPHYR_SUFFIX) else folder.stem
    if src_type == "nwb":
        candidates.append(parent / f"{stem}.nwb")
        if name and not name.lower().endswith(".nwb"):
            candidates.append(parent / f"{name}.nwb")
    elif src_type == "abf":
        candidates.append(parent / f"{stem}.abf")
    elif src_type == "edf":
        candidates.append(parent / f"{stem}.edf")
    elif src_type == "daq":
        candidates.append(parent / f"{stem}.daq")
    elif src_type == "xdat":
        candidates.extend(
            [
                parent / name if name else parent,
                parent / f"{stem}.xdat.json",
                parent / f"{stem}_data.xdat",
                parent / stem,
            ]
        )
    elif src_type in {"rhs", "rhd", "ncs", "openephys"}:
        candidates.append(parent / name if name else parent / stem)
        candidates.append(parent / stem)
        candidates.append(parent)

    for path in candidates:
        if path.is_file() or path.is_dir():
            return path
    return None


def source_file_dialog_filter(src_type: str) -> Tuple[str, bool]:
    """Return ``(Qt name filter, prefer_directory)`` for a manual source picker."""
    src_type = (src_type or "").lower()
    if src_type == "nwb":
        return "NWB files (*.nwb);;All files (*)", False
    if src_type == "abf":
        return "ABF files (*.abf);;All files (*)", False
    if src_type == "edf":
        return "EDF files (*.edf);;All files (*)", False
    if src_type == "daq":
        return "DAQ files (*.daq);;All files (*)", False
    if src_type == "xdat":
        return "XDAT metadata (*.xdat.json *.json);;All files (*)", False
    if src_type in {"rhs", "rhd", "ncs", "openephys"}:
        return "", True
    return "All files (*)", False


def preferred_channel_order(
    header: Header,
    *,
    source_path: Optional[Path] = None,
) -> Tuple[List[int], str]:
    """Return ``(order for all experiment channels, human-readable method)``."""
    n_channels = int(header.number_of_channels)
    if n_channels <= 0:
        raise ValueError("Header has no channels")
    src_type = str(header.type_before_conversion or "").lower()

    handlers: dict[str, Callable[[], Optional[Tuple[List[int], str]]]] = {
        "nwb": lambda: _order_from_nwb(source_path, n_channels),
        "rhs": lambda: _order_from_intan(source_path, n_channels, kind="rhs"),
        "rhd": lambda: _order_from_intan(source_path, n_channels, kind="rhd"),
        "xdat": lambda: _order_from_xdat(source_path, header, n_channels),
        "daq": lambda: _order_from_daq(source_path, header, n_channels),
        "ncs": lambda: _order_from_ncs(source_path, header, n_channels),
        "edf": lambda: _order_from_names(header, n_channels, "EDF signal labels"),
        "abf": lambda: _order_from_names(header, n_channels, "ABF ADC names"),
        "openephys": lambda: _order_from_names(header, n_channels, "Open Ephys channel names"),
    }

    handler = handlers.get(src_type)
    if handler is not None:
        result = handler()
        if result is not None:
            return result

    return list(range(n_channels)), "acquisition order"


def import_channel_order(
    header: Header,
    current_channels: Sequence[int],
    *,
    source_path: Optional[Path] = None,
) -> Tuple[List[int], str]:
    preferred, method = preferred_channel_order(header, source_path=source_path)
    return apply_preferred_order(current_channels, preferred), method


def _validate_full_order(order: Sequence[int], n_channels: int) -> List[int]:
    values = [int(ch) for ch in order]
    if sorted(values) != list(range(n_channels)):
        raise ValueError(
            f"Source channel order length/content mismatch "
            f"(got {len(values)} indices for {n_channels} channels)"
        )
    return values


def _order_from_names(header: Header, n_channels: int, method: str) -> Tuple[List[int], str]:
    names = list(header.channel_info.name or [])
    while len(names) < n_channels:
        names.append(f"ch_{len(names)}")
    order = sorted(range(n_channels), key=lambda idx: natural_key(names[idx]))
    return order, method


def _order_from_nwb(source_path: Optional[Path], n_channels: int) -> Optional[Tuple[List[int], str]]:
    if source_path is None or not Path(source_path).is_file():
        return None
    from ephyr.converter.source_reader.nwb import layout_table_from_nwb

    _table, order = layout_table_from_nwb(Path(source_path))
    if len(order) < n_channels:
        missing = [idx for idx in range(n_channels) if idx not in set(order)]
        order = list(order) + missing
    return _validate_full_order(order[:n_channels], n_channels), "NWB electrode coordinates (rel_x/rel_y)"


def _order_from_intan(
    source_path: Optional[Path],
    n_channels: int,
    *,
    kind: str,
) -> Optional[Tuple[List[int], str]]:
    if source_path is None:
        return None
    path = Path(source_path)
    from ephyr.converter.source_reader.intan_rhs_source_reader import (
        _resolve_intan_folder,
        read_header,
        read_rhd_header,
    )

    folder = _resolve_intan_folder(path)
    suffix = ".rhs" if kind == "rhs" else ".rhd"
    if path.is_file() and path.suffix.lower() == suffix:
        files = [path]
    elif folder.is_dir():
        files = sorted(
            [item for item in folder.iterdir() if item.is_file() and item.suffix.lower() == suffix],
            key=lambda item: item.stat().st_mtime,
        )
    else:
        return None
    if not files:
        return None

    with open(files[0], "rb") as fid:
        header = read_header(fid) if kind == "rhs" else read_rhd_header(fid)

    amplifiers = list(header.get("amplifier_channels") or [])
    n_amp = len(amplifiers)
    n_adc = int(header.get("num_board_adc_channels") or 0)
    if n_amp + n_adc != n_channels:
        if n_amp != n_channels and n_amp + n_adc != n_channels:
            return None

    amp_order = sorted(
        range(n_amp),
        key=lambda idx: (
            int(amplifiers[idx].get("custom_order", idx)),
            int(amplifiers[idx].get("native_order", idx)),
            idx,
        ),
    )
    if n_amp + n_adc == n_channels:
        order = amp_order + list(range(n_amp, n_amp + n_adc))
    else:
        order = amp_order
    return _validate_full_order(order, n_channels), f"Intan {kind.upper()} custom_order"


def _order_from_xdat(
    source_path: Optional[Path],
    header: Header,
    n_channels: int,
) -> Optional[Tuple[List[int], str]]:
    names = list(header.channel_info.name or [])
    probes = list(header.channel_info.probe or [])
    while len(names) < n_channels:
        names.append(f"ch_{len(names)}")
    while len(probes) < n_channels:
        probes.append("")

    if source_path is not None:
        try:
            from ephyr.converter.source_reader.xdat_source_reader import (
                _channels_from_metadata,
                _load_metadata,
                _resolve_xdat_paths,
            )

            paths = _resolve_xdat_paths(Path(source_path))
            metadata = _load_metadata(paths.metadata)
            channels = _channels_from_metadata(metadata)
            if len(channels) == n_channels:
                order = sorted(
                    range(n_channels),
                    key=lambda idx: (
                        natural_key(channels[idx].probe),
                        natural_key(channels[idx].name),
                        idx,
                    ),
                )
                return order, "XDAT port + channel name"
        except Exception:
            pass

    order = sorted(
        range(n_channels),
        key=lambda idx: (natural_key(probes[idx]), natural_key(names[idx]), idx),
    )
    return order, "XDAT port + channel name"


def _order_from_daq(
    source_path: Optional[Path],
    header: Header,
    n_channels: int,
) -> Optional[Tuple[List[int], str]]:
    hw_numbers: List[int] = []
    if source_path is not None and Path(source_path).is_file():
        try:
            from ephyr.converter.source_reader.daq_source_reader import _parse_daq_metadata

            metadata = _parse_daq_metadata(Path(source_path))
            if len(metadata.channels) == n_channels:
                hw_numbers = [int(ch.hw_channel) for ch in metadata.channels]
        except Exception:
            hw_numbers = []

    if not hw_numbers:
        names = list(header.channel_info.name or [])
        for idx in range(n_channels):
            name = names[idx] if idx < len(names) else ""
            match = re.search(r"(\d+)", str(name))
            hw_numbers.append(int(match.group(1)) if match else idx)

    order = sorted(range(n_channels), key=lambda idx: (hw_numbers[idx], idx))
    return order, "DAQ HwChannel"


def _order_from_ncs(
    source_path: Optional[Path],
    header: Header,
    n_channels: int,
) -> Optional[Tuple[List[int], str]]:
    names = list(header.channel_info.name or [])
    while len(names) < n_channels:
        names.append(f"ch_{len(names)}")

    def sort_key(idx: int):
        name = names[idx]
        if str(name).lower() == "events":
            return (1, natural_key(name), idx)
        return (0, natural_key(name), idx)

    if source_path is not None:
        try:
            from ephyr.converter.source_reader.ncs_source_reader import (
                _list_ordered_ncs_files,
                _read_ncs_header,
            )

            files = _list_ordered_ncs_files(Path(source_path))
            file_names = []
            for path in files:
                header_map = _read_ncs_header(path)
                file_names.append(header_map.get("AcqEntName") or path.stem)
            if file_names and len(file_names) <= n_channels:
                name_to_indices = {}
                for idx, name in enumerate(names):
                    name_to_indices.setdefault(str(name), []).append(idx)
                order: List[int] = []
                used = set()
                for file_name in sorted(file_names, key=natural_key):
                    bucket = name_to_indices.get(str(file_name), [])
                    for idx in bucket:
                        if idx not in used:
                            order.append(idx)
                            used.add(idx)
                            break
                order.extend(idx for idx in range(n_channels) if idx not in used)
                return _validate_full_order(order, n_channels), "Neuralynx AcqEntName"
        except Exception:
            pass

    order = sorted(range(n_channels), key=sort_key)
    return order, "Neuralynx channel names"
