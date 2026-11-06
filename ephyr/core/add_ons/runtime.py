# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

"""Locate the Python environment Ephyr was launched from.

A PyInstaller build sets ``sys.executable`` to the bundled application. Running
that file with ``-m pip`` opens another copy of Ephyr and never returns.
Add-ons still have to land in the environment that is actually running:

- a virtualenv install goes into that virtualenv
- a global install goes into that interpreter
- a standalone build has no separate Python. pip runs inside the application
  and writes packages next to the executable, so the user does not install Python
"""

from __future__ import annotations

import io
import os
import re
import shutil
import site
import subprocess
import sys
import urllib.parse
from pathlib import Path
from typing import Optional, Sequence


_DIST_NAME_RE = re.compile(r"[-_.]+")
_LIBRARY_PATH_KEYS = (
    "LD_LIBRARY_PATH",
    "DYLD_LIBRARY_PATH",
    "DYLD_FRAMEWORK_PATH",
    "DYLD_FALLBACK_LIBRARY_PATH",
)
_PIP_RETARGET_KEYS = ("PIP_TARGET", "PIP_PREFIX", "PIP_USER", "PYTHONUSERBASE")


def is_frozen_runtime() -> bool:
    return bool(getattr(sys, "frozen", False))


def standalone_site_dir() -> Path:
    """Add-on install location that belongs to this standalone build."""
    return Path(sys.executable).resolve().parent / "ephyr_site"


def ensure_standalone_site_on_path() -> Optional[Path]:
    """Make add-ons installed beside a standalone build importable.

    The directory is created only when an add-on is installed. A normal launch
    leaves the application folder untouched until that happens.
    """
    if not is_frozen_runtime():
        return None
    site_dir = standalone_site_dir()
    if not site_dir.is_dir():
        return None
    site.addsitedir(str(site_dir))
    return site_dir


