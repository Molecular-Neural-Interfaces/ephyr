# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

"""Locate the Python environment Ephyr was launched from.

A PyInstaller build sets ``sys.executable`` to the bundled application. Running
that file with ``-m pip`` opens another copy of Ephyr and never returns.
Add-ons still have to land in the environment that is actually running:

- a virtualenv install goes into that virtualenv
- a global install goes into that interpreter
- a standalone build installs into a directory next to the executable
"""

from __future__ import annotations

import functools
import os
import re
import shutil
import site
import subprocess
import sys
import urllib.parse
from pathlib import Path
from typing import Iterable, Optional, Sequence


_DIST_NAME_RE = re.compile(r"[-_.]+")
_LIBRARY_PATH_KEYS = (
    "LD_LIBRARY_PATH",
    "DYLD_LIBRARY_PATH",
    "DYLD_FRAMEWORK_PATH",
    "DYLD_FALLBACK_LIBRARY_PATH",
)
_PIP_RETARGET_KEYS = ("PIP_TARGET", "PIP_PREFIX", "PIP_USER", "PYTHONUSERBASE")
_DARWIN_PYTHON_STUBS = {Path("/usr/bin/python3"), Path("/usr/bin/python")}


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
    """``pip`` command that installs into the environment Ephyr is running in."""
    if is_frozen_runtime() and args and args[0] == "uninstall":
        raise RuntimeError("Standalone uninstall does not invoke pip.")

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


@functools.lru_cache(maxsize=1)
def python_argv() -> tuple[str, ...]:
    """Interpreter for pip.

    Outside a bundle this is the interpreter that started Ephyr, so a virtualenv
    stays a virtualenv and a global install stays global. A bundle is not an
    interpreter; pip then runs on a Python of the same version and installs with
    ``--target`` next to the executable.
    """
    if not is_frozen_runtime():
        return (sys.executable,)

    major, minor = sys.version_info[:2]
    env = pip_subprocess_env()
    this_app = Path(sys.executable).resolve()
    exact = [f"python{major}.{minor}"]
    generic = [f"python{major}", "python3", "python"]
    if sys.platform == "win32":
        exact = [f"{name}.exe" for name in exact]
        generic = [f"{name}.exe" for name in generic]

    # Exact minor first, so an older ``python3`` earlier on PATH does not hide it.
    for names in (exact, generic):
        for argv in _interpreter_candidates(names, this_app):
            if _interpreter_version(argv, env) == (major, minor):
                return argv

    if sys.platform == "win32":
        py = shutil.which("py")
        if py:
            try:
                resolved_py = Path(py).resolve()
            except OSError:
                resolved_py = None
            if resolved_py is not None and resolved_py != this_app:
                argv = (str(resolved_py), f"-{major}.{minor}")
                if _interpreter_version(argv, env) == (major, minor):
                    return argv

    version = f"{major}.{minor}"
    raise RuntimeError(
        f"Standalone Ephyr needs Python {version} with pip so add-ons can be installed into "
        f"{standalone_site_dir()}. No matching interpreter was found."
    )


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

    # The application interpreter had no pip. Bring that environment's pip up
    # to date once, and leave an external interpreter used by a standalone
    # build alone.
    if not is_frozen_runtime():
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


def _interpreter_version(argv: Sequence[str], env: dict[str, str]) -> Optional[tuple[int, int]]:
    _reject_this_application(argv)
    try:
        process = subprocess.run(
            [*argv, "-c", "import sys; print(sys.version_info[0], sys.version_info[1])"],
            capture_output=True,
            text=True,
            check=False,
            env=env,
            timeout=20,
            **subprocess_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if process.returncode != 0:
        return None
    parts = process.stdout.split()
    if len(parts) < 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


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


def _search_directories() -> list[Path]:
    seen: set[Path] = set()
    directories: list[Path] = []
    raw_entries = [Path(entry) for entry in os.environ.get("PATH", "").split(os.pathsep) if entry]
    raw_entries.extend(_extra_interpreter_dirs())
    for directory in raw_entries:
        if not directory.is_dir():
            continue
        try:
            resolved = directory.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        directories.append(directory)
    return directories


def _interpreter_candidates(names: Sequence[str], this_app: Path) -> Iterable[tuple[str, ...]]:
    seen: set[Path] = set()
    for directory in _search_directories():
        for name in names:
            candidate = directory / name
            if sys.platform == "darwin" and candidate in _DARWIN_PYTHON_STUBS:
                continue
            if not candidate.is_file() or not os.access(candidate, os.X_OK):
                continue
            try:
                resolved = candidate.resolve()
            except OSError:
                continue
            if resolved == this_app or resolved in seen:
                continue
            seen.add(resolved)
            yield (str(resolved),)


def _extra_interpreter_dirs() -> Iterable[Path]:
    """Places a GUI launch (short PATH) can still find a matching Python."""
    major, minor = sys.version_info[:2]
    home = Path.home()
    directories: list[Path] = [
        home / ".local" / "bin",
        *_versioned_interpreter_bins(home / ".pyenv" / "versions", f"{major}.{minor}"),
        *_versioned_interpreter_bins(home / ".asdf" / "installs" / "python", f"{major}.{minor}"),
        *_uv_interpreter_bins(home / ".local" / "share" / "uv" / "python", major, minor),
    ]
    if sys.platform == "darwin":
        directories.extend((
            Path(f"/opt/homebrew/opt/python@{major}.{minor}/bin"),
            Path("/opt/homebrew/bin"),
            Path(f"/usr/local/opt/python@{major}.{minor}/bin"),
            Path("/usr/local/bin"),
            Path(f"/Library/Frameworks/Python.framework/Versions/{major}.{minor}/bin"),
            home / f"Library/Frameworks/Python.framework/Versions/{major}.{minor}/bin",
            *_uv_interpreter_bins(home / "Library" / "Application Support" / "uv" / "python", major, minor),
        ))
    elif sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            directories.append(Path(local) / "Programs" / "Python" / f"Python{major}{minor}")
        directories.append(home / "AppData" / "Local" / "Programs" / "Python" / f"Python{major}{minor}")
        directories.append(Path(f"C:/Python{major}{minor}"))
    else:
        directories.extend((Path("/usr/local/bin"), Path("/usr/bin")))
    return directories


def _versioned_interpreter_bins(root: Path, version_prefix: str) -> list[Path]:
    if not root.is_dir():
        return []
    bins: list[Path] = []
    try:
        children = list(root.iterdir())
    except OSError:
        return []
    for child in children:
        if child.name == version_prefix or child.name.startswith(version_prefix + "."):
            bins.append(child / "bin")
    return bins


def _uv_interpreter_bins(root: Path, major: int, minor: int) -> list[Path]:
    if not root.is_dir():
        return []
    token = f"{major}.{minor}"
    bins: list[Path] = []
    try:
        children = list(root.iterdir())
    except OSError:
        return []
    for child in children:
        if token in child.name:
            bins.append(child / "bin")
    return bins


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
