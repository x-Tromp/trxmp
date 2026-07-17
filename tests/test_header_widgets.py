"""Tests for the two small widgets the header's status line is built
from — real Qt widgets, run on the offscreen platform like the rest of
``tests/test_widgets.py``.
"""

from __future__ import annotations

from pytestqt.qtbot import QtBot

from trxmp.ui.widgets.eliding_label import ElidingLabel
from trxmp.ui.widgets.status_dot import StatusDot

_LONG_TEXT = (
    "Output: Headphones (SteelSeries Arctis Nova 5) · auto: Sundara Harman "
    "· ⚠ Equalizer APO is not installed on this device"
)


class TestElidingLabel:
    def test_text_returns_the_full_string_regardless_of_width(self, qtbot: QtBot) -> None:
        """The core contract this widget exists for: code (and tests)
        that read `.text()` must see what was actually set, never a
        truncated approximation that depends on the widget's current
        pixel width at the moment of reading."""
        label = ElidingLabel()
        qtbot.addWidget(label)
        label.setText(_LONG_TEXT)
        label.resize(40, 20)  # far narrower than the text could ever fit
        assert label.text() == _LONG_TEXT

    def test_minimum_size_hint_allows_shrinking_below_the_text_width(self, qtbot: QtBot) -> None:
        """This is the actual mechanism that makes eliding possible: a
        plain QLabel's minimum size hint equals its full-text size hint,
        which means a layout can never squeeze it small enough to need
        an ellipsis in the first place."""
        label = ElidingLabel()
        qtbot.addWidget(label)
        label.setText(_LONG_TEXT)
        assert label.minimumSizeHint().width() < label.sizeHint().width()

    def test_renders_at_every_width_without_error(self, qtbot: QtBot) -> None:
        """From wide enough to show the full string down to narrower
        than a single character — none of these should raise, which is
        what a paintEvent doing its own text measurement risks getting
        wrong at the edges."""
        label = ElidingLabel()
        qtbot.addWidget(label)
        label.setText(_LONG_TEXT)
        label.show()
        for width in (500, 120, 40, 1, 0):
            label.resize(width, 20)
            label.grab()

    def test_empty_text_renders_without_error(self, qtbot: QtBot) -> None:
        label = ElidingLabel()
        qtbot.addWidget(label)
        label.show()
        label.grab()


class TestStatusDot:
    def test_has_a_small_fixed_size(self, qtbot: QtBot) -> None:
        dot = StatusDot()
        qtbot.addWidget(dot)
        assert dot.size().width() == dot.size().height()
        assert 0 < dot.size().width() <= 12

    def test_renders_with_various_colors_without_error(self, qtbot: QtBot) -> None:
        dot = StatusDot()
        qtbot.addWidget(dot)
        dot.show()
        for color in ("#30d158", "#9a9aa0", "#ff453a", "not-a-real-color"):
            dot.set_color(color)
            dot.grab()
