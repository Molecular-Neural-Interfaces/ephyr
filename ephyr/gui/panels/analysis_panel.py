from __future__ import annotations

from pathlib import Path
import inspect
from typing import Dict, List, Optional, Tuple

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QCheckBox,
    QLineEdit,
    QScrollArea,
    QSizePolicy, QToolButton, QStyle,
)

from ephyr import settings
from ephyr.gui.dialogs.loading_dialog import LoadingDialog
from ephyr.logger import ephyr_logger


class AnalysisPanel(QWidget):
    """Add-ons control panel (view/transform/run)."""

    def __init__(self, session_manager, parent=None):
        super().__init__(parent)
        self._session_manager = session_manager
        self._expanded_groups = set()
        self._search_text = ""
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(240)
        self._build_ui()
        self._connect_signals()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(5, 5, 5, 5)
        root.setSpacing(8)

        title = QLabel("Add-ons")
        root.addWidget(title)

        self._search_input = QLineEdit(self)
        self._search_input.setPlaceholderText("Search...")
        root.addWidget(self._search_input)

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._container = QWidget()
        self._container_layout = QVBoxLayout(self._container)
        self._container_layout.setContentsMargins(2, 2, 2, 2)
        self._container_layout.setSpacing(6)
        self._container_layout.addStretch(1)
        self._scroll.setWidget(self._container)
        root.addWidget(self._scroll, 1)

    def _connect_signals(self):
        self._session_manager.session_loaded.connect(self._rebuild_rows)
        self._session_manager.add_ons_changed.connect(self._rebuild_rows)
        self._search_input.textChanged.connect(self._on_search_changed)

    def _on_search_changed(self, text: str):
        self._search_text = (text or "").strip().lower()
        self._rebuild_rows()

    def _clear_rows(self):
        while self._container_layout.count():
            item = self._container_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _rebuild_rows(self, *_args):
        self._clear_rows()
        gui_setup = self._session_manager.gui_setup
        if gui_setup is None:
            self._container_layout.addStretch(1)
            return

        runtime_add_ons = self._session_manager.get_all_add_ons()
        groups = self._group_add_ons(gui_setup.add_ons, runtime_add_ons)
        if not groups:
            empty_label = QLabel("No add-ons match the search" if self._search_text else "No add-ons")
            self._container_layout.addWidget(empty_label)
            self._container_layout.addStretch(1)
            return

        for group_id, group_label, entries in groups:
            self._add_group(group_id, group_label, entries)

        self._container_layout.addStretch(1)

    def _group_add_ons(self, add_on_setups, runtime_add_ons: Dict) -> List[Tuple[str, str, List[Tuple[str, object, object]]]]:
        installed_groups: Dict[str, Tuple[str, List[Tuple[str, object, object]]]] = {}
        dev_entries: List[Tuple[str, object, object]] = []

        for module_name in sorted(add_on_setups.keys()):
            setup = add_on_setups[module_name]
            add_on = runtime_add_ons.get(module_name)
            if self._search_text and self._search_text not in self._entry_label(module_name, add_on).lower():
                continue
            entry = (module_name, setup, add_on)
            if module_name.startswith("dev_"):
                dev_entries.append(entry)
                continue

            distribution_name = getattr(add_on, "_ephyr_distribution_name", None) if add_on else None
            group_label = distribution_name or "Installed add-ons"
            group_id = f"installed:{group_label}"
            if group_id not in installed_groups:
                installed_groups[group_id] = (group_label, [])
            installed_groups[group_id][1].append(entry)

        result: List[Tuple[str, str, List[Tuple[str, object, object]]]] = []
        for group_id, (group_label, entries) in sorted(installed_groups.items(), key=lambda item: item[1][0]):
            result.append((group_id, group_label, entries))
        if dev_entries:
            result.append(("dev", "Development add-ons", dev_entries))
        return result

    def _add_group(self, group_id: str, group_label: str, entries: List[Tuple[str, object, object]]):
        if self._search_text:
            expanded = True
        else:
            expanded = group_id in self._expanded_groups

        group_button = QToolButton(self._container)
        group_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        group_button.setCursor(Qt.CursorShape.PointingHandCursor)
        group_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        # Иконка и текст
        group_button.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        group_button.setText(f"  {group_label} ({len(entries)})")
        group_button.clicked.connect(lambda _checked=False, gid=group_id: self._toggle_group(gid))
        self._container_layout.addWidget(group_button)

        if not expanded:
            return

        for module_name, setup, add_on in entries:
            self._add_entry_row(module_name, setup, add_on)

    def _toggle_group(self, group_id: str):
        if group_id in self._expanded_groups:
            self._expanded_groups.discard(group_id)
        else:
            self._expanded_groups.add(group_id)
        self._rebuild_rows()

    def _entry_label(self, module_name: str, add_on) -> str:
        entry_point_name = getattr(add_on, "_ephyr_entry_point_name", None) if add_on else module_name
        if entry_point_name.startswith("dev_"):
            return entry_point_name[4:]
        return entry_point_name

    def _add_entry_row(self, module_name: str, setup, add_on):
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(18, 2, 2, 2)
        row_layout.setSpacing(6)

        label = QLabel(self._entry_label(module_name, add_on))
        row_layout.addWidget(label, 1)

        view_cb = QCheckBox("View")
        view_supported = bool(add_on and getattr(add_on, "VIEWABLE", False))
        view_cb.setChecked(bool(setup.view_enabled))
        view_cb.setEnabled(view_supported)
        view_cb.toggled.connect(lambda checked, m=module_name: self._session_manager.set_add_on_view_enabled(m, checked))
        row_layout.addWidget(view_cb)

        transform_cb = QCheckBox("Transform")
        transform_supported = bool(add_on and getattr(add_on, "TRANSFORMATION", False))
        transform_cb.setChecked(bool(setup.transform_enabled))
        transform_cb.setEnabled(transform_supported)
        transform_cb.toggled.connect(
            lambda checked, m=module_name: self._session_manager.set_add_on_transform_enabled(m, checked)
        )
        row_layout.addWidget(transform_cb)

        run_btn = QPushButton("Run")
        run_supported = bool(add_on and getattr(add_on, "RUNNABLE", False))
        run_btn.setEnabled(run_supported)
        run_btn.clicked.connect(lambda checked=False, m=module_name: self._run_add_on(m))
        row_layout.addWidget(run_btn)

        self._container_layout.addWidget(row_widget)

    def _parse_progress(self, yielded):
        if isinstance(yielded, str):
            return None, yielded
        if isinstance(yielded, (tuple, list)) and len(yielded) >= 2:
            return yielded[0], str(yielded[1])
        if isinstance(yielded, dict):
            return yielded.get("progress"), str(yielded.get("message", "Running add-on..."))
        return None, str(yielded)

    def _run_add_on(self, module_name: str):
        runtime_add_on = self._session_manager.get_runtime_add_on(module_name)
        if runtime_add_on is None:
            return
        add_ons_data_dir = (
            Path(self._session_manager.ephyr_experiment_folder)
            / settings.ADD_ONS_SUBFOLDER
            / settings.ADD_ONS_DATA_SUBFOLDER
            / module_name
        )
        add_ons_data_dir.mkdir(parents=True, exist_ok=True)

        loading: Optional[LoadingDialog] = None
        try:            
            run_result = runtime_add_on.run(self._session_manager, add_ons_data_dir)
            if inspect.isgenerator(run_result):
                for yielded in run_result:
                    progress, message = self._parse_progress(yielded)
                    if loading is None:
                        loading = LoadingDialog("Running add-on...", self)
                        loading.show()
                        loading.raise_()
                        loading.activateWindow()
                    loading.set_message(message)
                    loading.set_progress(progress)
                    QApplication.processEvents()
            self._session_manager.notify_add_on_run(module_name)
        except Exception as e:
            ephyr_logger().error(str(e))
        finally:
            if loading is not None:
                loading.close()
