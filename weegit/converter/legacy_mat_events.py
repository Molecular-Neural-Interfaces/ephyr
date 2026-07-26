from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from weegit.core.header import Header
from weegit.core.weegit_session import Event, EventVocabularyEntry


class LegacyMatEventsImportError(Exception):
    pass


def import_legacy_events_from_mat(
        mat_filepath: Path,
        header: Header,
) -> Tuple[Dict[int, EventVocabularyEntry], List[Event], Dict[str, str]]:
    data = _load_mat_data(mat_filepath)
    data = _replace_original_tables_if_needed(data)
    ts_table = _extract_ts_table(data)

    raw_time_values, used_time_column = _extract_column_values(
        ts_table,
        ("start", "time_ms", "time", "timestamp", "t"),
        required=True,
    )
    raw_name_values, used_name_column = _extract_column_values(
        ts_table,
        ("name", "label", "event", "event_name", "type"),
        required=False,
    )
    raw_bad_values, used_bad_column = _extract_column_values(
        ts_table,
        ("is_bad", "bad", "isbad", "artifact", "reject"),
        required=False,
    )
    raw_sweep_values, used_sweep_column = _extract_column_values(
        ts_table,
        ("sweep_idx", "sweep", "trial", "segment"),
        required=False,
    )

    times_ms, time_conversion = _convert_time_values_to_ms(raw_time_values, header)

    vocabulary: Dict[int, EventVocabularyEntry] = {}
    name_to_id: Dict[str, int] = {}
    imported_events: List[Event] = []
    skipped_out_of_range = 0

    for idx, time_ms_candidate in enumerate(times_ms):
        event_name = _normalize_event_name(_value_at(raw_name_values, idx), idx)
        is_bad = _to_bool(_value_at(raw_bad_values, idx))
        raw_sweep_idx = _to_int(_value_at(raw_sweep_values, idx))

        # NOTE: old MAT events can store either absolute timeline values or per-sweep values.
        # We map best-effort; if shape is unclear, debugger can inspect `debug_info`.
        if raw_sweep_idx is not None:
            sweep_idx = raw_sweep_idx
            time_ms = float(time_ms_candidate)
        else:
            sweep_idx, time_ms = _split_absolute_time_to_sweep_time(time_ms_candidate, header)

        if sweep_idx < 0 or sweep_idx >= header.number_of_sweeps:
            skipped_out_of_range += 1
            continue

        sweep_duration = _sweep_duration_ms(header, sweep_idx)
        if time_ms < 0 or time_ms > sweep_duration:
            skipped_out_of_range += 1
            continue

        event_name_id = name_to_id.get(event_name)
        if event_name_id is None:
            event_name_id = len(name_to_id)
            name_to_id[event_name] = event_name_id
            vocabulary[event_name_id] = EventVocabularyEntry(name=event_name)

        imported_events.append(
            Event(
                event_name_id=event_name_id,
                sweep_idx=int(sweep_idx),
                time_ms=float(time_ms),
                is_bad=is_bad,
            )
        )

    imported_events.sort(key=lambda ev: (ev.sweep_idx, ev.time_ms))
    debug_info = {
        "source": "legacy_mat",
        "ts_time_column": used_time_column or "",
        "ts_name_column": used_name_column or "",
        "ts_bad_column": used_bad_column or "",
        "ts_sweep_column": used_sweep_column or "",
        "time_conversion": time_conversion,
        "parsed_rows": str(len(times_ms)),
        "imported_events": str(len(imported_events)),
        "skipped_out_of_range": str(skipped_out_of_range),
    }
    return vocabulary, imported_events, debug_info


def _load_mat_data(mat_filepath: Path) -> Dict[str, Any]:
    try:
        from pymatreader import read_mat

        return read_mat(str(mat_filepath))
    except Exception as pymat_error:
        try:
            from scipy.io import loadmat

            return loadmat(str(mat_filepath), squeeze_me=True, struct_as_record=False)
        except Exception as scipy_error:
            raise LegacyMatEventsImportError(
                "Cannot read .mat file. Install `pymatreader` or `scipy`."
            ) from scipy_error if isinstance(pymat_error, ImportError) else pymat_error


def _replace_original_tables_if_needed(data: Dict[str, Any]) -> Dict[str, Any]:
    subsystem = data.get("#subsystem#")
    if not isinstance(subsystem, dict):
        return data

    mcos = subsystem.get("MCOS")
    if not isinstance(mcos, (list, np.ndarray)):
        return data

    lists_in_table: List[list] = []
    source_iterable = list(mcos)[2:-1] if len(mcos) >= 3 else list(mcos)
    for elem in source_iterable:
        if isinstance(elem, list):
            lists_in_table.append(elem)

    for ii in range(1, len(lists_in_table), 2):
        if not lists_in_table[ii]:
            continue
        first = lists_in_table[ii][0]
        if not isinstance(first, (list, np.ndarray)):
            for dd in range(len(lists_in_table[ii])):
                lists_in_table[ii][dd] = [lists_in_table[ii][dd]]

    table_names = _find_matlab_table_names(data)
    count = 0
    for table_name in table_names:
        if count + 1 >= len(lists_in_table):
            break
        keys = lists_in_table[count]
        values = lists_in_table[count + 1]
        count += 2
        if not isinstance(keys, list) or not isinstance(values, list):
            continue
        table_dict = dict(zip(keys, values))
        data[table_name] = pd.DataFrame.from_dict(table_dict)

    data.pop("#subsystem#", None)
    return data