def pip_subprocess_env() -> dict[str, str]:
    """Environment for a real interpreter spawned by the GUI.

    Drop launcher variables that make ``-m pip`` fail, and drop bundle library
    paths so a standalone build does not force its own libraries onto another
    Python.
    """
    env = dict(os.environ)
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    for key in _PIP_RETARGET_KEYS:
        env.pop(key, None)
    for key in ("SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
        value = env.get(key)
        if value and not Path(value).exists():
            env.pop(key, None)

    roots = _frozen_library_roots()
    if roots:
        for key in (*_LIBRARY_PATH_KEYS, "PATH"):
            _drop_paths_inside(env, key, roots)
    return env


def subprocess_kwargs() -> dict[str, int]:
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if sys.platform == "win32" and creationflags:
        return {"creationflags": creationflags}
    return {}


def build_pip_command(args: Sequence[str]) -> list[str]:
    """``pip`` command for the interpreter that launched a non-standalone Ephyr."""
    if is_frozen_runtime():
        raise RuntimeError("A standalone build installs add-ons inside the application.")

    python = list(python_argv())
    _reject_this_application(python)
    env = pip_subprocess_env()
    pip_prefix = _pip_prefix(python, env)
    target: Optional[Path] = None
    if is_frozen_runtime():
        target = standalone_site_dir()
        target.mkdir(parents=True, exist_ok=True)
    return [*pip_prefix, *adjust_pip_args(args, target=target)]


def adjust_pip_args(args: Sequence[str], *, target: Optional[Path]) -> list[str]:
    pip_args = list(args)
    if target is None or not pip_args or pip_args[0] != "install":
        return pip_args
    return ["install", "--target", str(target), *pip_args[1:]]


def uninstall_standalone_distribution(distribution_name: str) -> None:
    """Remove one distribution from the standalone add-on directory.

    ``pip uninstall`` has no target directory, and running it with an external
    interpreter would remove the package from that interpreter instead.
    """
    if not is_frozen_runtime():
        raise RuntimeError("Standalone uninstall is only used by a frozen build.")
    _uninstall_distribution_from(standalone_site_dir(), distribution_name)


def _uninstall_distribution_from(target: Path, distribution_name: str) -> None:
    if not target.is_dir():
        raise RuntimeError(f"{distribution_name} is not installed in {target}")

    wanted = normalize_distribution_name(distribution_name)
    removed = False
    for dist_info in sorted(target.glob("*.dist-info")):
        if normalize_distribution_name(_dist_info_name(dist_info)) != wanted:
            continue
        if not (dist_info / "RECORD").is_file():
            _remove_unrecorded_package(target, _dist_info_name(dist_info))
        else:
            _remove_recorded_files(target, dist_info)
        if dist_info.exists():
            shutil.rmtree(dist_info)
        removed = True
    _prune_empty_directories(target)
    if not removed:
        raise RuntimeError(f"{distribution_name} is not installed in {target}")


def normalize_distribution_name(name: str) -> str:
    return _DIST_NAME_RE.sub("-", name).strip("-").lower()


def install_standalone_package(package_dir: Path, *, upgrade: bool) -> None:
    """Install a local project into the standalone add-on directory."""
    if not is_frozen_runtime():
        raise RuntimeError("In-process install is only used by a standalone build.")
    install_project_into(standalone_site_dir(), Path(package_dir), upgrade=upgrade)


def install_project_into(target: Path, package_dir: Path, *, upgrade: bool) -> None:
    """Install a local project and its binary dependencies into ``target``.

    The add-on is copied in this process. Dependencies are wheels downloaded by
    pip, also in this process. Nothing is launched with ``sys.executable``.
    """
    package_dir = Path(package_dir)
    project = _read_project(package_dir)
    name = str(project.get("name") or "").strip()
    if not name:
        raise RuntimeError(f"Add-on pyproject.toml has no project name: {package_dir}")
    version = str(project.get("version") or "0.0.0").strip() or "0.0.0"
    target.mkdir(parents=True, exist_ok=True)
    try:
        from ephyr.logger import ephyr_logger

        ephyr_logger().info(
            "Installing %s %s into %s (upgrade=%s)",
            name,
            version,
            target,
            upgrade,
        )
    except Exception:
        pass

    requirements = _project_requirements(project)
    if requirements:
        _pip_install_target(target, requirements, upgrade=True, no_deps=False)

    try:
        _uninstall_distribution_from(target, name)
    except RuntimeError:
        pass
    installed = _copy_import_tree(package_dir, target)
    _write_distribution(target, name, version, project, installed)


def _read_project(package_dir: Path) -> dict:
    pyproject = package_dir / "pyproject.toml"
    if not pyproject.is_file():
        raise RuntimeError(f"Add-on has no pyproject.toml: {package_dir}")
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib
    with pyproject.open("rb") as handle:
        parsed = tomllib.load(handle)
    project = parsed.get("project")
    if not isinstance(project, dict):
        raise RuntimeError(f"Add-on pyproject.toml has no [project] table: {package_dir}")
    project["_entry_points"] = parsed.get("project", {}).get("entry-points", {}) or {}
    return project


def _project_requirements(project: dict) -> list[str]:
    """Dependencies pip should download. Ephyr itself is already the running app."""
    from packaging.requirements import Requirement

    requirements: list[str] = []
    for raw in project.get("dependencies") or []:
        req = Requirement(str(raw))
        if req.marker is not None and not req.marker.evaluate():
            continue
        if normalize_distribution_name(req.name) == "ephyr":
            continue
        extras = f"[{','.join(sorted(req.extras))}]" if req.extras else ""
        requirements.append(f"{req.name}{extras}{req.specifier}")
    return requirements


_SKIP_IMPORT_DIRS = {
    ".git", ".hg", ".svn", "build", "dist", "__pycache__",
    "tests", "test", ".venv", "venv", "node_modules",
}


def _import_root(package_dir: Path) -> Path:
    src = package_dir / "src"
    if (src / "ephyr_add_ons").exists():
        return src
    return package_dir


def _copy_import_tree(package_dir: Path, target: Path) -> list[Path]:
    root = _import_root(package_dir)
    copied: list[Path] = []
    for child in sorted(root.iterdir(), key=lambda path: path.name):
        if child.name in _SKIP_IMPORT_DIRS or child.name.startswith("."):
            continue
        if child.name.endswith((".egg-info", ".dist-info")):
            continue
        if child.is_file() and child.suffix != ".py":
            continue
        if child.is_dir() and not _contains_python(child):
            continue
        destination = target / child.name
        if child.is_dir():
            copied.extend(_copy_tree(child, destination))
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(child, destination)
            copied.append(destination)
    if not copied:
        raise RuntimeError(f"Add-on has no Python modules to install: {package_dir}")
    return copied


def _contains_python(directory: Path) -> bool:
    return any(path.suffix == ".py" for path in directory.rglob("*.py"))


def _copy_tree(source: Path, destination: Path) -> list[Path]:
    copied: list[Path] = []
    for path in sorted(source.rglob("*"), key=lambda item: item.as_posix()):
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        relative = path.relative_to(source)
        output = destination / relative
        if path.is_dir():
            output.mkdir(parents=True, exist_ok=True)
            continue
        if not path.is_file():
            continue
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, output)
        copied.append(output)
    return copied


