"""A small filled circle indicating state at a glance.

The Apple pattern this borrows (Time Machine's menu bar icon, the
Wi-Fi/Bluetooth status dots) puts colour in a dedicated indicator, never
in the text itself. Keeping it a separate widget — rather than the
previous approach of embedding an HTML ``<span style="color:...">`` into
the status label — is what let the label next to it become plain text,
which in turn is what makes :class:`~trxmp.ui.widgets.eliding_label.ElidingLabel`
possible: font-metric eliding has no idea what to do with markup.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import QWidget

_DIAMETER = 8


class StatusDot(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = QColor("#888888")
        self.setFixedSize(_DIAMETER, _DIAMETER)

    def set_color(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._color)
        painter.drawEllipse(self.rect())
