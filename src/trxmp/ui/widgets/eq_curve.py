"""The interactive EQ curve — the app's centrepiece.

Draws the *real* frequency response of the current preset (computed by
``application.eq_analysis``, the same RBJ math the audio engine runs) and
lets the user shape it directly: drag a handle to move a band in gain
and frequency, wheel over it to change Q, double-click to flatten it.

Why a custom-painted ``QWidget`` and not a charting library: this widget
needs pixel-exact hit-testing on a logarithmic axis, hover affordances,
and a repaint budget measured in milliseconds during a drag. QPainter
gives all of that with zero dependencies. Reaching for matplotlib here
would be slower, heavier, and would still look like matplotlib.

The axes are the interesting part. Frequency is logarithmic because
hearing is: the octave 20→40 Hz deserves the same screen width as
10k→20k. Gain is linear in dB because dB is already a log scale.
"""

from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QWheelEvent,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from trxmp.application.eq_analysis import compute_response_curve
from trxmp.domain.equalizer import MAX_FREQUENCY_HZ, MIN_FREQUENCY_HZ
from trxmp.ui.theme import FONT_SIZE_CAPTION, Palette
from trxmp.ui.view_models import EqViewModel

# ± this many dB fills the vertical axis. 12 leaves the ±9 dB guardrail
# comfortably inside the frame instead of pinned to the edges.
DB_RANGE = 12.0
GRID_DB = (-9, -6, -3, 0, 3, 6, 9)
GRID_FREQUENCIES = (32, 64, 125, 250, 500, 1_000, 2_000, 4_000, 8_000, 16_000)

MARGIN_LEFT = 40
MARGIN_RIGHT = 14
MARGIN_TOP = 14
MARGIN_BOTTOM = 22

HANDLE_RADIUS = 5.0
HANDLE_HOVER_RADIUS = 7.0
HIT_SLOP = 6.0

_LOG_MIN = math.log10(MIN_FREQUENCY_HZ)
_LOG_MAX = math.log10(MAX_FREQUENCY_HZ)

# Q per wheel notch (a notch is 120 eighths of a degree). Multiplicative
# because Q is perceptually geometric: 0.5→1.0 is the same "amount" of
# change as 4.0→8.0.
_Q_WHEEL_FACTOR = 1.12


