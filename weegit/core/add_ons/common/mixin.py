"""Base mixin with shared helpers for Weegit add-ons.

Add-ons subclass ``(WeegitAddOnMixin, BaseAddOn)`` to get channel/group
selection widgets, ignore-event/period controls, event/period time resolution,
channel matrix loading and session-persistent parameter storage. The mixin is
deliberately group-agnostic: it lives in core and is shared by every add-on
group without creating cross-group dependencies.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
)

from weegit.core.add_ons.common.preprocessing import (
    PIPELINES_FILENAME,
    PipelineSpec,
    apply_single_step,
    enabled_steps,
    step_label,
)
from weegit.core.add_ons.common.state import COMMON_SCOPE, SessionParamStore
from weegit.logger import weegit_logger


class WeegitAddOnMixin:
    """Common helpers for add-on dialogs and data access."""

    # ---- Parameter persistence ----
    def param_store(self, add_on_data_dir: Path) -> SessionParamStore:
        return SessionParamStore.from_add_on_data_dir(Path(add_on_data_dir))

    def addon_scope(self) -> str:
        return str(getattr(self, "_weegit_module_name", type(self).__name__))

    def load_common(self, add_on_data_dir: Path) -> Dict[str, Any]:
        return dict(self.param_store(add_on_data_dir).get_all(COMMON_SCOPE))

    def save_common(self, add_on_data_dir: Path, values: Dict[str, Any]) -> None:
        self.param_store(add_on_data_dir).update(COMMON_SCOPE, values)

    def load_params(self, add_on_data_dir: Path) -> Dict[str, Any]:
        return dict(self.param_store(add_on_data_dir).get_all(self.addon_scope()))

    def save_params(self, add_on_data_dir: Path, values: Dict[str, Any]) -> None:
        self.param_store(add_on_data_dir).update(self.addon_scope(), values)

    def pipelines_path(self, add_on_data_dir: Path) -> Path:
        return Path(add_on_data_dir).parent / "weegit" / PIPELINES_FILENAME

    # ---- Channel groups ----
    def channel_groups(self, session_manager) -> List[Tuple[int, Any]]:
        """All channel groups with channels, including auxiliary groups."""
        return [
            (idx, group)
            for idx, group in enumerate(session_manager.user_session.gui_setup.channels_groups or [])
            if getattr(group, "channel_indexes", [])
        ]

    def non_aux_groups(self, session_manager) -> List[Tuple[int, Any]]:
        # Kept for callers that still want non-aux only; most add-ons use channel_groups.
        return [
            (idx, group)
            for idx, group in self.channel_groups(session_manager)
            if not getattr(group, "is_auxiliary", False)
        ]

    def ensure_channel_groups(self, session_manager, title: str) -> Optional[List[Tuple[int, Any]]]:
        groups = self.channel_groups(session_manager)
        if not groups:
            QMessageBox.warning(None, title, "No channel groups configured.")
            return None
        return groups

    def ensure_non_aux_groups(self, session_manager, title: str) -> Optional[List[Tuple[int, Any]]]:
        # Include AUX groups as well — users need them for event/TTL channels.
        return self.ensure_channel_groups(session_manager, title)

    @staticmethod
    def channel_name(header, channel_idx: int) -> str:
        try:
            names = header.channel_info.name or []
            if 0 <= int(channel_idx) < len(names):
                name = str(names[int(channel_idx)]).strip()
                if name:
                    return name
        except Exception as e:
            weegit_logger().debug(str(e))
        return f"ch{int(channel_idx)}"

    def build_group_channel_selector(
        self,
        form: QFormLayout,
        groups: List[Tuple[int, Any]],
        header,
        preferred_group_idx: int = 0,
        preferred_channels: Optional[List[int]] = None,
    ) -> Tuple[QComboBox, QListWidget]:
        group_combo = QComboBox()
        for group_idx, group in groups:
            aux_tag = " [AUX]" if getattr(group, "is_auxiliary", False) else ""
            group_combo.addItem(f"#{group_idx} {group.name}{aux_tag}", group_idx)
        default_group_pos = group_combo.findData(int(preferred_group_idx))
        group_combo.setCurrentIndex(max(0, default_group_pos))
        form.addRow("Channel group:", group_combo)

        channels_list = QListWidget()
        channels_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        form.addRow("Channels:", channels_list)

        preferred = set(int(c) for c in (preferred_channels or []))

        def rebuild() -> None:
            channels_list.clear()
            group_idx = int(group_combo.currentData())
            group = next((g for idx, g in groups if idx == group_idx), None)
            enabled = set(getattr(group, "enabled_indexes", set()) or set()) if group is not None else set()
            selected_by_default = preferred if preferred else enabled
            for ch_idx in (getattr(group, "channel_indexes", []) or []):
                ch_name = self.channel_name(header, int(ch_idx))
                label = f"{ch_idx} [{ch_name}]"
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, int(ch_idx))
                item.setSelected(int(ch_idx) in selected_by_default)
                channels_list.addItem(item)

        group_combo.currentIndexChanged.connect(lambda _idx: rebuild())
        rebuild()
        return group_combo, channels_list

    @staticmethod
    def selected_channels(channels_list: QListWidget) -> List[int]:
        selected: List[int] = []
        seen = set()
        for row in range(channels_list.count()):
            item = channels_list.item(row)
            if item is None or (not item.isSelected()):
                continue
            value = item.data(Qt.ItemDataRole.UserRole)
            if value is None:
                continue
            ch_idx = int(value)
            if ch_idx not in seen:
                selected.append(ch_idx)
                seen.add(ch_idx)
        return selected

    # ---- Events / periods vocabulary ----
    def event_vocabulary_names(self, session_manager) -> List[str]:
        names: List[str] = []
        for _event_id, entry in (session_manager.events_vocabulary or {}).items():
            name = str(getattr(entry, "name", "")).strip()
            if name:
                names.append(name)
        return sorted(set(names))

    def period_vocabulary_names(self, session_manager) -> List[str]:
        names: List[str] = []
        for _pid, entry in (session_manager.periods_vocabulary or {}).items():
            name = str(getattr(entry, "name", "")).strip()
            if name:
                names.append(name)
        return sorted(set(names))

    def build_ignore_events_controls(
        self,
        form: QFormLayout,
        session_manager,
        selected_names: Optional[List[str]] = None,
        before_ms: float = 0.0,
        after_ms: float = 0.0,
    ) -> Tuple[QListWidget, QDoubleSpinBox, QDoubleSpinBox]:
        events_list = QListWidget()
        events_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        selected = set(selected_names or [])
        for name in self.event_vocabulary_names(session_manager):
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setSelected(name in selected)
            events_list.addItem(item)
        form.addRow("Ignore events:", events_list)

        before_spin = QDoubleSpinBox()
        before_spin.setRange(0.0, 60_000.0)
        before_spin.setDecimals(3)
        before_spin.setValue(float(before_ms))
        form.addRow("Ignore before (ms):", before_spin)

        after_spin = QDoubleSpinBox()
        after_spin.setRange(0.0, 60_000.0)
        after_spin.setDecimals(3)
        after_spin.setValue(float(after_ms))
        form.addRow("Ignore after (ms):", after_spin)
        return events_list, before_spin, after_spin

    def build_ignore_periods_controls(
        self,
        form: QFormLayout,
        session_manager,
        selected_names: Optional[List[str]] = None,
    ) -> QListWidget:
        periods_list = QListWidget()
        periods_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        selected = set(selected_names or [])
        for name in self.period_vocabulary_names(session_manager):
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setSelected(name in selected)
            periods_list.addItem(item)
        form.addRow("Ignore periods:", periods_list)
        return periods_list

    @staticmethod
    def selected_names_from_list(list_widget: QListWidget) -> List[str]:
        names: List[str] = []
        for item in list_widget.selectedItems():
            value = item.data(Qt.ItemDataRole.UserRole)
            if value:
                names.append(str(value))
        return sorted(set(names))

    # ---- Time resolution ----
    def event_times_by_name_for_window(
        self,
        session_manager,
        sweep_idx: int,
        start_second: float,
        end_second: float,
    ) -> Dict[str, np.ndarray]:
        event_times: Dict[str, List[float]] = {}
        for event in session_manager.events or []:
            if int(event.sweep_idx) != int(sweep_idx):
                continue
            event_time_s = float(event.time_ms) / 1000.0
            if event_time_s < start_second or event_time_s > end_second:
                continue
            event_name = session_manager.user_session.get_event_vocabulary_name(event.event_name_id)
            event_times.setdefault(event_name, []).append(event_time_s - start_second)
        return {k: np.asarray(v, dtype=float) for k, v in event_times.items()}

    def period_intervals_for_window(
        self,
        session_manager,
        sweep_idx: int,
        start_second: float,
        end_second: float,
        period_names: Optional[List[str]] = None,
    ) -> List[Tuple[float, float]]:
        """Return period intervals (seconds, relative to window start) that
        overlap the window for the given sweep, restricted to ``period_names``.

        An empty ``period_names`` means "ignore nothing" (return no intervals).
        """
        wanted = set(period_names or [])
        if not wanted:
            return []
        intervals: List[Tuple[float, float]] = []
        for period in session_manager.periods or []:
            name = session_manager.user_session.get_period_vocabulary_name(period.period_name_id)
            if name not in wanted:
                continue
            if int(period.start_sweep_idx) > int(sweep_idx) or int(period.end_sweep_idx) < int(sweep_idx):
                continue
            p_start_s = float(period.start_time_ms) / 1000.0 if int(period.start_sweep_idx) == int(sweep_idx) else start_second
            p_end_s = float(period.end_time_ms) / 1000.0 if int(period.end_sweep_idx) == int(sweep_idx) else end_second
            lo = max(start_second, p_start_s)
            hi = min(end_second, p_end_s)
            if hi > lo:
                intervals.append((lo - start_second, hi - start_second))
        return intervals

    # ---- Data access ----
    def channel_matrix_from_session(
        self,
        session_manager,
        channel_indexes: List[int],
        sweep_idx: int,
        start_sample: int,
        end_sample: int,
        sample_rate: float,
    ) -> np.ndarray:
        n_samples = max(1, int(end_sample) - int(start_sample))
        rows = []
        for channel_idx in channel_indexes:
            try:
                signal = session_manager.experiment_data.process_single_channel(
                    channel_idx=int(channel_idx),
                    sweep_idx=int(sweep_idx),
                    start_sample=int(start_sample),
                    end_sample=int(end_sample),
                    each_point=1,
                    sample_rate=float(sample_rate),
                    filters=[],
                    output_number_of_dots=n_samples,
                    transformation_add_ons=[],
                )
                rows.append(np.asarray(signal, dtype=np.float64))
            except Exception as e:
                weegit_logger().debug(str(e))
                rows.append(np.zeros(n_samples, dtype=np.float64))
        return np.vstack(rows) if rows else np.empty((0, n_samples), dtype=np.float64)

    def iter_apply_pipeline(
        self,
        matrix: np.ndarray,
        sample_rate: float,
        pipeline: Optional[PipelineSpec],
        *,
        base_progress: int = 0,
        progress_span: int = 100,
        message_prefix: str = "Preprocessing pipeline",
    ):
        """Generator that applies a pipeline step-by-step while yielding
        ``{"progress", "message"}`` dicts, and returns the processed matrix.

        Use ``processed = yield from self.iter_apply_pipeline(...)`` inside an
        add-on ``run()`` generator so the loading screen shows a
        "Preprocessing pipeline: <step>" message while the work runs.
        """
        out = np.asarray(matrix, dtype=np.float64).copy()
        steps = enabled_steps(pipeline)
        total = len(steps)
        if total == 0:
            return out
        for idx, step in enumerate(steps, start=1):
            progress = int(base_progress + ((idx - 1) / total) * progress_span)
            yield {"progress": progress, "message": f"{message_prefix}: {step_label(step)}"}
            out = apply_single_step(out, sample_rate, step)
        yield {"progress": int(base_progress + progress_span), "message": f"{message_prefix}: done"}
        return out


__all__ = ["WeegitAddOnMixin"]