def _write_distribution(
        target: Path,
        name: str,
        version: str,
        project: dict,
        installed: Sequence[Path],
) -> None:
    dist_name = re.sub(r"[-_.]+", "_", name).strip("_").lower()
    dist_info = target / f"{dist_name}-{version}.dist-info"
    if dist_info.exists():
        shutil.rmtree(dist_info)
    dist_info.mkdir(parents=True)
    metadata = [
        "Metadata-Version: 2.1",
        f"Name: {name}",
        f"Version: {version}",
    ]
    summary = str(project.get("description") or "").strip()
    if summary:
        metadata.append(f"Summary: {summary}")
    for requirement in project.get("dependencies") or []:
        metadata.append(f"Requires-Dist: {requirement}")
    (dist_info / "METADATA").write_text("\n".join(metadata) + "\n", encoding="utf-8")
    entry_points = project.get("_entry_points") or {}
    if isinstance(entry_points, dict) and entry_points:
        lines: list[str] = []
        for group, mapping in entry_points.items():
            if not isinstance(mapping, dict):
                continue
            lines.append(f"[{group}]")
            for entry_name, value in mapping.items():
                lines.append(f"{entry_name} = {value}")
            lines.append("")
        (dist_info / "entry_points.txt").write_text("\n".join(lines), encoding="utf-8")
    recorded = [path for path in installed if path.is_file()]
    recorded.extend(path for path in dist_info.iterdir() if path.is_file())
    record_path = dist_info / "RECORD"
    lines = [_record_line(target, path) for path in recorded]
    lines.append(f"{_relative_posix(target, record_path)},,")
    record_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _record_line(root: Path, path: Path) -> str:
    import base64
    import hashlib

    payload = path.read_bytes()
    digest = base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).decode("ascii").rstrip("=")
    return f"{_relative_posix(root, path)},sha256={digest},{len(payload)}"


