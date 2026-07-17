"""Tests for the preset -> engine-arguments translation shared by the
offline WAV processor and Lab mode's live pipeline.
"""

from __future__ import annotations

import pytest

from trxmp.application.live_engine import resolve_preset_for_engine
from trxmp.domain.equalizer import EqBand, EqPreset
from trxmp.domain.errors import InvalidBandError
from trxmp.dsp.biquad import FilterType

SAMPLE_RATE = 48_000.0


def test_a_flat_preset_resolves_to_no_bands_and_the_margin_preamp() -> None:
    coefficients, preamp_db = resolve_preset_for_engine(EqPreset.flat(), SAMPLE_RATE)
    assert coefficients == []
    assert preamp_db == pytest.approx(-0.5, abs=0.01)


def test_coefficient_count_matches_band_count() -> None:
    preset = EqPreset(
        bands=(
            EqBand(FilterType.LOW_SHELF, 60.0, 3.0, 0.7),
            EqBand(FilterType.PEAKING, 1_000.0, -3.0, 1.5),
        )
    )
    coefficients, _ = resolve_preset_for_engine(preset, SAMPLE_RATE)
    assert len(coefficients) == 2


def test_the_returned_preamp_is_the_safe_one_not_the_requested_one() -> None:
    """The whole point of this function: callers get what EqEngine
    actually needs, not the raw, untrusted value a preset asked for."""
    preset = EqPreset(
        bands=(EqBand(FilterType.PEAKING, 1_000.0, 6.0, 1.0),), requested_preamp_db=0.0
    )
    _, preamp_db = resolve_preset_for_engine(preset, SAMPLE_RATE)
    assert preamp_db == pytest.approx(preset.safe_preamp_db(SAMPLE_RATE))
    assert preamp_db < 0.0


def test_a_band_too_close_to_nyquist_for_this_rate_is_rejected() -> None:
    """validate_for_sample_rate is context-dependent (M2's lesson): a
    band legal at 48 kHz can be illegal at a lower rate, and this
    function is exactly where that check has to run before any filter
    design is attempted."""
    preset = EqPreset(bands=(EqBand(FilterType.PEAKING, 19_000.0, 3.0, 1.0),))
    with pytest.raises(InvalidBandError, match="Nyquist"):
        resolve_preset_for_engine(preset, 32_000.0)
