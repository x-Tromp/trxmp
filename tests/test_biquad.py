"""Tests for biquad design.

These deliberately mirror the tests the original Rust engine had, so we
know the Python port behaves identically before building on top of it.
Each test asserts a *property a professional would expect from an EQ*,
not an implementation detail — that's what keeps tests valuable when
the internals change.
"""

import numpy as np
import pytest

from eqgenius.dsp.biquad import design_peaking, magnitude_response_db

SAMPLE_RATE = 48_000.0


def test_peaking_filter_hits_target_gain_at_center_frequency() -> None:
    coefficients = design_peaking(SAMPLE_RATE, frequency_hz=1_000.0, gain_db=6.0, q=1.0)
    gain = magnitude_response_db(coefficients, np.array([1_000.0]), SAMPLE_RATE)
    assert gain[0] == pytest.approx(6.0, abs=0.05)


def test_zero_gain_peaking_filter_is_flat_everywhere() -> None:
    coefficients = design_peaking(SAMPLE_RATE, frequency_hz=1_000.0, gain_db=0.0, q=1.0)
    frequencies = np.array([50.0, 500.0, 1_000.0, 5_000.0, 15_000.0])
    gains = magnitude_response_db(coefficients, frequencies, SAMPLE_RATE)
    assert np.all(np.abs(gains) < 0.01)


def test_cut_mirrors_boost_so_they_cancel_out() -> None:
    """RBJ peaking filters are symmetric: +6 dB and -6 dB at the same
    frequency and Q must sum to a flat response. This symmetry is why
    an 'undo' of an EQ move sounds truly neutral."""
    boost = design_peaking(SAMPLE_RATE, 1_000.0, gain_db=6.0, q=1.0)
    cut = design_peaking(SAMPLE_RATE, 1_000.0, gain_db=-6.0, q=1.0)
    frequencies = np.geomspace(20.0, 20_000.0, 200)
    combined = magnitude_response_db(boost, frequencies, SAMPLE_RATE) + magnitude_response_db(
        cut, frequencies, SAMPLE_RATE
    )
    assert np.all(np.abs(combined) < 0.01)
