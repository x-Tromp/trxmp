"""Widget tests — real Qt widgets, driven the way a user drives them.

These run on Qt's "offscreen" platform (see conftest.py), so they need
no display and work identically on a CI runner. pytest-qt's ``qtbot``
both manages widget lifetime and synthesizes real input events, which
means we're testing the actual event handlers rather than calling
private methods and hoping.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QWidget
from pytestqt.qtbot import QtBot

from trxmp.application.preferences import AccentColor, ThemeMode
from trxmp.domain.equalizer import EqBand, EqPreset
from trxmp.dsp.biquad import FilterType
from trxmp.ui.theme import Theme
from trxmp.ui.view_models import EqViewModel
from trxmp.ui.widgets.band_controls import BandControls
from trxmp.ui.widgets.eq_curve import EqCurveWidget


def _drag(qtbot: QtBot, widget: QWidget, start: QPoint, end: QPoint) -> None:
    """Press, move, release — one gesture, one typed entry point.

    pytest-qt's input helpers carry no annotations, so strict mypy flags
    every call. Funnelling them through here keeps the ignores in one
    place instead of scattered across a dozen tests — the same
    containment move we make for scipy — and reads better besides.
    """
    qtbot.mousePress(widget, Qt.MouseButton.LeftButton, pos=start)  # type: ignore[no-untyped-call]
    qtbot.mouseMove(widget, end)  # type: ignore[no-untyped-call]
    qtbot.mouseRelease(widget, Qt.MouseButton.LeftButton, pos=end)  # type: ignore[no-untyped-call]


def _double_click(qtbot: QtBot, widget: QWidget, position: QPoint) -> None:
    qtbot.mouseDClick(widget, Qt.MouseButton.LeftButton, pos=position)  # type: ignore[no-untyped-call]


@pytest.fixture
def model(qtbot: QtBot) -> EqViewModel:
    return EqViewModel()


@pytest.fixture
def curve(qtbot: QtBot, model: EqViewModel) -> EqCurveWidget:
    widget = EqCurveWidget(model, Theme().palette)
    qtbot.addWidget(widget)
    widget.resize(800, 320)
    widget.show()
    qtbot.waitExposed(widget)
    return widget


class TestEqCurveWidget:
    def test_renders_without_error(self, curve: EqCurveWidget) -> None:
        """A paintEvent that throws leaves a blank widget and a console
        traceback rather than a crash — so 'it painted at all' is worth
        asserting explicitly."""
        curve.grab()  # forces a synchronous paintEvent

    def test_renders_with_extreme_and_empty_presets(
        self, curve: EqCurveWidget, model: EqViewModel
    ) -> None:
        model.load(EqPreset.flat())
        curve.grab()
        model.load(
            EqPreset(
                bands=(
                    EqBand(FilterType.LOW_SHELF, 20.0, 9.0, 0.1),
                    EqBand(FilterType.HIGH_SHELF, 20_000.0, -18.0, 10.0),
                )
            )
        )
        curve.grab()

    def test_renders_when_powered_off(self, curve: EqCurveWidget, model: EqViewModel) -> None:
        model.set_band_gain(0, 6.0)
        model.set_powered(False)
        curve.grab()

    def test_dragging_a_handle_changes_gain_and_frequency(
        self, qtbot: QtBot, curve: EqCurveWidget, model: EqViewModel
    ) -> None:
        index = 4  # a mid band, far from the edges
        start = curve._handle_center(index).toPoint()

        _drag(qtbot, curve, start, start + QPoint(40, -30))  # right and up

        band = model.bands[index]
        assert band.gain_db > 0.0, "dragging up should boost"
        assert band.frequency_hz > 500.0, "dragging right should raise the frequency"

    def test_dragging_empty_space_changes_nothing(
        self, qtbot: QtBot, curve: EqCurveWidget, model: EqViewModel
    ) -> None:
        before = model.bands
        _drag(qtbot, curve, QPoint(60, 40), QPoint(200, 100))
        assert model.bands == before

    def test_drag_is_clamped_to_the_guardrails(
        self, qtbot: QtBot, curve: EqCurveWidget, model: EqViewModel
    ) -> None:
        """Dragging far past the top of the widget must saturate at
        +9 dB, not raise InvalidBandError in a paint loop."""
        index = 4
        start = curve._handle_center(index).toPoint()
        _drag(qtbot, curve, start, QPoint(start.x(), -500))
        assert model.bands[index].gain_db == 9.0

    def test_double_click_flattens_a_band(
        self, qtbot: QtBot, curve: EqCurveWidget, model: EqViewModel
    ) -> None:
        model.set_band_gain(2, 7.0)
        _double_click(qtbot, curve, curve._handle_center(2).toPoint())
        assert model.bands[2].gain_db == 0.0

    def test_widget_ignores_input_when_powered_off(
        self, qtbot: QtBot, curve: EqCurveWidget, model: EqViewModel
    ) -> None:
        position = curve._handle_center(3).toPoint()
        model.set_powered(False)
        _drag(qtbot, curve, position, position + QPoint(0, -40))
        assert model.bands[3].gain_db == 0.0

    def test_frequency_axis_is_logarithmic(self, curve: EqCurveWidget) -> None:
        """The defining property of the axis: equal ratios occupy equal
        widths, so 20→200 Hz spans the same pixels as 2k→20k."""
        first_decade = curve._freq_to_x(200.0) - curve._freq_to_x(20.0)
        last_decade = curve._freq_to_x(20_000.0) - curve._freq_to_x(2_000.0)
        assert first_decade == pytest.approx(last_decade, abs=0.5)

    def test_coordinate_mapping_roundtrips(self, curve: EqCurveWidget) -> None:
        for hz in (20.0, 440.0, 5_000.0, 20_000.0):
            assert curve._x_to_freq(curve._freq_to_x(hz)) == pytest.approx(hz, rel=1e-6)
        for db in (-9.0, 0.0, 6.0):
            assert curve._y_to_db(curve._db_to_y(db)) == pytest.approx(db, abs=1e-6)

    def test_theme_change_repaints_with_the_new_palette(self, curve: EqCurveWidget) -> None:
        curve.set_palette(Theme(ThemeMode.LIGHT, AccentColor.ORANGE).palette)
        curve.grab()

    def test_loading_a_smaller_preset_while_hovering_does_not_crash(
        self, qtbot: QtBot, curve: EqCurveWidget, model: EqViewModel
    ) -> None:
        """Regression: hover band 8, then load a one-band preset. The
        stale index used to point past the end of the new band list and
        raise IndexError inside paintEvent."""
        qtbot.mouseMove(curve, curve._handle_center(8).toPoint())  # type: ignore[no-untyped-call]
        model.load(EqPreset(bands=(EqBand(FilterType.PEAKING, 1_000.0, 3.0, 1.0),)))
        curve.grab()


class TestBandControls:
    def test_sliders_mirror_the_model(self, qtbot: QtBot, model: EqViewModel) -> None:
        controls = BandControls(model)
        qtbot.addWidget(controls)
        model.set_band_gain(0, 3.5)
        assert controls._sliders[0].slider.value() == 35  # tenths of a dB

    def test_moving_a_slider_updates_the_model(self, qtbot: QtBot, model: EqViewModel) -> None:
        controls = BandControls(model)
        qtbot.addWidget(controls)
        controls._sliders[2].slider.setValue(-45)
        assert model.bands[2].gain_db == -4.5

    def test_two_way_binding_does_not_loop_forever(self, qtbot: QtBot, model: EqViewModel) -> None:
        """If the guard against feedback were missing, this would hang
        or blow the recursion limit instead of finishing."""
        controls = BandControls(model)
        qtbot.addWidget(controls)
        for value in range(-90, 91, 10):
            controls._sliders[0].slider.setValue(value)
        assert model.bands[0].gain_db == 9.0

    def test_curve_and_sliders_stay_in_sync_through_the_model(
        self, qtbot: QtBot, model: EqViewModel
    ) -> None:
        """The MVVM payoff: two widgets that have never heard of each
        other, kept consistent by the model alone."""
        curve = EqCurveWidget(model, Theme().palette)
        controls = BandControls(model)
        qtbot.addWidget(curve)
        qtbot.addWidget(controls)
        curve.resize(800, 320)

        index = 4
        start = curve._handle_center(index).toPoint()
        _drag(qtbot, curve, start, QPoint(start.x(), start.y() - 25))

        expected = round(model.bands[index].gain_db * 10)
        assert controls._sliders[index].slider.value() == expected

    def test_loading_a_preset_rebuilds_the_bank_to_match(
        self, qtbot: QtBot, model: EqViewModel
    ) -> None:
        """Regression: an imported preset can have any number of bands.
        The panel must rebuild rather than assume the ten it started with."""
        controls = BandControls(model)
        qtbot.addWidget(controls)
        assert len(controls._sliders) == 10

        model.load(
            EqPreset(
                bands=(
                    EqBand(FilterType.PEAKING, 4_500.0, -3.0, 2.5),
                    EqBand(FilterType.HIGH_SHELF, 10_000.0, 1.5, 0.7),
                )
            )
        )

        assert len(controls._sliders) == 2
        assert controls._sliders[0].slider.value() == -30
        controls._sliders[1].slider.setValue(40)
        assert model.bands[1].gain_db == 4.0  # rebuilt sliders drive the right bands

    def test_slider_labels_track_frequency(self, qtbot: QtBot, model: EqViewModel) -> None:
        """Labels are the band's real frequency, so dragging a band
        sideways on the curve can't leave a lying label behind."""
        controls = BandControls(model)
        qtbot.addWidget(controls)
        assert controls._sliders[0].name_label.text() == "32"
        model.set_band_frequency(0, 4_500.0)
        assert controls._sliders[0].name_label.text() == "4.5k"

    def test_power_off_disables_the_sliders(self, qtbot: QtBot, model: EqViewModel) -> None:
        controls = BandControls(model)
        qtbot.addWidget(controls)
        model.set_powered(False)
        assert not controls._sliders[0].slider.isEnabled()
        model.set_powered(True)
        assert controls._sliders[0].slider.isEnabled()
