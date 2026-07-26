from __future__ import annotations

import keyword
from dataclasses import dataclass
from pathlib import Path
from typing import List

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from weegit import settings


@dataclass
class _AuthorInput:
    row_widget: QWidget
    name_input: QLineEdit
    email_input: QLineEdit
    remove_button: QPushButton


class AddOnDevelopmentDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._authors: List[_AuthorInput] = []
        self._build_ui()

    def _build_ui(self):
        self.setWindowTitle("Create add-on template")
        self.resize(760, 520)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        root.addLayout(form)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("my_add_on")
        form.addRow("[project] name:", self.name_input)

        self.description_input = QLineEdit()
        self.description_input.setPlaceholderText("Short add-on description")
        form.addRow("[project] description:", self.description_input)

        self.authors_container = QWidget()
        self.authors_layout = QVBoxLayout(self.authors_container)
        self.authors_layout.setContentsMargins(0, 0, 0, 0)
        self.authors_layout.setSpacing(6)
        form.addRow("authors:", self.authors_container)

        self.btn_add_author = QPushButton("Add author")
        self.btn_add_author.clicked.connect(self._on_add_author_clicked)
        root.addWidget(self.btn_add_author, alignment=Qt.AlignmentFlag.AlignLeft)

        options_row = QHBoxLayout()
        options_row.setSpacing(16)
        self.cb_viewable = QCheckBox("viewable")
        self.cb_transformation = QCheckBox("transformation")
        self.cb_runnable = QCheckBox("runnable")
        self.cb_viewable.setChecked(True)
        self.cb_transformation.setChecked(False)
        self.cb_runnable.setChecked(True)
        options_row.addWidget(self.cb_viewable)
        options_row.addWidget(self.cb_transformation)
        options_row.addWidget(self.cb_runnable)
        options_row.addStretch(1)
        root.addLayout(options_row)

        repo_root = settings.ADD_ONS_REPOSITORY[:-4] if settings.ADD_ONS_REPOSITORY.endswith(".git") else settings.ADD_ONS_REPOSITORY
        link_label = QLabel(f'Guide: <a href="{repo_root}">{repo_root}</a>')
        link_label.setOpenExternalLinks(True)
        link_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        root.addWidget(link_label, alignment=Qt.AlignmentFlag.AlignLeft)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        btn_cancel = QPushButton("Cancel")
        btn_generate = QPushButton("Generate template")
        buttons.addWidget(btn_cancel)
        buttons.addWidget(btn_generate)
        root.addLayout(buttons)

        btn_cancel.clicked.connect(self.reject)
        btn_generate.clicked.connect(self._on_generate_clicked)

        self._add_author_row()

    def _add_author_row(self, name: str = "", email: str = ""):
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)

        name_input = QLineEdit()
        name_input.setPlaceholderText("Author name")
        name_input.setText(name)
        email_input = QLineEdit()
        email_input.setPlaceholderText("Email (optional)")
        email_input.setText(email)
        remove_button = QPushButton("Remove")

        row_layout.addWidget(QLabel("name:"))
        row_layout.addWidget(name_input, 2)
        row_layout.addWidget(QLabel("email:"))
        row_layout.addWidget(email_input, 2)
        row_layout.addWidget(remove_button)

        author = _AuthorInput(
            row_widget=row_widget,
            name_input=name_input,
            email_input=email_input,
            remove_button=remove_button,
        )
        self._authors.append(author)
        self.authors_layout.addWidget(row_widget)
        remove_button.clicked.connect(lambda _checked=False, a=author: self._remove_author_row(a))
        self._refresh_remove_buttons_state()

    def _remove_author_row(self, author: _AuthorInput):
        if author not in self._authors:
            return
        self._authors.remove(author)
        self.authors_layout.removeWidget(author.row_widget)
        author.row_widget.deleteLater()
        self._refresh_remove_buttons_state()

    def _refresh_remove_buttons_state(self):
        can_remove = len(self._authors) > 1
        for author in self._authors:
            author.remove_button.setEnabled(can_remove)

    def _on_add_author_clicked(self):
        self._add_author_row()

    @staticmethod
    def _escape_toml_string(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").strip()

    def _collect_authors(self) -> List[dict]:
        result: List[dict] = []
        for author in self._authors:
            name = author.name_input.text().strip()
            email = author.email_input.text().strip()
            if not name and not email:
                continue
            row = {"name": name}
            if email:
                row["email"] = email
            result.append(row)
        return result

    def _render_pyproject(self, template_toml: str, project_name: str, description: str, authors: List[dict]) -> str:
        escaped_name = self._escape_toml_string(project_name)
        escaped_description = self._escape_toml_string(description)
        if authors:
            author_rows = []
            for author in authors:
                escaped_author_name = self._escape_toml_string(author.get("name", ""))
                escaped_author_email = self._escape_toml_string(author.get("email", ""))
                if escaped_author_email:
                    author_rows.append(f'    {{name = "{escaped_author_name}", email = "{escaped_author_email}"}},')
                else:
                    author_rows.append(f'    {{name = "{escaped_author_name}"}},')
            authors_block = "\n".join(author_rows)
        else:
            authors_block = "    {name = \"Unknown\"},"
        return template_toml.format(
            project_name=escaped_name,
            project_description=escaped_description,
            authors_block=authors_block,
        )

    def _render_example_py(self, template_py: str) -> str:
        transform_block = ""
        view_block = ""
        run_block = ""

        if self.cb_transformation.isChecked():
            transform_block = """
    def transform(self, channel_data: np.ndarray, sample_rate: float):
        if not self.TRANSFORMATION:
            return channel_data

        # TODO: Implement transformation logic.
        return channel_data

    def applicable(self, channel_idx: int) -> bool:
        # TODO: Return False for channels this add-on should skip.
        _ = channel_idx
        return True
"""

        if self.cb_viewable.isChecked():
            view_block = """
    def view(
            self,
            add_on_data_dir: Path,
            processed_data: Dict[int, np.ndarray[np.float64]],
            voltage_scale: float,
            start_point: int,
            duration_ms: float,
            start_time_ms: float,
            end_time_ms: float,
            sample_rate: float,
            axis_duration_ms: float,
            sweep_idx: int,
            visible_channel_indexes: List[int],
            channel_names: List[str],
            visible_events: List[Any],
            visible_periods: List[Any],
            channel_groups: List[Any],
            channels_setup: Dict[int, Any],
            painter: QPainter,
            signal_widget: QWidget,
            channel_rects: List[Tuple[int, QRect]],
            signal_width: int,
            draw_area_height: int,
            bg_color: QColor,
            grid_color: QColor,
            signal_color: QColor,
            text_color: QColor,
            axis_color: QColor,
    ):
        if not self.VIEWABLE:
            return

        # TODO: Draw custom entities on the signal panel.
        return
"""

        if self.cb_runnable.isChecked():
            run_block = """
    def run(self, session_manager, add_on_data_dir):
        if not self.RUNNABLE:
            return

        add_on_data_dir = Path(add_on_data_dir)
        add_on_data_dir.mkdir(parents=True, exist_ok=True)
        # TODO: Add your computation here.
        yield {"progress": 100, "message": "Example add-on finished"}
"""

        return template_py.format(
            transformation_enabled=str(self.cb_transformation.isChecked()),
            viewable_enabled=str(self.cb_viewable.isChecked()),
            runnable_enabled=str(self.cb_runnable.isChecked()),
            transform_block=transform_block.strip("\n"),
            view_block=view_block.strip("\n"),
            run_block=run_block.strip("\n"),
        )

    def _read_templates(self) -> tuple[str, str]:
        template_dir = Path(__file__).resolve().parents[2] / "core" / "add_ons" / "template"
        py_template = (template_dir / "template.py").read_text(encoding="utf-8")
        toml_template = (template_dir / "template.toml").read_text(encoding="utf-8")
        return py_template, toml_template

    def _write_output_files(self, target_dir: Path, pyproject_content: str, example_content: str, project_name: str):
        package_dir = target_dir / "weegit_add_ons" / project_name
        readme_content = (
            f"# {project_name}\n\n"
            "Generated add-on template.\n\n"
            "## Files\n"
            f"- `weegit_add_ons/{project_name}/entry_point.py`: add-on implementation\n"
            f"- `weegit_add_ons/{project_name}/__init__.py`: package marker for helpers\n"
            "- `pyproject.toml`: package metadata and entry point\n"
        )
        target_dir.mkdir(parents=True, exist_ok=True)
        package_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "README.md").write_text(readme_content, encoding="utf-8")
        (target_dir / "pyproject.toml").write_text(pyproject_content, encoding="utf-8")
        (package_dir / "__init__.py").write_text("", encoding="utf-8")
        (package_dir / "entry_point.py").write_text(example_content, encoding="utf-8")

    def _on_generate_clicked(self):
        project_name = self.name_input.text().strip()
        description = self.description_input.text().strip()
        if not project_name:
            QMessageBox.warning(self, "Create add-on template", "Field [project] name is required.")
            return
        if not project_name.isidentifier() or keyword.iskeyword(project_name):
            QMessageBox.warning(
                self,
                "Create add-on template",
                "Field [project] name must be a valid Python package name, for example my_add_on.",
            )
            return
        if not description:
            QMessageBox.warning(self, "Create add-on template", "Field [project] description is required.")
            return

        authors = self._collect_authors()
        try:
            py_template, toml_template = self._read_templates()
            pyproject_content = self._render_pyproject(toml_template, project_name, description, authors)
            example_content = self._render_example_py(py_template)
            target_dir = Path.cwd() / "add_on_development"

            existing_paths = [
                target_dir / "README.md",
                target_dir / "pyproject.toml",
                target_dir / "weegit_add_ons" / project_name / "__init__.py",
                target_dir / "weegit_add_ons" / project_name / "entry_point.py",
            ]
            existing_files = [str(path.relative_to(target_dir)) for path in existing_paths if path.exists()]
            if existing_files:
                reply = QMessageBox.question(
                    self,
                    "Overwrite files",
                    "Files already exist in add_on_development:\n"
                    + "\n".join(f"- {name}" for name in existing_files)
                    + "\n\nOverwrite them?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return

            self._write_output_files(target_dir, pyproject_content, example_content, project_name)
            QMessageBox.information(
                self,
                "Create add-on template",
                f"Template generated in:\n{target_dir}",
            )
            self.accept()
        except Exception as exc:
            QMessageBox.warning(self, "Create add-on template", f"Failed to generate template: {exc}")
