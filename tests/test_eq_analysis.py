"""Tests for the response curve the UI draws."""

from __future__ import annotations

import numpy as np
import pytest

from trxmp.application.eq_analysis import compute_response_curve
from trxmp.domain.equalizer import EqBand, EqPreset, default_graphic_preset
from trxmp.dsp.biquad import FilterType


def test_flat_preset_is_a_flat_line_at_zero() -> None:
    curve = compute_response_curve(EqPreset.flat())
    assert np.allclose(curve.magnitudes_db, 0.0)


def test_default_graphic_preset_starts_flat() -> None:
    """Ten bands at 0 dB must sum to silence-shaped nothing — if the
    default layout coloured the sound before the user touched anything,
    that would be a bug you'd never notice by ear."""
    curve = compute_response_curve(default_graphic_preset())
    assert np.max(np.abs(curve.magnitudes_db)) < 0.01


def test_frequencies_are_log_spaced_and_span_the_audible_range() -> None:
    curve = compute_response_curve(EqPreset.flat(), num_points=64)
    assert curve.frequencies_hz[0] == pytest.approx(20.0)
    assert curve.frequencies_hz[-1] == pytest.approx(20_000.0, rel=0.02)
    # Log spacing = constant ratio between neighbours.
    ratios = curve.frequencies_hz[1:] / curve.frequencies_hz[:-1]
    assert np.allclose(ratios, ratios[0])


def test_a_boost_shows_up_as_a_bump_at_its_frequency() -> None:
    preset = EqPreset(bands=(EqBand(FilterType.PEAKING, 1_000.0, 6.0, 1.0),))
    curve = compute_response_curve(preset, num_points=512)
    peak_index = int(np.argmax(curve.magnitudes_db))
    assert curve.frequencies_hz[peak_index] == pytest.approx(1_000.0, rel=0.05)
    assert curve.magnitudes_db[peak_index] == pytest.approx(6.0, abs=0.1)


def test_curve_excludes_preamp_by_design() -> None:
    """The curve draws the filter shape; gain staging is reported
    separately. A requested preamp must not move the line."""
    bands = (EqBand(FilterType.PEAKING, 1_000.0, 6.0, 1.0),)
    without = compute_response_curve(EqPreset(bands=bands))
    with_preamp = compute_response_curve(EqPreset(bands=bands, requested_preamp_db=-6.0))
    np.testing.assert_allclose(without.magnitudes_db, with_preamp.magnitudes_db)


def test_curve_matches_the_domains_own_peak_calculation() -> None:
    """The drawn curve and the headroom engine must agree — if they
    ever diverge, the UI is lying about what the audio will do."""
    preset = EqPreset(
        bands=(
            EqBand(FilterType.PEAKING, 900.0, 5.0, 1.0),
            EqBand(FilterType.PEAKING, 1_100.0, 5.0, 1.0),
        )
    )
    curve = compute_response_curve(preset, num_points=256)
    assert float(np.max(curve.magnitudes_db)) == pytest.approx(
        preset.peak_response_db(48_000.0), abs=0.01
    )
