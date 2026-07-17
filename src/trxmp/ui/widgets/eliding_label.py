"""A QLabel that visually truncates its text with an ellipsis, without
lying about what it contains.

QLabel doesn't elide on its own — squeeze one into a layout narrower
than its text and Qt just clips mid-character. That was a real bug in
this app's header: at some window widths the device line read
"Output: Headphones (SteelSeries Arc" with no ellipsis at all, cut off
mid-word, because the label's minimum size hint equalled its full-text
size and the layout had nowhere left to take space from.

The fix's key property: ``.text()`` always returns the exact string
that was set, unchanged. Only ``paintEvent`` computes an elided version,
and only for drawing. That split matters — code (and tests) that reads
a label's text for its content sees the real content, never a
truncated approximation that would otherwise depend on how wide the
window happened to be at that exact moment. Eliding is a rendering
concern; the underlying text is not.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPainter, QPaintEvent
from PySide6.QtWidgets import QLabel, QWidget


class ElidingLabel(QLabel):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # QLabel's default size policy resists shrinking below its
        # sizeHint; a label that's meant to elide has to opt out of
        # that, or the layout will never squeeze it enough to trigger
        # the ellipsis in the first place.
        self.setMinimumWidth(0)

    def minimumSizeHint(self) -> QSize:
        return QSize(0, super().minimumSizeHint().height())

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        metrics = self.fontMetrics()
        rect = self.contentsRect()
        elided = metrics.elidedText(self.text(), Qt.TextElideMode.ElideRight, rect.width())
        painter.drawText(rect, int(self.alignment()), elided)
