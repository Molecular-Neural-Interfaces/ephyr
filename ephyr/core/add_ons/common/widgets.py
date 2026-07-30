# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

"""Reusable Qt widgets shared by add-on dialogs.

Contains the filter editor, the preprocessing pipeline selector (with an inline
"Manage pipelines" button) and the pipeline builder dialog. Keeping these in
core means every add-on gets a consistent UI for the shared concepts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ephyr.core.conversions.filters import (
    BaseFilter,
    ButterworthBandPassFilter,
    ButterworthHighPassFilter,
    ButterworthLowPassFilter,
    ChebyshevBandPassFilter,
    NotchFilter,
    all_filter_names,
    filter_class_by_name,
)
from ephyr.core.add_ons.common.preprocessing import (
    DEFAULT_PIPELINE_NAME,
    STEP_KINDS,
    PipelineSpec,
    PreprocessingStep,
    read_pipeline_store,
    write_pipeline_store,
)
from ephyr.logger import ephyr_logger


class FilterEditor:
    """Compact editor for a single optional filter, rendered into a form."""

    def __init__(self, form: QFormLayout, title: str, default_spec: Optional[Dict[str, Any]]):
        self._use_filter_checkbox = QCheckBox("Use filter")
        self._selector = QComboBox()
        self._selector.addItems(all_filter_names())
        self._params_container = QWidget()
        self._params_layout = QVBoxLayout(self._params_container)
        self._params_layout.setContentsMargins(0, 0, 0, 0)
        self._param_inputs: Dict[str, Any] = {}

        form.addRow(f"{title}:", self._use_filter_checkbox)
        form.addRow(f"{title} type:", self._selector)
        form.addRow(f"{title} params:", self._params_container)

        self._use_filter_checkbox.stateChanged.connect(self._on_filter_enabled_changed)
        self._selector.currentIndexChanged.connect(self._rebuild_filter_params)
        self.apply_spec(default_spec)

    def apply_spec(self, filter_spec: Optional[Dict[str, Any]]) -> None:
        if not filter_spec:
            self._use_filter_checkbox.setChecked(False)
            self._selector.setCurrentIndex(0)
            self._selector.setEnabled(False)
            self._rebuild_filter_params()
            return
        self._use_filter_checkbox.setChecked(bool(filter_spec.get("enabled", True)))
        filter_name = str(filter_spec.get("filter_name", "")).strip()
        idx = self._selector.findText(filter_name)
        if idx >= 0:
            self._selector.setCurrentIndex(idx)
        self._selector.setEnabled(self._use_filter_checkbox.isChecked())
        self._rebuild_filter_params()
        params = dict(filter_spec.get("params", {}) or {})
        for key, widget in self._param_inputs.items():
            if key not in params:
                continue
            value = params[key]
            if isinstance(widget, QDoubleSpinBox):
                widget.setValue(float(value))
            elif isinstance(widget, QSpinBox):
                widget.setValue(int(value))

    def _clear_layout(self, layout_obj) -> None:
        while layout_obj.count():
            item = layout_obj.takeAt(0)
            widget = item.widget()
            child_layout = item.layout()
            if widget is not None:
                widget.deleteLater()
            elif child_layout is not None:
                self._clear_layout(child_layout)

    def _add_param_spin(self, label: str, key: str, value: float, min_v: float, max_v: float, step: float) -> None:
        row = QHBoxLayout()
        row.addWidget(QLabel(label))
        spin = QDoubleSpinBox()
        spin.setRange(min_v, max_v)
        spin.setDecimals(6)
        spin.setSingleStep(step)
        spin.setValue(float(value))
        row.addWidget(spin)
        self._params_layout.addLayout(row)
        self._param_inputs[key] = spin

    def _add_param_int(self, label: str, key: str, value: int, min_v: int, max_v: int) -> None:
        row = QHBoxLayout()
        row.addWidget(QLabel(label))
        spin = QSpinBox()
        spin.setRange(min_v, max_v)
        spin.setSingleStep(1)
        spin.setValue(int(value))
        row.addWidget(spin)
        self._params_layout.addLayout(row)
        self._param_inputs[key] = spin

    def _on_filter_enabled_changed(self, _state: int) -> None:
        self._selector.setEnabled(self._use_filter_checkbox.isChecked())
        self._rebuild_filter_params()

    def _rebuild_filter_params(self) -> None:
        self._clear_layout(self._params_layout)
        self._param_inputs.clear()
        if not self._use_filter_checkbox.isChecked():
            return
        cls = filter_class_by_name(self._selector.currentText().strip())
        if cls is None:
            return
        flt = cls()
        if isinstance(flt, ButterworthLowPassFilter):
            self._add_param_spin("Cutoff (Hz):", "cutoff_hz", flt.cutoff_hz, 0.1, 1e6, 1.0)
            self._add_param_int("Order:", "order", flt.order, 1, 12)
        elif isinstance(flt, ButterworthHighPassFilter):
            self._add_param_spin("Cutoff (Hz):", "cutoff_hz", flt.cutoff_hz, 0.1, 1e6, 1.0)
            self._add_param_int("Order:", "order", flt.order, 1, 12)
        elif isinstance(flt, ButterworthBandPassFilter):
            self._add_param_spin("Low cut (Hz):", "lowcut_hz", flt.lowcut_hz, 0.1, 1e6, 1.0)
            self._add_param_spin("High cut (Hz):", "highcut_hz", flt.highcut_hz, 0.1, 1e6, 1.0)
            self._add_param_int("Order:", "order", flt.order, 1, 12)
        elif isinstance(flt, ChebyshevBandPassFilter):
            self._add_param_spin("Low cut (Hz):", "lowcut_hz", flt.lowcut_hz, 0.1, 1e6, 1.0)
            self._add_param_spin("High cut (Hz):", "highcut_hz", flt.highcut_hz, 0.1, 1e6, 1.0)
            self._add_param_int("Order:", "order", flt.order, 1, 12)
            self._add_param_spin("Ripple (dB):", "ripple_db", flt.ripple_db, 0.1, 10.0, 0.1)
        elif isinstance(flt, NotchFilter):
            self._add_param_spin("Notch (Hz):", "notch_freq_hz", flt.notch_freq_hz, 1.0, 1e6, 1.0)
            self._add_param_spin("Q factor:", "q_factor", flt.q_factor, 0.1, 200.0, 0.1)

    def get_filter_spec(self) -> Optional[Dict[str, Any]]:
        if not self._use_filter_checkbox.isChecked():
            return None
        params: Dict[str, Any] = {}
        for key, widget in self._param_inputs.items():
            if isinstance(widget, QDoubleSpinBox):
                params[key] = float(widget.value())
            elif isinstance(widget, QSpinBox):
                params[key] = int(widget.value())
        return {
            "enabled": True,
            "filter_name": self._selector.currentText().strip(),
            "params": params,
        }


def filter_from_spec(spec: Optional[Dict[str, Any]]) -> Optional[BaseFilter]:
    if not spec or not bool(spec.get("enabled", True)):
        return None
    cls = filter_class_by_name(str(spec.get("filter_name", "")).strip())
    if cls is None:
        return None
    flt = cls()
    setattr(flt, "enabled", True)
    for key, value in (spec.get("params", {}) or {}).items():
        if hasattr(flt, key):
            current = getattr(flt, key)
            setattr(flt, key, int(value) if isinstance(current, int) else float(value))
    if hasattr(flt, "sos_cache"):
        flt.sos_cache = {}
    return flt


class PipelineBuilderDialog(QDialog):
    """Create or edit named preprocessing pipelines saved to the session store."""

    def __init__(self, pipelines_path: Path, parent=None, initial_name: str = ""):
        super().__init__(parent)
        self._pipelines_path = Path(pipelines_path)
        self._store = read_pipeline_store(self._pipelines_path)
        self._steps: List[PreprocessingStep] = []
        self.setWindowTitle("Preprocessing pipelines")
        self.setMinimumWidth(640)
        self._build_ui()
        if initial_name and initial_name in self._store:
            idx = self._pipeline_combo.findText(initial_name)
            if idx >= 0:
                self._pipeline_combo.setCurrentIndex(idx)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._pipeline_combo = QComboBox()
        self._pipeline_combo.addItem("<new pipeline>", "")
        for name in sorted(self._store.keys()):
            self._pipeline_combo.addItem(name, name)
        self._pipeline_combo.currentIndexChanged.connect(lambda _i: self._on_pipeline_selected())
        form.addRow("Edit existing:", self._pipeline_combo)

        self._name_edit = QLineEdit()
        form.addRow("Pipeline name:", self._name_edit)
        self._description_edit = QLineEdit()
        form.addRow("Description:", self._description_edit)

        self._steps_list = QListWidget()
        form.addRow("Ordered steps:", self._steps_list)

        buttons = QHBoxLayout()
        btn_add = QPushButton("Add step")
        btn_remove = QPushButton("Remove")
        btn_up = QPushButton("Up")
        btn_down = QPushButton("Down")
        buttons.addWidget(btn_add)
        buttons.addWidget(btn_remove)
        buttons.addWidget(btn_up)
        buttons.addWidget(btn_down)
        form.addRow("", buttons)
        btn_add.clicked.connect(self._add_step)
        btn_remove.clicked.connect(self._remove_step)
        btn_up.clicked.connect(lambda: self._move_step(-1))
        btn_down.clicked.connect(lambda: self._move_step(1))

        layout.addLayout(form)

        actions = QHBoxLayout()
        btn_delete = QPushButton("Delete pipeline")
        btn_close = QPushButton("Close")
        btn_save = QPushButton("Save")
        actions.addWidget(btn_delete)
        actions.addStretch(1)
        actions.addWidget(btn_close)
        actions.addWidget(btn_save)
        layout.addLayout(actions)
        btn_delete.clicked.connect(self._delete_pipeline)
        btn_close.clicked.connect(self.reject)
        btn_save.clicked.connect(self._save_pipeline)

    @staticmethod
    def _step_label(step: PreprocessingStep) -> str:
        params = ", ".join(f"{k}={v}" for k, v in step.params.items())
        prefix = STEP_KINDS.get(step.kind, step.kind)
        return f"{prefix} ({params})" if params else prefix

    def _refresh_steps(self) -> None:
        self._steps_list.clear()
        for idx, step in enumerate(self._steps, start=1):
            self._steps_list.addItem(QListWidgetItem(f"{idx}. {self._step_label(step)}"))

    def _on_pipeline_selected(self) -> None:
        name = str(self._pipeline_combo.currentData() or "")
        if not name:
            self._name_edit.setText("")
            self._description_edit.setText("")
            self._steps = []
            self._refresh_steps()
            return
        spec = self._store.get(name)
        if spec is None:
            return
        self._name_edit.setText(spec.name)
        self._description_edit.setText(spec.description)
        self._steps = [s.model_copy(deep=True) for s in spec.steps]
        self._refresh_steps()

    def _add_step(self) -> None:
        step = self._ask_step()
        if step is not None:
            self._steps.append(step)
            self._refresh_steps()

    def _remove_step(self) -> None:
        row = self._steps_list.currentRow()
        if 0 <= row < len(self._steps):
            self._steps.pop(row)
            self._refresh_steps()

    def _move_step(self, delta: int) -> None:
        row = self._steps_list.currentRow()
        new_row = row + delta
        if 0 <= row < len(self._steps) and 0 <= new_row < len(self._steps):
            self._steps[row], self._steps[new_row] = self._steps[new_row], self._steps[row]
            self._refresh_steps()
            self._steps_list.setCurrentRow(new_row)

    def _ask_step(self) -> Optional[PreprocessingStep]:
        dialog = QDialog(self)
        dialog.setWindowTitle("Add preprocessing step")
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        kind_combo = QComboBox()
        for key, label in STEP_KINDS.items():
            kind_combo.addItem(label, key)
        form.addRow("Step:", kind_combo)

        params_layout = QFormLayout()
        form.addRow(QLabel("Parameters:"))
        form.addRow(params_layout)
        widgets: Dict[str, Any] = {}

        def clear_params() -> None:
            while params_layout.count():
                item = params_layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
            widgets.clear()

        def add_double(label: str, key: str, value: float, low: float = 0.0, high: float = 1_000_000.0) -> None:
            spin = QDoubleSpinBox()
            spin.setRange(low, high)
            spin.setDecimals(6)
            spin.setValue(float(value))
            params_layout.addRow(label, spin)
            widgets[key] = spin

        def add_int(label: str, key: str, value: int, low: int = 0, high: int = 64) -> None:
            spin = QSpinBox()
            spin.setRange(low, high)
            spin.setValue(int(value))
            params_layout.addRow(label, spin)
            widgets[key] = spin

        def rebuild_params() -> None:
            clear_params()
            kind = str(kind_combo.currentData())
            if kind == "trim":
                add_double("Trim seconds:", "trim_seconds", 0.0, 0.0, 3600.0)
            elif kind == "baseline":
                add_int("Polynomial order:", "order", 1, 0, 6)
            elif kind == "highpass":
                add_double("Cutoff (Hz):", "cutoff_hz", 300.0, 0.1)
                add_int("Order:", "order", 3, 1, 12)
            elif kind == "lowpass":
                add_double("Cutoff (Hz):", "cutoff_hz", 3000.0, 0.1)
                add_int("Order:", "order", 3, 1, 12)
            elif kind == "bandpass":
                add_double("Low cut (Hz):", "lowcut_hz", 300.0, 0.1)
                add_double("High cut (Hz):", "highcut_hz", 3000.0, 0.1)
                add_int("Order:", "order", 3, 1, 12)
            elif kind == "notch":
                add_double("Frequency (Hz):", "notch_freq_hz", 50.0, 1.0)
                add_double("Q factor:", "q_factor", 30.0, 0.1, 300.0)
            elif kind == "artifact_removal":
                add_double("Threshold (robust z):", "threshold_z", 5.0, 0.1, 1000.0)
                add_double("Min distance (ms):", "min_distance_ms", 20.0, 0.0, 60_000.0)
                add_double("Pre window (ms):", "pre_ms", 5.0, 0.0, 60_000.0)
                add_double("Post window (ms):", "post_ms", 25.0, 0.0, 60_000.0)
                add_double("Merge gap (ms):", "merge_gap_ms", 5.0, 0.0, 60_000.0)

        kind_combo.currentIndexChanged.connect(lambda _i: rebuild_params())
        rebuild_params()

        layout.addLayout(form)
        actions = QHBoxLayout()
        btn_cancel = QPushButton("Cancel")
        btn_ok = QPushButton("Add")
        actions.addStretch(1)
        actions.addWidget(btn_cancel)
        actions.addWidget(btn_ok)
        layout.addLayout(actions)
        btn_cancel.clicked.connect(dialog.reject)
        btn_ok.clicked.connect(dialog.accept)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        params: Dict[str, Any] = {}
        for key, widget in widgets.items():
            if isinstance(widget, QComboBox):
                params[key] = widget.currentText().strip()
            else:
                params[key] = widget.value()
        return PreprocessingStep(kind=str(kind_combo.currentData()), enabled=True, params=params)

    def _delete_pipeline(self) -> None:
        name = str(self._pipeline_combo.currentData() or "")
        if not name:
            return
        if name == DEFAULT_PIPELINE_NAME:
            QMessageBox.warning(self, "Preprocessing pipelines", "The 'raw' pipeline cannot be deleted.")
            return
        self._store.pop(name, None)
        try:
            write_pipeline_store(self._pipelines_path, self._store)
        except Exception as e:
            ephyr_logger().debug(str(e))
        pos = self._pipeline_combo.currentIndex()
        self._pipeline_combo.removeItem(pos)
        self._pipeline_combo.setCurrentIndex(0)

    def _save_pipeline(self) -> None:
        name = self._name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Preprocessing pipelines", "Pipeline name is required.")
            return
        if name == DEFAULT_PIPELINE_NAME:
            QMessageBox.warning(self, "Preprocessing pipelines", "'raw' is reserved for an empty pipeline.")
            return
        spec = PipelineSpec(
            name=name,
            description=self._description_edit.text().strip(),
            steps=[s.model_copy(deep=True) for s in self._steps],
        )
        self._store[name] = spec
        try:
            write_pipeline_store(self._pipelines_path, self._store)
        except Exception as e:
            ephyr_logger().debug(str(e))
            QMessageBox.warning(self, "Preprocessing pipelines", f"Failed to save pipeline: {e}")
            return
        self._saved_name = name
        self.accept()

    def saved_pipeline_name(self) -> Optional[str]:
        return getattr(self, "_saved_name", None)


class PipelineSelector(QWidget):
    """Combo of saved pipelines plus an inline "Manage..." button."""

    def __init__(self, pipelines_path: Path, selected_name: str = DEFAULT_PIPELINE_NAME, parent=None):
        super().__init__(parent)
        self._pipelines_path = Path(pipelines_path)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._combo = QComboBox()
        self._manage_btn = QPushButton("Manage...")
        layout.addWidget(self._combo, 1)
        layout.addWidget(self._manage_btn)
        self._manage_btn.clicked.connect(self._open_manager)
        self._reload(selected_name)

    def _reload(self, selected_name: str = "") -> None:
        prev = selected_name or self.current_pipeline_name()
        store = read_pipeline_store(self._pipelines_path)
        self._combo.blockSignals(True)
        self._combo.clear()
        for name in sorted(store.keys()):
            self._combo.addItem(name, name)
        idx = self._combo.findData(prev)
        self._combo.setCurrentIndex(max(0, idx))
        self._combo.blockSignals(False)

    def _open_manager(self) -> None:
        dialog = PipelineBuilderDialog(self._pipelines_path, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._reload(dialog.saved_pipeline_name() or self.current_pipeline_name())
        else:
            self._reload(self.current_pipeline_name())

    def current_pipeline_name(self) -> str:
        data = self._combo.currentData()
        return str(data) if data is not None else DEFAULT_PIPELINE_NAME

    def set_current_pipeline(self, name: str) -> None:
        idx = self._combo.findData(name)
        if idx >= 0:
            self._combo.setCurrentIndex(idx)


__all__ = [
    "FilterEditor",
    "PipelineBuilderDialog",
    "PipelineSelector",
    "filter_from_spec",
]
