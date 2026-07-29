# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import platform
from typing import List


def get_hotkey_descriptions() -> List[str]:
    ctrl_key = "Cmd" if platform.system() == "Darwin" else "Ctrl"
    return [
        f"{ctrl_key} + S: save current session",
        f"{ctrl_key} + scroll: zoom in/out",
        "M: measurement bar",
        "V: view selected area",
        "Esc: disable",
    ]
