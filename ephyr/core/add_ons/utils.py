# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

import importlib
import importlib.util
import sys
from importlib.metadata import entry_points
from pathlib import Path
from typing import Callable, Dict, Optional

from ephyr.logger import ephyr_logger

from ephyr.core.add_ons.base import BaseAddOn

# Folder captured on the first load of this process. A later change in global
# storage is picked up only after restart, because imported modules stay in sys.modules.
_active_local_add_ons_dir: Path | None = None


def _drop_stale_modules(module_path: str):
    stale_modules = [
        name for name in list(sys.modules.keys())
        if name == module_path or name.startswith(f"{module_path}.")
    ]
    for stale_module_name in stale_modules:
        sys.modules.pop(stale_module_name, None)


def _add_module_add_on_classes(
        runtime_add_ons: Dict[str, BaseAddOn],
        module,
        add_on_name: str,
        *,
        distribution_name: str = "",
):
    added = 0
    for attr_name in dir(module):
        attr = getattr(module, attr_name)
        if isinstance(attr, type) and issubclass(attr, BaseAddOn) and attr != BaseAddOn:
            add_on_obj = attr()
            setattr(add_on_obj, "_ephyr_module_name", add_on_name)
            setattr(add_on_obj, "_ephyr_entry_point_name", add_on_name)
            setattr(add_on_obj, "_ephyr_distribution_name", distribution_name)
            runtime_add_ons[add_on_name] = add_on_obj
            added += 1
    return added


def _import_dev_module(runtime_add_ons: Dict[str, BaseAddOn], module_path: str, add_on_name: str, distribution_name: str):
    module = importlib.import_module(module_path)
    return _add_module_add_on_classes(
        runtime_add_ons,
        module,
        add_on_name,
        distribution_name=distribution_name,
    )


def _import_dev_file(runtime_add_ons: Dict[str, BaseAddOn], py_file: Path, add_on_name: str, distribution_name: str):
    """Load a loose script under a private module name.

    Importing it as its bare filename would replace a standard-library module
    when the chosen folder contains something like ``os.py`` or ``setup.py``.
    """
    module_name = f"ephyr_local_addons.{py_file.stem}"
    _drop_stale_modules(module_name)
    spec = importlib.util.spec_from_file_location(module_name, py_file)
    if spec is None or spec.loader is None:
        return 0
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(module_name, None)
        raise
    return _add_module_add_on_classes(
        runtime_add_ons,
        module,
        add_on_name,
        distribution_name=distribution_name,
    )


def _load_quietly(label: str, load: Callable[[], Optional[int]]) -> None:
    """Import one local module without letting it stop Ephyr.

    A folder of local add-ons is ordinary Python. ``setup.py`` and similar scripts
    call ``setuptools.setup()``, which raises ``SystemExit`` when the program was
    not launched as a setuptools command. ``SystemExit`` is not an ``Exception``.
    """
    try:
        load()
    except KeyboardInterrupt:
        raise
    except BaseException as exc:
        ephyr_logger().error(f"Skipped local add-on {label}: {exc}")


def load_installed_add_ons():
    importlib.invalidate_caches()
    # A local package of the same name replaces the installed copy.
    prefer_local_add_ons_path()

    runtime_add_ons: Dict[str, BaseAddOn] = {}
    for ep in entry_points().select(group="ephyr.add_ons"):
        try:
            module_path = str(getattr(ep, "value", "")).split(":", 1)[0].strip()
            if module_path:
                _drop_stale_modules(module_path)

            add_on_cls = ep.load()
            add_on_obj = add_on_cls()
            add_on_name = ep.name
            setattr(add_on_obj, "_ephyr_module_name", add_on_name)
            setattr(add_on_obj, "_ephyr_entry_point_name", add_on_name)
            setattr(add_on_obj, "_ephyr_distribution_name", ep.dist.name)
            runtime_add_ons[add_on_name] = add_on_obj
        except Exception as e:
            ephyr_logger().debug(str(e))
            continue

    return runtime_add_ons


