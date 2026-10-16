# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

"""events.csv / periods.csv: annotations in Record time (ms from the Record start)."""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

EVENT_COLUMNS = ["id", "t_ms", "source_id", "channel", "label", "value", "is_bad"]
PERIOD_COLUMNS = ["id", "start_t_ms", "end_t_ms", "source_id", "channel", "label", "value"]


@dataclass
class EventRow:
    id: int
    t_ms: float
    label: str
    source_id: Optional[str] = None
    channel: Optional[int] = None
    value: Optional[str] = None
    is_bad: bool = False
    extra: Dict[str, str] = field(default_factory=dict)


@dataclass
class PeriodRow:
    id: int
    start_t_ms: float
    end_t_ms: float
    label: str
    source_id: Optional[str] = None
    channel: Optional[int] = None
    value: Optional[str] = None
    extra: Dict[str, str] = field(default_factory=dict)


def _optional_text(value: Optional[str]) -> Optional[str]:
    text = (value or "").strip()
    return text or None


def _optional_int(value: Optional[str]) -> Optional[int]:
    text = (value or "").strip()
    return int(text) if text else None


def _row_id(record: Dict[str, str], number: int) -> int:
    value = _optional_int(record.get("id"))
    return number if value is None else value


def _format_float(value: float) -> str:
    return repr(float(value))


def _extra_columns(rows, base: List[str]) -> List[str]:
    columns: List[str] = []
    for row in rows:
        for key in row.extra:
            if key not in base and key not in columns:
                columns.append(key)
    return columns


def _atomic_write(path: Path, header: List[str], records: List[Dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    with open(tmp_path, "w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=header)
        writer.writeheader()
        writer.writerows(records)
    os.replace(tmp_path, path)


def write_events(path: Path, rows: List[EventRow]) -> None:
    extra = _extra_columns(rows, EVENT_COLUMNS)
    records = []
    for row in rows:
        record = {
            "id": str(row.id),
            "t_ms": _format_float(row.t_ms),
            "source_id": row.source_id or "",
            "channel": "" if row.channel is None else str(row.channel),
            "label": row.label,
            "value": row.value or "",
            "is_bad": "1" if row.is_bad else "0",
        }
        record.update({key: row.extra.get(key, "") for key in extra})
        records.append(record)
    _atomic_write(path, EVENT_COLUMNS + extra, records)


def write_periods(path: Path, rows: List[PeriodRow]) -> None:
    extra = _extra_columns(rows, PERIOD_COLUMNS)
    records = []
    for row in rows:
        record = {
            "id": str(row.id),
            "start_t_ms": _format_float(row.start_t_ms),
            "end_t_ms": _format_float(row.end_t_ms),
            "source_id": row.source_id or "",
            "channel": "" if row.channel is None else str(row.channel),
            "label": row.label,
            "value": row.value or "",
        }
        record.update({key: row.extra.get(key, "") for key in extra})
        records.append(record)
    _atomic_write(path, PERIOD_COLUMNS + extra, records)


def read_events(path: Path) -> List[EventRow]:
    if not path.exists():
        return []
    rows: List[EventRow] = []
    with open(path, "r", encoding="utf-8", newline="") as file:
        for number, record in enumerate(csv.DictReader(file)):
            rows.append(
                EventRow(
                    id=_row_id(record, number),
                    t_ms=float(record["t_ms"]),
                    label=(record.get("label") or "").strip(),
                    source_id=_optional_text(record.get("source_id")),
                    channel=_optional_int(record.get("channel")),
                    value=_optional_text(record.get("value")),
                    is_bad=(record.get("is_bad") or "").strip().lower() in {"1", "true", "yes"},
                    extra={key: value for key, value in record.items()
                           if key not in EVENT_COLUMNS and key is not None and value},
                )
            )
    return rows


def read_periods(path: Path) -> List[PeriodRow]:
    if not path.exists():
        return []
    rows: List[PeriodRow] = []
    with open(path, "r", encoding="utf-8", newline="") as file:
        for number, record in enumerate(csv.DictReader(file)):
            start = float(record["start_t_ms"])
            end = float(record["end_t_ms"])
            rows.append(
                PeriodRow(
                    id=_row_id(record, number),
                    start_t_ms=min(start, end),
                    end_t_ms=max(start, end),
                    label=(record.get("label") or "").strip(),
                    source_id=_optional_text(record.get("source_id")),
                    channel=_optional_int(record.get("channel")),
                    value=_optional_text(record.get("value")),
                    extra={key: value for key, value in record.items()
                           if key not in PERIOD_COLUMNS and key is not None and value},
                )
            )
    return rows
