"""View model tests — state, clamping, and signals.

These need a QApplication (QObject/Signal), which pytest-qt's ``qapp``
fixture provides, but no windows: the model is Qt-aware, not visual.
"""

from __future__ import annotations

import pytest
from pytestqt.qtbot import QtBot

from trxmp.domain.equalizer import (
    MAX_BOOST_DB,
    MAX_CUT_DB,
    MAX_FREQUENCY_HZ,
    MAX_Q,
    MIN_FREQUENCY_HZ,
    MIN_Q,
    EqBand,
    EqPreset,
    default_graphic_preset,
)
from trxmp.dsp.biquad import FilterType
from trxmp.ui.view_models import EqViewModel


@pytest.fixture
def model(qtbot: QtBot) -> EqViewModel:
    return EqViewModel()


def test_starts_from_the_flat_ten_band_layout(model: EqViewModel) -> None:
    assert len(model.bands) == 10
    assert all(band.gain_db == 0.0 for band in model.bands)
    assert model.powered is True


def test_bands_property_returns_an_immutable_snapshot(model: EqViewModel) -> None:
    assert isinstance(model.bands, tuple)


def test_setting_gain_emits_and_updates(qtbot: QtBot, model: EqViewModel) -> None:
    with qtbot.waitSignal(model.bands_changed):
        model.set_band_gain(0, 4.5)
    assert model.bands[0].gain_db == 4.5


def test_setting_the_same_gain_emits_nothing(qtbot: QtBot, model: EqViewModel) -> None:
    """Repaints are cheap but not free; a drag that doesn't move the
    band shouldn't cost one."""
    model.set_band_gain(0, 3.0)
    with qtbot.assertNotEmitted(model.bands_changed):
        model.set_band_gain(0, 3.0)


def test_gain_is_clamped_to_the_domain_guardrails(model: EqViewModel) -> None:
    """Clamp at the UI, reject in the domain: dragging past the limit
    should stop at the limit, never raise an error at the user."""
    model.set_band_gain(0, 99.0)
    assert model.bands[0].gain_db == MAX_BOOST_DB
    model.set_band_gain(0, -99.0)
    assert model.bands[0].gain_db == MAX_CUT_DB


def test_q_is_clamped(model: EqViewModel) -> None:
    model.set_band_q(0, 500.0)
    assert model.bands[0].q == MAX_Q
    model.set_band_q(0, 0.0001)
    assert model.bands[0].q == MIN_Q


def test_frequency_is_clamped_to_the_domains_range(model: EqViewModel) -> None:
    model.set_band_frequency(0, 0.5)
    assert model.bands[0].frequency_hz == MIN_FREQUENCY_HZ
    model.set_band_frequency(0, 96_000.0)
    assert model.bands[0].frequency_hz == MAX_FREQUENCY_HZ


def test_preamp_clamps_and_emits(qtbot: QtBot, model: EqViewModel) -> None:
    with qtbot.waitSignal(model.preamp_changed):
        model.set_preamp(-6.0)
    assert model.preamp_db == -6.0
    model.set_preamp(10.0)  # positive preamp is not a thing here
    assert model.preamp_db == 0.0


def test_editing_a_band_preserves_its_other_parameters(model: EqViewModel) -> None:
    original = model.bands[3]
    model.set_band_gain(3, 2.0)
    updated = model.bands[3]
    assert updated.gain_db == 2.0
    assert updated.frequency_hz == original.frequency_hz
    assert updated.q == original.q
    assert updated.filter_type == original.filter_type


def test_to_preset_produces_a_valid_domain_preset(model: EqViewModel) -> None:
    model.set_band_gain(0, 5.0)
    model.set_preamp(-2.0)
    preset = model.to_preset()
    assert isinstance(preset, EqPreset)
    assert preset.requested_preamp_db == -2.0
    assert preset.bands[0].gain_db == 5.0


def test_effective_preset_is_flat_when_powered_off(model: EqViewModel) -> None:
    """Bypass must be real bypass, not a curve nobody's looking at."""
    model.set_band_gain(0, 8.0)
    model.set_powered(False)
    assert model.effective_preset().bands == ()
    model.set_powered(True)
    assert model.effective_preset().bands[0].gain_db == 8.0


def test_load_replaces_state_and_announces_it(qtbot: QtBot, model: EqViewModel) -> None:
    preset = EqPreset(
        bands=(EqBand(FilterType.PEAKING, 500.0, -4.0, 2.0),), requested_preamp_db=-3.0
    )
    with qtbot.waitSignal(model.preset_loaded):
        model.load(preset)
    assert len(model.bands) == 1
    assert model.preamp_db == -3.0


def test_reset_returns_to_the_default_layout(model: EqViewModel) -> None:
    model.load(EqPreset(bands=(EqBand(FilterType.PEAKING, 500.0, -4.0, 2.0),)))
    model.reset()
    assert model.bands == default_graphic_preset().bands


def test_power_signal_only_fires_on_change(qtbot: QtBot, model: EqViewModel) -> None:
    with qtbot.waitSignal(model.powered_changed):
        model.set_powered(False)
    with qtbot.assertNotEmitted(model.powered_changed):
        model.set_powered(False)