def _configured_local_add_ons_dir() -> Path:
    try:
        from ephyr.core.global_storage import GlobalStorageManager

        return GlobalStorageManager().local_add_ons_dir
    except Exception as exc:
        ephyr_logger().debug(str(exc))
        return Path("./add_on_development")


def active_local_add_ons_dir() -> Path:
    """Local add-on folder for this process. Frozen on the first lookup."""
    global _active_local_add_ons_dir
    if _active_local_add_ons_dir is None:
        _active_local_add_ons_dir = _configured_local_add_ons_dir()
    return _active_local_add_ons_dir


def prefer_local_add_ons_path() -> None:
    """Search the local add-on folder before site-packages.

    Installed and local trees share the ``ephyr_add_ons`` namespace. The folder
    stays behind the standard library, so a local ``os.py`` cannot replace it,
    but a copied package overrides the installed one of the same name.
    """
    dev_folder = active_local_add_ons_dir()
    if not dev_folder.is_dir():
        return
    folder = str(dev_folder.resolve())
    if folder in sys.path:
        sys.path.remove(folder)
    site_indexes = [
        index for index, entry in enumerate(sys.path)
        if Path(entry).name == "site-packages"
    ]
    sys.path.insert(site_indexes[0] if site_indexes else len(sys.path), folder)
    # A namespace already imported keeps its own path. Put the local tree first.
    parent = sys.modules.get("ephyr_add_ons")
    local_namespace = dev_folder / "ephyr_add_ons"
    if parent is None or not local_namespace.is_dir():
        return
    local_namespace_str = str(local_namespace.resolve())
    current = [str(Path(entry).resolve()) for entry in getattr(parent, "__path__", [])]
    if local_namespace_str in current:
        current.remove(local_namespace_str)
    current.insert(0, local_namespace_str)
    parent.__path__ = current


def load_dev_add_ons():
    runtime_add_ons: Dict[str, BaseAddOn] = {}
    dev_folder = active_local_add_ons_dir()
    if dev_folder.is_dir():
        prefer_local_add_ons_path()

        for py_file in sorted(dev_folder.glob("*.py"), key=lambda path: path.name):
            # setup.py runs setuptools and exits the process when imported.
            if py_file.name in {"__init__.py", "setup.py", "conftest.py"}:
                continue

            module_name = py_file.stem

            def _load_top_level(py_file=py_file, module_name=module_name):
                _import_dev_file(runtime_add_ons, py_file, f"dev_{module_name}", module_name)

            _load_quietly(str(py_file), _load_top_level)

        namespace_root = dev_folder / "ephyr_add_ons"
        if namespace_root.is_dir():
            for package_dir in namespace_root.iterdir():
                if not package_dir.is_dir() or not (package_dir / "__init__.py").exists():
                    continue

                package_name = package_dir.name
                module_path = f"ephyr_add_ons.{package_name}"

                def _load_package(module_path=module_path, package_name=package_name, package_dir=package_dir):
                    _drop_stale_modules(module_path)
                    _import_dev_module(runtime_add_ons, module_path, f"dev_{package_name}", package_name)

                    entry_point_module = package_dir / "entry_point.py"
                    if entry_point_module.exists():
                        _import_dev_module(
                            runtime_add_ons,
                            f"{module_path}.entry_point",
                            f"dev_{package_name}",
                            package_name,
                        )

                    for child in sorted(package_dir.iterdir(), key=lambda path: path.name):
                        if child.name in {"__pycache__", "entry_point.py", "setup.py", "conftest.py"}:
                            continue
                        if child.is_file() and child.suffix == ".py" and child.name != "__init__.py":
                            child_name = child.stem
                            _import_dev_module(
                                runtime_add_ons,
                                f"{module_path}.{child_name}",
                                f"dev_{child_name}",
                                package_name,
                            )
                        elif child.is_dir() and (child / "__init__.py").exists():
                            child_name = child.name
                            _import_dev_module(
                                runtime_add_ons,
                                f"{module_path}.{child_name}",
                                f"dev_{child_name}",
                                package_name,
                            )

                _load_quietly(str(package_dir), _load_package)

    return runtime_add_ons
