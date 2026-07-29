from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QWidget, QFileDialog


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