def _find_matlab_table_names(data: Dict[str, Any]) -> List[str]:
    marker = 3707764736
    table_names: List[str] = []
    for key, value in data.items():
        if isinstance(value, np.ndarray) and value.ndim == 1 and len(value) > 0:
            try:
                if int(value[0]) == marker:
                    table_names.append(key)
            except Exception:
                continue
    table_names.sort()
    return table_names


def _extract_ts_table(data: Dict[str, Any]) -> pd.DataFrame:
    for key in ("TS", "ts", "events", "Events"):
        table = data.get(key)
        if isinstance(table, pd.DataFrame):
            return table
        if isinstance(table, dict):
            return pd.DataFrame.from_dict(table)
    raise LegacyMatEventsImportError("Cannot find events table in .mat file (expected TS-like table).")


def _extract_column_values(
        table: pd.DataFrame,
        preferred_names: Sequence[str],
        required: bool,
) -> Tuple[List[Any], Optional[str]]:
    if table.empty:
        if required:
            raise LegacyMatEventsImportError("Events table is empty.")
        return [], None

    columns_lower = {str(col).lower(): col for col in table.columns}
    for name in preferred_names:
        found = columns_lower.get(name.lower())
        if found is not None:
            return table[found].tolist(), str(found)

    if required:
        raise LegacyMatEventsImportError(
            f"Cannot find required events column. Tried: {', '.join(preferred_names)}"
        )
    return [], None


def _convert_time_values_to_ms(raw_values: List[Any], header: Header) -> Tuple[List[float], str]:
    normalized_values: List[float] = []
    for item in raw_values:
        value = _to_float(item)
        if value is None:
            continue
        normalized_values.append(value)

    if not normalized_values:
        raise LegacyMatEventsImportError("No numeric event times found in .mat events table.")

    max_value = max(normalized_values)
    total_duration_ms = sum(_sweep_duration_ms(header, idx) for idx in range(max(1, header.number_of_sweeps)))
    total_duration_sec = total_duration_ms / 1000.0 if total_duration_ms > 0 else 0.0
    total_points = sum(header.number_of_points_per_sweep)

    if total_duration_ms > 0 and max_value <= total_duration_ms * 1.2:
        return normalized_values, "absolute_ms"
    if total_duration_sec > 0 and max_value <= total_duration_sec * 1.2:
        return [value * 1000.0 for value in normalized_values], "absolute_seconds"
    if total_points > 0 and max_value <= total_points * 1.2:
        ms_per_point = header.sample_interval_microseconds / 1000.0
        return [value * ms_per_point for value in normalized_values], "absolute_points"
    return normalized_values, "unknown_assume_ms"


def _split_absolute_time_to_sweep_time(absolute_time_ms: float, header: Header) -> Tuple[int, float]:
    if header.number_of_sweeps <= 1:
        return 0, float(max(0.0, absolute_time_ms))

    remaining = float(absolute_time_ms)
    for sweep_idx in range(header.number_of_sweeps):
        duration = _sweep_duration_ms(header, sweep_idx)
        if remaining <= duration:
            return sweep_idx, remaining
        remaining -= duration

    last_sweep = max(0, header.number_of_sweeps - 1)
    return last_sweep, _sweep_duration_ms(header, last_sweep)


def _sweep_duration_ms(header: Header, sweep_idx: int) -> float:
    points = list(header.number_of_points_per_sweep)
    sweep_idx = max(0, min(int(sweep_idx), len(points) - 1))
    return (header.sample_interval_microseconds / 1000.0) * float(points[sweep_idx])


def _value_at(values: List[Any], idx: int) -> Any:
    if idx < len(values):
        return values[idx]
    return None


def _to_float(value: Any) -> Optional[float]:
    scalar = _to_scalar(value)
    if scalar is None:
        return None
    try:
        if isinstance(scalar, str):
            scalar = scalar.strip().replace(",", ".")
        return float(scalar)
    except Exception:
        return None


def _to_int(value: Any) -> Optional[int]:
    float_value = _to_float(value)
    if float_value is None:
        return None
    return int(float_value)


def _to_bool(value: Any) -> bool:
    scalar = _to_scalar(value)
    if scalar is None:
        return False
    if isinstance(scalar, bool):
        return scalar
    if isinstance(scalar, (int, float)):
        return scalar != 0
    text = str(scalar).strip().lower()
    return text in {"1", "true", "yes", "y", "bad", "artifact"}


def _to_scalar(value: Any) -> Any:
    current = value
    while isinstance(current, (list, tuple, np.ndarray, pd.Series)):
        if len(current) == 0:
            return None
        current = current[0]
    return current


def _normalize_event_name(raw_name: Any, idx: int) -> str:
    scalar = _to_scalar(raw_name)
    if scalar is None:
        return f"Event {idx + 1}"
    name = str(scalar).strip()
    if not name:
        return f"Event {idx + 1}"
    return name