class EqCurveWidget(QWidget):
    """Renders and edits the EQ curve for an :class:`EqViewModel`."""

    def __init__(self, model: EqViewModel, palette: Palette, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model = model
        self._palette = palette
        self._dragging: int | None = None
        self._hovered: int | None = None

        self.setMinimumHeight(220)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)  # hover without a button held down
        self.setCursor(Qt.CursorShape.CrossCursor)

        # Any model change repaints us. The model never touches this
        # widget directly — it just announces, and whoever cares listens.
        model.bands_changed.connect(self.update)
        model.powered_changed.connect(self.update)
        model.preset_loaded.connect(self._on_preset_loaded)

    def _on_preset_loaded(self) -> None:
        """Drop hover/drag state: a loaded preset can have fewer bands,
        which would leave these indices pointing past the end and blow
        up in the next paint. Any index kept across a structural change
        is a dangling reference in disguise.
        """
        self._hovered = None
        self._dragging = None
        self.update()

    def set_palette(self, palette: Palette) -> None:
        """Custom-painted widgets can't be styled by QSS, so the theme
        reaches them through this instead."""
        self._palette = palette
        self.update()

    # ── Coordinate mapping ────────────────────────────────────────────
    def _plot_rect(self) -> QRectF:
        return QRectF(
            MARGIN_LEFT,
            MARGIN_TOP,
            max(1.0, self.width() - MARGIN_LEFT - MARGIN_RIGHT),
            max(1.0, self.height() - MARGIN_TOP - MARGIN_BOTTOM),
        )

    def _freq_to_x(self, frequency_hz: float) -> float:
        rect = self._plot_rect()
        fraction = (math.log10(frequency_hz) - _LOG_MIN) / (_LOG_MAX - _LOG_MIN)
        return rect.left() + fraction * rect.width()

    def _x_to_freq(self, x: float) -> float:
        rect = self._plot_rect()
        fraction = (x - rect.left()) / rect.width()
        # math.pow, not `**`: the operator is typed to return Any here
        # (a negative base with a float exponent could be complex), and
        # letting Any leak out of a mapping function would poison every
        # caller's types.
        return math.pow(10.0, _LOG_MIN + fraction * (_LOG_MAX - _LOG_MIN))

    def _db_to_y(self, db: float) -> float:
        rect = self._plot_rect()
        return rect.center().y() - (db / DB_RANGE) * (rect.height() / 2.0)

    def _y_to_db(self, y: float) -> float:
        rect = self._plot_rect()
        return (rect.center().y() - y) / (rect.height() / 2.0) * DB_RANGE

    def _handle_center(self, index: int) -> QPointF:
        band = self._model.bands[index]
        return QPointF(self._freq_to_x(band.frequency_hz), self._db_to_y(band.gain_db))

    def _band_at(self, position: QPointF) -> int | None:
        """Topmost handle under the cursor, or None.

        Iterates in reverse so that when handles overlap, the one drawn
        last (visually on top) is the one you grab — matching what the
        user sees.
        """
        reach = HANDLE_HOVER_RADIUS + HIT_SLOP
        for index in reversed(range(len(self._model.bands))):
            delta = self._handle_center(index) - position
            if math.hypot(delta.x(), delta.y()) <= reach:
                return index
        return None

    # ── Painting ──────────────────────────────────────────────────────
    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._draw_grid(painter)
        self._draw_curve(painter)
        self._draw_handles(painter)

    def _draw_grid(self, painter: QPainter) -> None:
        rect = self._plot_rect()
        p = self._palette
        font = painter.font()
        font.setPixelSize(FONT_SIZE_CAPTION)
        painter.setFont(font)

        for db in GRID_DB:
            y = self._db_to_y(db)
            is_zero = db == 0
            painter.setPen(QPen(QColor(p.grid_major if is_zero else p.grid_minor), 1.0))
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            painter.setPen(QColor(p.text_tertiary))
            painter.drawText(
                QRectF(0, y - 8, MARGIN_LEFT - 8, 16),
                Qt.AlignmentFlag.AlignRight,
                f"{db:+d}",
            )

        for frequency in GRID_FREQUENCIES:
            x = self._freq_to_x(frequency)
            painter.setPen(QPen(QColor(p.grid_minor), 1.0))
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            label = f"{frequency // 1000}k" if frequency >= 1000 else str(frequency)
            painter.setPen(QColor(p.text_tertiary))
            painter.drawText(
                QRectF(x - 20, rect.bottom() + 4, 40, MARGIN_BOTTOM),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                label,
            )

    def _curve_points(self) -> list[QPointF]:
        rect = self._plot_rect()
        # One sample per pixel column, capped: more would be invisible,
        # fewer would show corners on steep filters. Recomputing this
        # every repaint costs ~100 µs — cheap enough that caching it
        # would be complexity without a measured reason.
        num_points = max(64, min(int(rect.width()), 512))

        if self._model.powered:
            curve = compute_response_curve(self._model.to_preset(), num_points=num_points)
            magnitudes = np.clip(curve.magnitudes_db, -DB_RANGE, DB_RANGE)
            frequencies = curve.frequencies_hz
        else:  # bypassed: an honest flat line, not a hidden curve
            frequencies = np.geomspace(MIN_FREQUENCY_HZ, MAX_FREQUENCY_HZ, num_points)
            magnitudes = np.zeros(num_points)

        return [
            QPointF(self._freq_to_x(float(f)), self._db_to_y(float(db)))
            for f, db in zip(frequencies, magnitudes, strict=True)
        ]

    def _draw_curve(self, painter: QPainter) -> None:
        rect = self._plot_rect()
        points = self._curve_points()
        accent = QColor(self._palette.accent)
        if not self._model.powered:
            accent = QColor(self._palette.curve_baseline)

        line = QPainterPath(points[0])
        for point in points[1:]:
            line.lineTo(point)

        # Fill between the curve and the 0 dB line: reads instantly as
        # "boost above, cut below" without needing a legend.
        zero_y = self._db_to_y(0.0)
        fill = QPainterPath(line)
        fill.lineTo(QPointF(points[-1].x(), zero_y))
        fill.lineTo(QPointF(points[0].x(), zero_y))
        fill.closeSubpath()

        gradient = QLinearGradient(0.0, rect.top(), 0.0, rect.bottom())
        top = QColor(accent)
        top.setAlpha(60)
        bottom = QColor(accent)
        bottom.setAlpha(10)
        gradient.setColorAt(0.0, top)
        gradient.setColorAt(1.0, bottom)
        painter.fillPath(fill, QBrush(gradient))

        painter.setPen(QPen(accent, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawPath(line)

    def _draw_handles(self, painter: QPainter) -> None:
        if not self._model.powered:
            return
        p = self._palette
        for index in range(len(self._model.bands)):
            active = index in (self._hovered, self._dragging)
            radius = HANDLE_HOVER_RADIUS if active else HANDLE_RADIUS
            painter.setBrush(QColor(p.accent if active else p.surface_elevated))
            painter.setPen(QPen(QColor(p.accent), 2.0))
            painter.drawEllipse(self._handle_center(index), radius, radius)

        if self._hovered is not None:
            self._draw_readout(painter, self._hovered)

    def _draw_readout(self, painter: QPainter, index: int) -> None:
        """Live values for the hovered band, placed so the cursor never
        covers them and the box never leaves the widget."""
        band = self._model.bands[index]
        text = f"{_format_hz(band.frequency_hz)}   {band.gain_db:+.1f} dB   Q {band.q:.2f}"
        center = self._handle_center(index)

        metrics = painter.fontMetrics()
        width = metrics.horizontalAdvance(text) + 14
        height = metrics.height() + 8
        x = min(max(center.x() - width / 2, 2.0), self.width() - width - 2.0)
        y = center.y() - height - 12
        if y < 2.0:  # not enough room above? flip below the handle
            y = center.y() + 12
        box = QRectF(x, y, width, height)

        painter.setPen(QPen(QColor(self._palette.border), 1.0))
        painter.setBrush(QColor(self._palette.surface_elevated))
        painter.drawRoundedRect(box, 6.0, 6.0)
        painter.setPen(QColor(self._palette.text_primary))
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)

    # ── Interaction ───────────────────────────────────────────────────
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or not self._model.powered:
            return
        self._dragging = self._band_at(event.position())
        if self._dragging is not None:
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        position = event.position()
        if self._dragging is not None:
            # Vertical drag = gain, horizontal = frequency: two
            # parameters from one gesture, the way every pro EQ works.
            self._model.set_band_gain(self._dragging, self._y_to_db(position.y()))
            self._model.set_band_frequency(self._dragging, self._x_to_freq(position.x()))
            return

        hovered = self._band_at(position) if self._model.powered else None
        if hovered != self._hovered:
            self._hovered = hovered
            self.setCursor(
                Qt.CursorShape.OpenHandCursor if hovered is not None else Qt.CursorShape.CrossCursor
            )
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._dragging is not None:
            self._dragging = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            self.update()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        index = self._band_at(event.position())
        if index is not None and self._model.powered:
            self._model.set_band_gain(index, 0.0)  # flatten this band

    def wheelEvent(self, event: QWheelEvent) -> None:
        index = self._band_at(event.position())
        if index is None or not self._model.powered:
            event.ignore()
            return
        notches = event.angleDelta().y() / 120.0
        band = self._model.bands[index]
        self._model.set_band_q(index, band.q * (_Q_WHEEL_FACTOR**notches))
        event.accept()

    def leaveEvent(self, event: object) -> None:
        if self._hovered is not None:
            self._hovered = None
            self.update()


def _format_hz(frequency_hz: float) -> str:
    if frequency_hz >= 1000:
        return f"{frequency_hz / 1000:.2f} kHz"
    return f"{frequency_hz:.0f} Hz"
