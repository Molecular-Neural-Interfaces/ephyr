# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

import importlib
import sys
from importlib.metadata import entry_points
from pathlib import Path
from typing import Dict

from ephyr.logger import ephyr_logger

from ephyr.core.add_ons.base import BaseAddOn


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


def load_installed_add_ons():
    importlib.invalidate_caches()

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


def load_dev_add_ons():
    runtime_add_ons: Dict[str, BaseAddOn] = {}
    dev_folder = Path("./add_on_development")  # configurable path
    if dev_folder.exists():
        # Add the folder to sys.path (temporarily) to allow imports
        dev_folder_str = str(dev_folder.resolve())
        if dev_folder_str not in sys.path:
            sys.path.insert(0, dev_folder_str)

        for py_file in dev_folder.glob("*.py"):
            if py_file.name == "__init__.py":
                continue

            module_name = py_file.stem  # filename without .py
            try:
                # Remove stale module if it was loaded before
                _drop_stale_modules(module_name)

                # Import the module
                _import_dev_module(runtime_add_ons, module_name, f"dev_{module_name}", module_name)
            except Exception as e:
                ephyr_logger().debug(str(e))
                continue

        namespace_root = dev_folder / "ephyr_add_ons"
        if namespace_root.exists():
            for package_dir in namespace_root.iterdir():
                if not package_dir.is_dir() or not (package_dir / "__init__.py").exists():
                    continue

                package_name = package_dir.name
                module_path = f"ephyr_add_ons.{package_name}"
                try:
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
                        if child.name == "__pycache__" or child.name == "entry_point.py":
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
                except Exception as e:
                    ephyr_logger().debug(str(e))
                    continue

    return runtime_add_ons
