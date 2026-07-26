from typing import Union

from PyQt6.QtGui import QScreen
from PyQt6.QtWidgets import QWidget


class QWidgetMixin:
    def __init_subclass__(cls, scm_type=None, name=None, **kwargs):
        super().__init_subclass__(**kwargs)
        if not issubclass(cls, QWidget):
            raise TypeError(f"{cls.__name__} must be a subclass of {QWidget.__name__} "
                            f"to use {QWidgetMixin.__name__}")

    def move_to_center(self, parent_widget: Union[QWidget, QScreen]):
        try:
            parent_geometry = parent_widget.geometry()
        except AttributeError:
            parent_geometry = parent_widget.availableGeometry()

        parent_center = parent_geometry.center()
        geometry = self.geometry()
        geometry.moveCenter(parent_center)
        self.setGeometry(geometry)
