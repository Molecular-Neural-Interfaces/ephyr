# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import QApplication, QWidget, QFileDialog


def resolve_app_icon_path() -> Path | None:
    candidates: list[Path] = [
        Path(__file__).resolve().parent / "assets" / "ephyr.png",
    ]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "ephyr_assets" / "ephyr.png")
    repo_root = Path(__file__).resolve().parents[2]
    candidates.append(repo_root / "devtools" / "distribute" / "assets" / "ephyr.png")
    for path in candidates:
        if path.is_file():
            return path
    return None


def apply_application_icon(app: QApplication, window: QWidget | None = None) -> None:
    icon_path = resolve_app_icon_path()
    if icon_path is None:
        return
    icon = QIcon(str(icon_path))
    if icon.isNull():
        return
    app.setWindowIcon(icon)
    if window is not None:
        window.setWindowIcon(icon)
        handle = window.windowHandle()
        if handle is not None:
            handle.setIcon(icon)
    if sys.platform == "darwin":
        _set_macos_dock_icon(icon_path)


def _set_macos_dock_icon(icon_path: Path) -> None:
    """Replace the Python interpreter icon in the Dock when running from a console script."""
    try:
        from AppKit import NSApplication, NSImage
    except ImportError:
        try:
            _set_macos_dock_icon_via_objc(icon_path)
        except Exception:
            return
        return
    try:
        image = NSImage.alloc().initByReferencingFile_(str(icon_path))
        if image is None:
            return
        NSApplication.sharedApplication().setApplicationIconImage_(image)
    except Exception:
        return


def _set_macos_dock_icon_via_objc(icon_path: Path) -> None:
    import ctypes
    import ctypes.util

    objc_path = ctypes.util.find_library("objc")
    if not objc_path:
        return
    objc = ctypes.cdll.LoadLibrary(objc_path)
    objc.objc_getClass.restype = ctypes.c_void_p
    objc.objc_getClass.argtypes = [ctypes.c_char_p]
    objc.sel_registerName.restype = ctypes.c_void_p
    objc.sel_registerName.argtypes = [ctypes.c_char_p]

    msg_send = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(
        ("objc_msgSend", objc)
    )
    msg_send_id = ctypes.CFUNCTYPE(
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p
    )(("objc_msgSend", objc))
    msg_send_str = ctypes.CFUNCTYPE(
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p
    )(("objc_msgSend", objc))

    ns_string = objc.objc_getClass(b"NSString")
    ns_image = objc.objc_getClass(b"NSImage")
    ns_application = objc.objc_getClass(b"NSApplication")
    string_with_utf8 = objc.sel_registerName(b"stringWithUTF8String:")
    alloc = objc.sel_registerName(b"alloc")
    init_by_file = objc.sel_registerName(b"initByReferencingFile:")
    shared_application = objc.sel_registerName(b"sharedApplication")
    set_application_icon = objc.sel_registerName(b"setApplicationIconImage:")

    path_value = msg_send_str(
        ns_string, string_with_utf8, str(icon_path).encode("utf-8")
    )
    image = msg_send_id(msg_send(ns_image, alloc), init_by_file, path_value)
    if not image:
        return
    ns_app = msg_send(ns_application, shared_application)
    if not ns_app:
        return
    msg_send_id(ns_app, set_application_icon, image)


def milliseconds_to_readable(milliseconds, wrap=True) -> str:
    seconds = int(milliseconds / 1000) % 60
    minutes = int(milliseconds / (1000 * 60)) % 60
    hours = int(milliseconds / (1000 * 60 * 60)) % 24
    ms = int(milliseconds) % 1000

    time = None
    if hours > 0:
        time = f"{hours}h {minutes}m {seconds}s {ms}ms"
    elif minutes > 0:
        time = f"{minutes}m {seconds}s {ms}ms"
    elif seconds > 0:
        time = f"{seconds}s {ms}ms"
    elif ms > 0:
        time = f"{ms}ms"

    if time is not None:
        return f"[{time}]" if wrap else f"{time}"

    return ""


def sample_rate_to_readable(sample_rate: float, wrap=True) -> str:
    if sample_rate <= 0:
        return ""
    if sample_rate >= 1_000_000:
        value = sample_rate / 1_000_000
        unit = "MHz"
    elif sample_rate >= 1_000:
        value = sample_rate / 1_000
        unit = "kHz"
    else:
        value = sample_rate
        unit = "Hz"
    formatted = str(int(value)) if float(value).is_integer() else f"{value:g}"
    text = f"{formatted} {unit}"
    return f"[{text}]" if wrap else text


def capture_widget_to_file(main_widget: QWidget, widget: QWidget, base_filename: str):
    """
    Захватывает содержимое виджета и сохраняет его как PNG высокого разрешения.

    Args:
        widget: Виджет для захвата.
        base_filename: Базовое имя для файла (например, "main_window").
    """
    # Делаем скриншот виджета
    pixmap: QPixmap = widget.grab()

    # Для научного постера важно высокое разрешение.
    # Метод grab() уже захватывает в native resolution,
    # но мы можем масштабировать pixmap для увеличения DPI.
    # Например, увеличим в 2 раза для лучшего качества при печати.
    target_size = pixmap.size() * 2  # Увеличиваем в 2 раза
    scaled_pixmap = pixmap.scaled(target_size)

    # Формируем имя файла. Сохраняем в PNG для максимального качества.
    file_path, _ = QFileDialog.getSaveFileName(
        main_widget,
        f"Сохранить {base_filename}",
        f"{base_filename}.png",
        "PNG Image (*.png)"
    )

    if file_path:
        # Сохраняем в PNG
        success = scaled_pixmap.save(file_path, "PNG")
        if success:
            print(f"Успешно сохранено: {file_path}")
        else:
            print(f"Ошибка при сохранении: {file_path}")
