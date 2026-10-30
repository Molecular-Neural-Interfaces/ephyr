# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

"""Names and colors for groups created by splitting or merging a vocabulary."""

from __future__ import annotations

import colorsys


def allocate_unique_vocabulary_name(taken: set[str], desired: str) -> str:
    """Return `desired`, or `desired_2`, `desired_3`, … if that name is already used.

    The chosen name is added to `taken`.
    """
    base = desired.strip() or "Group"
    if base not in taken:
        taken.add(base)
        return base
    index = 2
    while f"{base}_{index}" in taken:
        index += 1
    unique = f"{base}_{index}"
    taken.add(unique)
    return unique


def companion_vocabulary_color(color: str) -> str:
    """A different saturated color, so the second group of a split is visible on the trace."""
    for degrees in (40, 80, 140, 200):
        shifted = _shift_hex_hue(color, degrees)
        if shifted.lower() != (color or "").strip().lower():
            return shifted
    return "#CC5500"


def _shift_hex_hue(color: str, degrees: float) -> str:
    text = (color or "").strip()
    if len(text) == 4 and text.startswith("#"):
        text = "#" + "".join(character * 2 for character in text[1:])
    if len(text) != 7 or not text.startswith("#"):
        return "#CC5500"
    try:
        red = int(text[1:3], 16) / 255.0
        green = int(text[3:5], 16) / 255.0
        blue = int(text[5:7], 16) / 255.0
    except ValueError:
        return "#CC5500"
    hue, saturation, value = colorsys.rgb_to_hsv(red, green, blue)
    hue = (hue + degrees / 360.0) % 1.0
    saturation = max(saturation, 0.65)
    value = max(value, 0.55)
    red, green, blue = colorsys.hsv_to_rgb(hue, saturation, value)
    return "#{:02X}{:02X}{:02X}".format(round(red * 255), round(green * 255), round(blue * 255))
