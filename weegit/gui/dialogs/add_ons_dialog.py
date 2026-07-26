from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib
import html
import zipfile

try:
    import tomllib
except ImportError:
    import tomli as tomllib

from importlib.metadata import PackageNotFoundError, version
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional
from urllib.request import urlopen

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
)

from weegit import settings
from weegit.gui.dialogs.loading_dialog import LoadingDialog
from weegit.gui.qt_weegit_session_manager_wrapper import QtWeegitSessionManagerWrapper
from weegit.logger import weegit_logger


@dataclass
class _IndexItem:
    label: str
    module_name: str
    keywords: List[str]
    path: str


class AddOnsDialog(QDialog):
    def __init__(self, session_manager: QtWeegitSessionManagerWrapper, parent=None):
        super().__init__(parent)
        self._session_manager = session_manager
        self._index_items: List[_IndexItem] = []
        self._selected_module_name: Optional[str] = None
        self._is_populating_table = False
        self._pyproject_cache: Dict[str, Dict[str, object]] = {}

        self.setWindowTitle("Add-ons")
        self.resize(980, 620)
        self._build_ui()
        self._load_index_and_refresh(parent)

    def _build_ui(self):
        root_layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        root_layout.addWidget(splitter)

        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["", "Name"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 28)
        left_layout.addWidget(self.table)

        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self.meta_form = QFormLayout()
        self.meta_form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.meta_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.meta_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.meta_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.lbl_module_name = QLabel("-")
        self.lbl_version = QLabel("-")
        self.lbl_description = QLabel("-")
        self.lbl_author = QLabel("-")
        self.lbl_keywords = QLabel("-")
        self.lbl_links = QLabel("-")
        for label in (
            self.lbl_module_name,
            self.lbl_version,
            self.lbl_description,
            self.lbl_keywords,
            self.lbl_author,
            self.lbl_links,
        ):
            label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            label.setWordWrap(True)
            label.setTextFormat(Qt.TextFormat.RichText)
            label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self.lbl_author.setOpenExternalLinks(True)
        self.lbl_links.setOpenExternalLinks(True)

        self.meta_form.addRow("Module name:", self.lbl_module_name)
        self.meta_form.addRow("Version:", self.lbl_version)
        self.meta_form.addRow("Author:", self.lbl_author)
        self.meta_form.addRow("Keywords:", self.lbl_keywords)
        self.meta_form.addRow("Links:", self.lbl_links)
        self.meta_form.addRow("Description:", self.lbl_description)
        right_layout.addLayout(self.meta_form)
        right_layout.addStretch(1)

        btn_row = QHBoxLayout()
        self.btn_install_toggle = QPushButton("Install")
        self.btn_update = QPushButton("Update")
        self.btn_update.setVisible(False)
        btn_row.addStretch(1)
        btn_row.addWidget(self.btn_install_toggle)
        btn_row.addWidget(self.btn_update)
        right_layout.addLayout(btn_row)

        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        self.table.itemSelectionChanged.connect(self._on_table_selection_changed)
        self.btn_install_toggle.clicked.connect(self._on_install_toggle_clicked)
        self.btn_update.clicked.connect(self._on_update_clicked)

    def _candidate_installed_names(self, item: _IndexItem) -> tuple[List[str], List[str]]:
        entry_point_names = [item.module_name]
        distribution_names = [item.module_name]
        try:
            pyproject = self._fetch_pyproject_info(item.path)
            project_name = str(pyproject.get("project_name", "") or "").strip()
            if project_name:
                distribution_names.insert(0, project_name)
            for entry_point_name in pyproject.get("entry_point_names", []) or []:
                entry_point_name = str(entry_point_name).strip()
                if entry_point_name and entry_point_name not in entry_point_names:
                    entry_point_names.append(entry_point_name)
        except Exception:
            pass
        return entry_point_names, distribution_names

    def _is_installed(self, item: _IndexItem) -> bool:
        entry_point_names, distribution_names = self._candidate_installed_names(item)
        if any(self._session_manager.has_runtime_add_on(name) for name in entry_point_names):
            return True
        if any(self._session_manager.has_runtime_distribution(name) for name in distribution_names):
            return True
        for distribution_name in distribution_names:
            try:
                version(distribution_name)
                return True
            except PackageNotFoundError:
                continue
        return False

    def _load_index(self) -> List[_IndexItem]:
        with urlopen(settings.INDEX_RAW_URL, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
        items: List[_IndexItem] = []
        for row in payload:
            items.append(
                _IndexItem(
                    label=str(row.get("label", "")).strip(),
                    module_name=str(row.get("module_name", "")).strip(),
                    keywords=[str(x) for x in (row.get("keywords") or [])],
                    path=str(row.get("path", "")).strip(),
                )
            )
        return [x for x in items if x.module_name and x.path]

    def _load_index_and_refresh(self, parent):
        loading = LoadingDialog("Loading add-ons information...", parent)
        loading.show()
        loading.raise_()
        loading.activateWindow()
        QApplication.processEvents()
        try:
            self._session_manager.refresh_runtime_add_ons()
            try:
                self._index_items = self._load_index()
            except Exception as exc:
                QMessageBox.warning(self, "Add-ons", f"Failed to load index.json: {exc}")
                self._index_items = []
            self._reload_table()
        finally:
            loading.close()

    def _reload_table(self):
        self._is_populating_table = True
        self.table.setRowCount(0)
        for row_idx, item in enumerate(self._index_items):
            self.table.insertRow(row_idx)

            status_item = QTableWidgetItem()
            status_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            status_item.setCheckState(Qt.CheckState.Checked if self._is_installed(item) else Qt.CheckState.Unchecked)
            status_item.setData(Qt.ItemDataRole.UserRole, item.module_name)
            self.table.setItem(row_idx, 0, status_item)

            name_item = QTableWidgetItem(item.label or item.module_name)
            name_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.table.setItem(row_idx, 1, name_item)
        self._is_populating_table = False

        if self._selected_module_name:
            self._select_row_by_module(self._selected_module_name)
            self._update_right_panel()
        elif self.table.rowCount() > 0:
            self.table.selectRow(0)
        else:
            self._set_no_selection_state()

    def _select_row_by_module(self, module_name: str):
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == module_name:
                self.table.selectRow(row)
                return

    def _set_no_selection_state(self):
        self._selected_module_name = None
        self.lbl_module_name.setText("-")
        self.lbl_version.setText("-")
        self.lbl_description.setText("Select add-on")
        self.lbl_author.setText("-")
        self.lbl_keywords.setText("-")
        self.lbl_links.setText("-")
        self.btn_install_toggle.setEnabled(False)
        self.btn_update.setVisible(False)

    def _selected_index_item(self) -> Optional[_IndexItem]:
        if self._selected_module_name is None:
            return None
        for item in self._index_items:
            if item.module_name == self._selected_module_name:
                return item
        return None

    @staticmethod
    def _repository_web_base_url() -> str:
        repo_url = settings.ADD_ONS_REPOSITORY.strip()
        if repo_url.endswith(".git"):
            return repo_url[:-4]
        return repo_url

    @staticmethod
    def _format_authors_html(authors: object) -> str:
        if not isinstance(authors, list):
            return "-"
        rendered: List[str] = []
        for author in authors:
            if not isinstance(author, dict):
                continue
            name = str(author.get("name", "") or "").strip()
            email = str(author.get("email", "") or "").strip()
            if not name and not email:
                continue

            if name:
                safe_name = html.escape(name)
                name_html = safe_name
            else:
                name_html = "Unknown author"

            if email:
                safe_email = html.escape(email)
                rendered.append(f"{name_html} ({safe_email})")
            else:
                rendered.append(name_html)

        return ", ".join(rendered) if rendered else "-"

    @staticmethod
    def _format_links_html(project_urls: object, add_on_path: str) -> str:
        links: List[str] = []
        if isinstance(project_urls, dict):
            for raw_title, raw_url in project_urls.items():
                title = str(raw_title or "").strip()
                url = str(raw_url or "").strip()
                if not title or not url:
                    continue
                safe_title = html.escape(title)
                safe_url = html.escape(url, quote=True)
                links.append(f'<a href="{safe_url}">{safe_title}</a>')

        homepage_url = f"{AddOnsDialog._repository_web_base_url()}/tree/main/{add_on_path.strip('/')}"
        safe_homepage = html.escape(homepage_url, quote=True)
        links.append(f'<a href="{safe_homepage}">Add-on homepage</a>')
        return "<br>".join(links)

    def _fetch_pyproject_info(self, add_on_path: str) -> Dict[str, object]:
        cache_key = add_on_path.strip().strip("/")
        if cache_key in self._pyproject_cache:
            return self._pyproject_cache[cache_key]
        pyproject_url = f"{settings.REPO_RAW_BASE}/{add_on_path}/pyproject.toml"
        request = urllib.request.Request(pyproject_url)
        request.add_header('Pragma', 'no-cache')
        request.add_header('Cache-Control', 'no-cache')
        with urlopen(request, timeout=10) as response:
            parsed = tomllib.loads(response.read().decode("utf-8"))
        project = parsed.get("project", {})
        project_name = str(project.get("name", "") or "")
        description = str(project.get("description", "") or "")
        version = str(project.get("version", "") or "")
        authors = project.get("authors") or []
        project_urls = project.get("urls") or {}
        entry_points = project.get("entry-points", {}) or {}
        weegit_entry_points = entry_points.get("weegit.add_ons", {}) or {}
        result = {
            "project_name": project_name,
            "description": description,
            "version": version,
            "author": self._format_authors_html(authors),
            "links": self._format_links_html(project_urls, add_on_path),
            "entry_point_names": list(weegit_entry_points.keys()),
        }
        self._pyproject_cache[cache_key] = result
        return result

    def _update_right_panel(self):
        item = self._selected_index_item()
        if item is None:
            self._set_no_selection_state()
            return

        self.lbl_module_name.setText(item.module_name)
        self.lbl_keywords.setText(", ".join(item.keywords) if item.keywords else "-")
        self.btn_install_toggle.setEnabled(True)

        try:
            pyproject = self._fetch_pyproject_info(item.path)
            self.lbl_description.setText(pyproject["description"] or "-")
            self.lbl_version.setText(pyproject["version"] or "-")
            self.lbl_author.setText(pyproject["author"])
            self.lbl_links.setText(pyproject["links"])
        except Exception as exc:
            self.lbl_version.setText("-")
            self.lbl_description.setText("-")
            self.lbl_author.setText("-")
            self.lbl_links.setText("-")
            QMessageBox.warning(self, "Add-ons", f"Failed to load pyproject.toml: {exc}")

        installed = self._is_installed(item)
        installed_version = "-"
        if installed:
            _entry_point_names, distribution_names = self._candidate_installed_names(item)
            for distribution_name in distribution_names:
                try:
                    installed_version = version(distribution_name)
                    break
                except PackageNotFoundError:
                    continue

        github_version = self.lbl_version.text().strip() or "-"
        self.lbl_version.setText(f"{github_version} (installed version: {installed_version})")
        self.btn_install_toggle.setText("Uninstall" if installed else "Install")
        self.btn_update.setVisible(installed)

    def _on_table_selection_changed(self):
        if self._is_populating_table:
            return
        selected = self.table.selectedItems()
        if not selected:
            self._set_no_selection_state()
            return
        row = selected[0].row()
        id_item = self.table.item(row, 0)
        if not id_item:
            self._set_no_selection_state()
            return
        self._selected_module_name = id_item.data(Qt.ItemDataRole.UserRole)
        self._update_right_panel()

    @staticmethod
    def _add_ons_repo_archive_zip_url() -> str:
        """HTTPS zipball URL; avoids pip's git+... scheme (requires git executable)."""
        repo = settings.ADD_ONS_REPOSITORY.strip().rstrip("/")
        if repo.endswith(".git"):
            repo = repo[:-4]
        branch = settings.REPO_RAW_BASE.rstrip("/").rsplit("/", 1)[-1]
        return f"{repo}/archive/refs/heads/{branch}.zip"

    def _install_add_on_with_pip(self, add_on_path: str, *, upgrade: bool, title: str) -> None:
        add_on_path_norm = add_on_path.strip().strip("/")
        archive_url = self._add_ons_repo_archive_zip_url()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            zip_path = tmp_path / "addons-repo.zip"
            with urlopen(archive_url, timeout=120) as response:
                zip_path.write_bytes(response.read())
            extract_root = tmp_path / "extracted"
            extract_root.mkdir()
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(extract_root)
            top_levels = [p for p in extract_root.iterdir() if p.is_dir()]
            if len(top_levels) != 1:
                raise RuntimeError(
                    f"Unexpected add-ons archive layout (expected one top-level folder): {list(extract_root.iterdir())}"
                )
            package_dir = top_levels[0] / add_on_path_norm
            if not package_dir.is_dir():
                raise RuntimeError(f"Add-on path not found in repository archive: {add_on_path_norm}")
            pip_args: List[str] = ["install"]
            if upgrade:
                pip_args.append("-U")
            pip_args.append(str(package_dir))
            self._run_pip(pip_args, title)

    def _run_pip(self, args: List[str], title: str):
        loading = LoadingDialog(title, self)
        loading.show()
        loading.raise_()
        loading.activateWindow()
        QApplication.processEvents()
        pip_cmd = self._resolve_pip_command()
        pip_env = self._pip_env()
        
        process = subprocess.run(
            [*pip_cmd, *args],
            capture_output=True,
            text=True,
            check=False,
            env=pip_env,
        )
        if process.stdout:
            weegit_logger().info(process.stdout)
        if process.stderr: 
            weegit_logger().warning(process.stderr)
        loading.close()
        if process.returncode != 0:
            details = (process.stderr or process.stdout or "Unknown error").strip()
            raise RuntimeError(details)

    def _on_install_toggle_clicked(self):
        item = self._selected_index_item()
        if item is None:
            return
        try:
            installed = self._is_installed(item)
            if installed:
                _entry_point_names, distribution_names = self._candidate_installed_names(item)
                distribution_name = next(
                    (
                        name for name in distribution_names
                        if self._session_manager.has_runtime_distribution(name)
                    ),
                    distribution_names[0],
                )
                self._run_pip(["uninstall", "-y", distribution_name], "Uninstalling add-on...")
                self._session_manager.pop_add_on(item.module_name)
                add_on_data_dir = (
                    Path(self._session_manager.weegit_experiment_folder)
                    / settings.ADD_ONS_SUBFOLDER
                    / settings.ADD_ONS_DATA_SUBFOLDER
                    / item.module_name
                )
                if add_on_data_dir.exists():
                    shutil.rmtree(add_on_data_dir)
            else:
                self._install_add_on_with_pip(item.path, upgrade=False, title="Package installation in progress")
            self._session_manager.refresh_runtime_add_ons()
            if not installed:
                _entry_point_names, distribution_names = self._candidate_installed_names(item)
                module_names = []
                for distribution_name in distribution_names:
                    module_names = self._session_manager.runtime_add_on_names_for_distribution(distribution_name)
                    if module_names:
                        break
                if not module_names and self._session_manager.has_runtime_add_on(item.module_name):
                    module_names = [item.module_name]
                for module_name in module_names:
                    self._session_manager.set_add_on(module_name, view_enabled=True, transform_enabled=True)
            self._reload_table()
        except Exception as exc:
            QMessageBox.warning(self, "Add-ons", f"Operation failed: {exc}")

    def _on_update_clicked(self):
        item = self._selected_index_item()
        if item is None:
            return
        try:
            self._install_add_on_with_pip(item.path, upgrade=True, title="Updating add-on...")
            self._session_manager.refresh_runtime_add_ons()
            self._reload_table()
        except Exception as exc:
            QMessageBox.warning(self, "Add-ons", f"Update failed: {exc}")

    def _ensure_pip(self):
        """Ensure pip is available for current interpreter."""
        pip_env = self._pip_env()
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "--version"],
                check=True,
                capture_output=True,
                text=True,
                env=pip_env,
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            subprocess.run(
                [sys.executable, "-m", "ensurepip", "--upgrade"],
                check=True,
                env=pip_env,
            )
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "--upgrade", "pip"],
                check=True,
                env=pip_env,
            )

    def _pip_env(self) -> Dict[str, str]:
        # GUI/IDE launchers may set PYTHONHOME/PYTHONPATH that break `-m pip`.
        pip_env = dict(os.environ)
        pip_env.pop("PYTHONHOME", None)
        pip_env.pop("PYTHONPATH", None)
        return pip_env

    def _resolve_pip_command(self) -> List[str]:
        self._ensure_pip()
        pip_env = self._pip_env()
        cmd = [sys.executable, "-m", "pip"]
        probe = subprocess.run(
            [*cmd, "--version"],
            capture_output=True,
            text=True,
            check=False,
            env=pip_env,
        )
        if probe.returncode == 0 and not probe.stderr:
            return cmd

        pip_exe = Path(sys.executable).with_name("pip.exe")
        if pip_exe.exists():
            return [str(pip_exe)]

        raise RuntimeError((probe.stderr or probe.stdout or "pip is unavailable").strip())
