"""Events detection add-on.

Runnable. Merges the analog (paired-impulse) and digital (per-channel peak)
detection strategies into a single add-on with a configurable preprocessing
pipeline and channel selection. Detected events are appended to the session
vocabulary; if more than 1000 events are found, the user is asked to confirm
before adding them (to avoid freezing the interface).
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from scipy.signal import find_peaks

from weegit.core.add_ons.base import BaseAddOn
from weegit.core.add_ons import (
    PipelineSelector,
    apply_preprocessing_pipeline,
    read_pipeline_store,
)
from weegit.logger import weegit_logger

from weegit_add_ons.labeling_utils._common import LabelingUtilsBase

CONFIRM_THRESHOLD = 1000


class EventsDetectionAddOn(LabelingUtilsBase, BaseAddOn):
    TRANSFORMATION = False
    VIEWABLE = False
    RUNNABLE = True

    def _ask_parameters(self, session_manager, header, add_on_data_dir: Path) -> Optional[dict]:
        groups = self.ensure_non_aux_groups(session_manager, "Events detection")
        if groups is None:
            return None
        common = self.load_common(add_on_data_dir)
        params = self.load_params(add_on_data_dir)

        dialog = QDialog()
        dialog.setWindowTitle("Events detection")
        dialog.setMinimumWidth(540)
        dialog.setFixedHeight(600)
        outer = QVBoxLayout(dialog)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_widget = QWidget()
        form = QFormLayout(scroll_widget)

        group_combo, channels_list = self.build_group_channel_selector(
            form,
            groups,
            header,
            preferred_group_idx=int(common.get("group_idx", 0)),
            preferred_channels=common.get("channel_indexes", []),
        )

        pipeline_selector = PipelineSelector(
            self.pipelines_path(add_on_data_dir),
            selected_name=str(params.get("pipeline", "raw")),
        )
        form.addRow("Preprocessing pipeline:", pipeline_selector)

        mode_combo = QComboBox()
        mode_combo.addItem("Digital (per-channel peaks)", "digital")
        mode_combo.addItem("Analog (paired impulses)", "analog")
        idx = mode_combo.findData(str(params.get("mode", "digital")))
        mode_combo.setCurrentIndex(max(0, idx))
        form.addRow("Detection mode:", mode_combo)

        polarity_combo = QComboBox()
        polarity_combo.addItem("Upward", "up")
        polarity_combo.addItem("Downward", "down")
        idx = polarity_combo.findData(str(params.get("polarity", "up")))
        polarity_combo.setCurrentIndex(max(0, idx))
        form.addRow("Polarity:", polarity_combo)

        name_edit = QLineEdit(str(params.get("event_name", "")))
        form.addRow("Event name:", name_edit)

        height_spin = QDoubleSpinBox()
        height_spin.setDecimals(6)
        height_spin.setRange(0.0, 1e9)
        height_spin.setValue(float(params.get("height", 50.0)))
        form.addRow("Height (threshold):", height_spin)

        distance_spin = QDoubleSpinBox()
        distance_spin.setDecimals(3)
        distance_spin.setRange(0.0, 1e9)
        distance_spin.setValue(float(params.get("distance_ms", 500.0)))
        form.addRow("Min distance (ms):", distance_spin)

        stim_spin = QDoubleSpinBox()
        stim_spin.setDecimals(3)
        stim_spin.setRange(-1e6, 1e6)
        stim_spin.setValue(float(params.get("stim_offset_ms", 0.0)))
        form.addRow("Analog stim offset (ms):", stim_spin)

        scroll_area.setWidget(scroll_widget)
        outer.addWidget(scroll_area)
        actions = QHBoxLayout()
        btn_cancel = QPushButton("Cancel")
        btn_run = QPushButton("Run")
        actions.addStretch(1)
        actions.addWidget(btn_cancel)
        actions.addWidget(btn_run)
        outer.addLayout(actions)
        btn_cancel.clicked.connect(dialog.reject)
        btn_run.clicked.connect(dialog.accept)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None

        channels = self.selected_channels(channels_list)
        if not channels:
            QMessageBox.warning(dialog, "Events detection", "Select at least one channel.")
            return None
        event_name = name_edit.text().strip()
        if not event_name:
            QMessageBox.warning(dialog, "Events detection", "Event name must not be empty.")
            return None
        existing = {entry.name for entry in (session_manager.events_vocabulary or {}).values()}
        if event_name in existing:
            QMessageBox.warning(dialog, "Events detection", "Event name must be unique.")
            return None

        self.save_common(
            add_on_data_dir,
            {"group_idx": int(group_combo.currentData()), "channel_indexes": channels},
        )
        self.save_params(
            add_on_data_dir,
            {
                "pipeline": pipeline_selector.current_pipeline_name(),
                "mode": str(mode_combo.currentData()),
                "polarity": str(polarity_combo.currentData()),
                "event_name": event_name,
                "height": float(height_spin.value()),
                "distance_ms": float(distance_spin.value()),
                "stim_offset_ms": float(stim_spin.value()),
            },
        )
        return {
            "channels": channels,
            "pipeline": pipeline_selector.current_pipeline_name(),
            "mode": str(mode_combo.currentData()),
            "polarity": str(polarity_combo.currentData()),
            "event_name": event_name,
            "height": float(height_spin.value()),
            "distance_ms": float(distance_spin.value()),
            "stim_offset_ms": float(stim_spin.value()),
        }

    def run(self, session_manager, add_on_data_dir):
        header = session_manager.header
        add_on_data_dir = Path(add_on_data_dir)
        params = self._ask_parameters(session_manager, header, add_on_data_dir)
        if params is None:
            return

        total_sweeps = int(header.number_of_sweeps)
        if total_sweeps <= 0:
            yield {"progress": 100, "message": "No sweeps to process"}
            return

        sample_rate = float(header.sample_rate)
        channels = params["channels"]
        pipeline = read_pipeline_store(self.pipelines_path(add_on_data_dir)).get(params["pipeline"])
        downward = params["polarity"] == "down"
        analog_mode = params["mode"] == "analog"
        distance_samples = max(1, int((params["distance_ms"] * sample_rate) / 1000.0)) if params["distance_ms"] > 0 else 1

        detected: List[Tuple[int, float]] = []
        for sweep_idx in range(total_sweeps):
            sweep_points = int(header.number_of_points_per_sweep[sweep_idx])
            yield {
                "progress": int((sweep_idx / total_sweeps) * 90),
                "message": f"Preprocessing pipeline '{params['pipeline']}' on sweep {sweep_idx + 1}/{total_sweeps}",
            }
            matrix = self.channel_matrix_from_session(
                session_manager, channels, sweep_idx, 0, sweep_points, sample_rate
            )
            processed = apply_preprocessing_pipeline(matrix, sample_rate, pipeline)
            processed = np.asarray(processed, dtype=np.float64)

            for row_idx in range(processed.shape[0]):
                signal = processed[row_idx]
                search_signal = -signal if downward else signal
                try:
                    if analog_mode:
                        peaks, _props = find_peaks(search_signal, height=params["height"])
                        peaks = peaks[0:-1:2]
                    else:
                        peaks, _props = find_peaks(search_signal, height=params["height"], distance=distance_samples)
                except Exception as e:
                    weegit_logger().debug(str(e))
                    continue
                for peak_sample in peaks:
                    time_ms = (float(peak_sample) * 1000.0) / sample_rate
                    if analog_mode:
                        time_ms += float(params["stim_offset_ms"])
                    detected.append((sweep_idx, float(time_ms)))
            yield {
                "progress": int(((sweep_idx + 1) / total_sweeps) * 90),
                "message": f"Sweep {sweep_idx + 1}/{total_sweeps}: {len(detected)} events so far",
            }

        if not detected:
            QMessageBox.information(None, "Events detection", "No events were detected. Vocabulary was not created.")
            return

        n_detected = len(detected)
        if n_detected > CONFIRM_THRESHOLD:
            answer = QMessageBox.question(
                None,
                "Events detection",
                f"Detected {n_detected} events. The interface may freeze. "
                "Are you sure you want to continue with these detection parameters?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                yield {"progress": 100, "message": f"Cancelled: {n_detected} events not added"}
                return

        yield {"progress": 95, "message": f"Adding {n_detected} events..."}
        try:
            event_name_id = session_manager.add_event_vocabulary(params["event_name"])
            events_specs = [(event_name_id, sweep_idx, time_ms) for sweep_idx, time_ms in detected]
            session_manager.add_events(events_specs)
        except Exception as e:
            weegit_logger().debug(str(e))
            yield {"progress": 100, "message": "Failed to add events"}
            return
        yield {"progress": 100, "message": f"Added {n_detected} '{params['event_name']}' events"}