def _relative_posix(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def python_argv() -> tuple[str, ...]:
    """Interpreter for pip when Ephyr itself was started by Python."""
    if is_frozen_runtime():
        raise RuntimeError(
            "A standalone build installs add-ons inside the application and does not launch Python."
        )
    return (sys.executable,)


def _pip_prefix(python: Sequence[str], env: dict[str, str]) -> list[str]:
    if _module_runs(python, "pip", env):
        return [*python, "-m", "pip"]

    sibling = _sibling_pip(python)
    if sibling is not None and _command_runs([str(sibling), "--version"], env):
        return [str(sibling)]

    bootstrap = subprocess.run(
        [*python, "-m", "ensurepip", "--upgrade"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        **subprocess_kwargs(),
    )
    if bootstrap.returncode != 0 or not _module_runs(python, "pip", env):
        details = (bootstrap.stderr or bootstrap.stdout or "pip is unavailable").strip()
        raise RuntimeError(details)

    # This interpreter had no pip. Install it into that same environment.
    upgrade = subprocess.run(
        [*python, "-m", "pip", "install", "--upgrade", "pip"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        **subprocess_kwargs(),
    )
    if upgrade.returncode != 0:
        details = (upgrade.stderr or upgrade.stdout or "failed to upgrade pip").strip()
        raise RuntimeError(details)
    return [*python, "-m", "pip"]


def _sibling_pip(python: Sequence[str]) -> Optional[Path]:
    if len(python) != 1:
        return None
    interpreter = Path(python[0])
    names = ("pip.exe", "pip3.exe", "pip") if sys.platform == "win32" else ("pip", "pip3")
    for name in names:
        candidate = interpreter.with_name(name)
        if candidate.is_file() and candidate.resolve() != Path(sys.executable).resolve():
            return candidate
    return None


def _module_runs(python: Sequence[str], module: str, env: dict[str, str]) -> bool:
    return _command_runs([*python, "-m", module, "--version"], env)


def _command_runs(command: Sequence[str], env: dict[str, str]) -> bool:
    _reject_this_application(command)
    try:
        process = subprocess.run(
            list(command),
            capture_output=True,
            text=True,
            check=False,
            env=env,
            timeout=60,
            **subprocess_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return process.returncode == 0


def _reject_this_application(argv: Sequence[str]) -> None:
    if not argv or not is_frozen_runtime():
        return
    try:
        executable = Path(argv[0]).resolve()
        this_app = Path(sys.executable).resolve()
    except OSError:
        return
    if executable == this_app:
        raise RuntimeError(
            "Refusing to launch the standalone application as a Python interpreter."
        )


def _pip_install_target(
        target: Path,
        arguments: Sequence[str],
        *,
        upgrade: bool,
        no_deps: bool,
) -> None:
    from pip._internal.cli.main import main as pip_main

    args = [
        "install",
        "--disable-pip-version-check",
        "--no-input",
        "--no-warn-script-location",
        "--target",
        str(target),
    ]
    if upgrade:
        args.append("--upgrade")
    if no_deps:
        args.append("--no-deps")
    else:
        # A source distribution would spawn the frozen executable to build it.
        args.extend(["--only-binary", ":all:"])
    args.extend(arguments)

    _ensure_stdio()
    output = io.StringIO()
    from contextlib import redirect_stderr, redirect_stdout

    with redirect_stdout(output), redirect_stderr(output):
        try:
            code = pip_main(list(args))
        except SystemExit as exc:
            code = exc.code
    text = output.getvalue().strip()
    if text:
        try:
            from ephyr.logger import ephyr_logger

            ephyr_logger().info(text)
        except Exception:
            pass
    if code not in (0, None):
        raise RuntimeError(text or f"pip exited with status {code}")


def _ensure_stdio() -> None:
    # A windowed standalone build has no console. pip writes to stdout.
    if sys.stdout is None:
        sys.stdout = io.StringIO()
    if sys.stderr is None:
        sys.stderr = io.StringIO()


def _frozen_library_roots() -> list[str]:
    if not is_frozen_runtime():
        return []
    roots = [str(Path(sys.executable).resolve().parent)]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(str(Path(meipass).resolve()))
    return roots


def _drop_paths_inside(env: dict[str, str], key: str, roots: Sequence[str]) -> None:
    raw = env.get(key)
    if not raw:
        return
    kept: list[str] = []
    for entry in raw.split(os.pathsep):
        if not entry:
            continue
        try:
            resolved = str(Path(entry).resolve())
        except OSError:
            kept.append(entry)
            continue
        if any(resolved == root or resolved.startswith(root + os.sep) for root in roots):
            continue
        kept.append(entry)
    if kept:
        env[key] = os.pathsep.join(kept)
    else:
        env.pop(key, None)


def _dist_info_name(dist_info: Path) -> str:
    metadata = dist_info / "METADATA"
    if metadata.is_file():
        for line in metadata.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                break
            if line.lower().startswith("name:"):
                return line.split(":", 1)[1].strip()
    return dist_info.name.split("-", 1)[0]


def _remove_recorded_files(target: Path, dist_info: Path) -> None:
    root = target.resolve()
    record = dist_info / "RECORD"
    if not record.is_file():
        return
    for line in record.read_text(encoding="utf-8", errors="replace").splitlines():
        rel = urllib.parse.unquote(line.split(",", 1)[0].strip())
        if not rel:
            continue
        path = (root / rel).resolve()
        if path != root and root not in path.parents:
            continue
        if path.is_file() or path.is_symlink():
            path.unlink()


def _remove_unrecorded_package(target: Path, distribution_name: str) -> None:
    wanted = normalize_distribution_name(distribution_name)
    for child in target.iterdir():
        if child.suffix in {".dist-info", ".egg-info", ".data"}:
            continue
        if normalize_distribution_name(child.name) != wanted:
            continue
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        elif child.is_file() or child.is_symlink():
            child.unlink()


def _prune_empty_directories(target: Path) -> None:
    root = target.resolve()
    directories = sorted(
        (path for path in root.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    )
    for directory in directories:
        if directory.resolve() == root:
            continue
        try:
            directory.rmdir()
        except OSError:
            continue
