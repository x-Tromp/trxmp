"""Tests for biquad design.

These deliberately mirror the tests the original Rust engine had, so we
know the Python port behaves identically before building on top of it.
Each test asserts a *property a professional would expect from an EQ*,
not an implementation detail — that's what keeps tests valuable when
the internals change.
"""

import numpy as np
import pytest

from trxmp.dsp.biquad import FilterType, design, magnitude_response_db

SAMPLE_RATE = 48_000.0


def test_peaking_filter_hits_target_gain_at_center_frequency() -> None:
    coefficients = design(FilterType.PEAKING, SAMPLE_RATE, 1_000.0, gain_db=6.0, q=1.0)
    gain = magnitude_response_db(coefficients, np.array([1_000.0]), SAMPLE_RATE)
    assert gain[0] == pytest.approx(6.0, abs=0.05)


def test_zero_gain_peaking_filter_is_flat_everywhere() -> None:
    coefficients = design(FilterType.PEAKING, SAMPLE_RATE, 1_000.0, gain_db=0.0, q=1.0)
    frequencies = np.array([50.0, 500.0, 1_000.0, 5_000.0, 15_000.0])
    gains = magnitude_response_db(coefficients, frequencies, SAMPLE_RATE)
    assert np.all(np.abs(gains) < 0.01)


def test_cut_mirrors_boost_so_they_cancel_out() -> None:
    """RBJ peaking filters are symmetric: +6 dB and -6 dB at the same
    frequency and Q must sum to a flat response. This symmetry is why
    an 'undo' of an EQ move sounds truly neutral."""
    boost = design(FilterType.PEAKING, SAMPLE_RATE, 1_000.0, gain_db=6.0, q=1.0)
    cut = design(FilterType.PEAKING, SAMPLE_RATE, 1_000.0, gain_db=-6.0, q=1.0)
    frequencies = np.geomspace(20.0, 20_000.0, 200)
    combined = magnitude_response_db(boost, frequencies, SAMPLE_RATE) + magnitude_response_db(
        cut, frequencies, SAMPLE_RATE
    )
    assert np.all(np.abs(combined) < 0.01)


def test_high_shelf_boosts_treble_and_leaves_bass_alone() -> None:
    coefficients = design(FilterType.HIGH_SHELF, SAMPLE_RATE, 8_000.0, gain_db=6.0, q=0.7)
    bass = magnitude_response_db(coefficients, np.array([100.0]), SAMPLE_RATE)
    treble = magnitude_response_db(coefficients, np.array([15_000.0]), SAMPLE_RATE)
    assert abs(bass[0]) < 0.5, f"bass should be near-untouched, got {bass[0]} dB"
    assert treble[0] > 5.0, f"treble should be boosted close to target, got {treble[0]} dB"


def test_low_shelf_boosts_bass_and_leaves_treble_alone() -> None:
    coefficients = design(FilterType.LOW_SHELF, SAMPLE_RATE, 100.0, gain_db=6.0, q=0.7)
    bass = magnitude_response_db(coefficients, np.array([30.0]), SAMPLE_RATE)
    treble = magnitude_response_db(coefficients, np.array([5_000.0]), SAMPLE_RATE)
    assert bass[0] > 5.0
    assert abs(treble[0]) < 0.5


def test_low_pass_attenuates_highs_and_ignores_gain_parameter() -> None:
    """Pass filters are guardrails, not tonal shaping: their response
    must not depend on gain_db at all."""
    with_gain = design(FilterType.LOW_PASS, SAMPLE_RATE, 1_000.0, gain_db=9.0, q=0.7071)
    without_gain = design(FilterType.LOW_PASS, SAMPLE_RATE, 1_000.0, gain_db=0.0, q=0.7071)
    assert with_gain == without_gain

    frequencies = np.array([100.0, 10_000.0])
    response = magnitude_response_db(with_gain, frequencies, SAMPLE_RATE)
    assert abs(response[0]) < 0.5, "passband should be flat"
    assert response[1] < -30.0, "two decades above cutoff should be strongly attenuated"


def test_high_pass_attenuates_lows() -> None:
    coefficients = design(FilterType.HIGH_PASS, SAMPLE_RATE, 1_000.0, q=0.7071)
    frequencies = np.array([50.0, 10_000.0])
    response = magnitude_response_db(coefficients, frequencies, SAMPLE_RATE)
    assert response[0] < -30.0
    assert abs(response[1]) < 0.5
