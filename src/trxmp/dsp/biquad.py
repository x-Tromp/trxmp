"""Biquad (second-order IIR) filter design and analysis.

Every EQ band in this application is ultimately one of these filters.
Formulas follow Robert Bristow-Johnson's "Audio EQ Cookbook", the
industry-standard reference for parametric EQ filters — the same source
the original Rust engine used, which lets us cross-check results.

Design rule for this module: pure functions and immutable values only.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import assert_never

import numpy as np
from numpy.typing import NDArray


class FilterType(StrEnum):
    """Filter shapes available for a single EQ band.

    ``PEAKING`` is the workhorse parametric "bell". Shelves handle broad
    tonal tilts (headphone bass/treble correction). ``LOW_PASS`` /
    ``HIGH_PASS`` are guardrails (e.g. rolling off content a driver
    can't reproduce cleanly), not creative shaping — they ignore gain.

    A ``StrEnum`` so members serialize to readable strings ("peaking")
    for free when presets become JSON in Milestone 2.
    """

    PEAKING = "peaking"
    LOW_SHELF = "low_shelf"
    HIGH_SHELF = "high_shelf"
    LOW_PASS = "low_pass"
    HIGH_PASS = "high_pass"


@dataclass(frozen=True, slots=True)
class BiquadCoefficients:
    """Coefficients for one second-order section, normalized so a0 == 1.

    Frozen because coefficients are a *value*: once designed they are
    never mutated, only replaced by a new design. Immutability makes
    them safe to share across threads (the future audio callback) for free.
    """

    b0: float
    b1: float
    b2: float
    a1: float
    a2: float

    def as_ba(self) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        """Coefficients in the ``(b, a)`` array form SciPy's filters expect."""
        b = np.array([self.b0, self.b1, self.b2], dtype=np.float64)
        a = np.array([1.0, self.a1, self.a2], dtype=np.float64)
        return b, a


def design(
    filter_type: FilterType,
    sample_rate: float,
    frequency_hz: float,
    gain_db: float = 0.0,
    q: float = 0.7071,
) -> BiquadCoefficients:
    """Design one RBJ biquad. ``gain_db`` is ignored for pass filters.

    ``match`` mirrors the Rust engine's exhaustive ``match`` on
    ``FilterType``; ``assert_never`` makes mypy prove at type-check time
    that every variant is handled — add a sixth filter type and this
    function fails CI until you implement it.
    """
    w0 = 2.0 * math.pi * frequency_hz / sample_rate
    cos_w0 = math.cos(w0)
    alpha = math.sin(w0) / (2.0 * q)
    a = 10.0 ** (gain_db / 40.0)
    sqrt_a = math.sqrt(a)

    match filter_type:
        case FilterType.PEAKING:
            b0 = 1.0 + alpha * a
            b1 = -2.0 * cos_w0
            b2 = 1.0 - alpha * a
            a0 = 1.0 + alpha / a
            a1 = -2.0 * cos_w0
            a2 = 1.0 - alpha / a
        case FilterType.LOW_SHELF:
            b0 = a * ((a + 1.0) - (a - 1.0) * cos_w0 + 2.0 * sqrt_a * alpha)
            b1 = 2.0 * a * ((a - 1.0) - (a + 1.0) * cos_w0)
            b2 = a * ((a + 1.0) - (a - 1.0) * cos_w0 - 2.0 * sqrt_a * alpha)
            a0 = (a + 1.0) + (a - 1.0) * cos_w0 + 2.0 * sqrt_a * alpha
            a1 = -2.0 * ((a - 1.0) + (a + 1.0) * cos_w0)
            a2 = (a + 1.0) + (a - 1.0) * cos_w0 - 2.0 * sqrt_a * alpha
        case FilterType.HIGH_SHELF:
            b0 = a * ((a + 1.0) + (a - 1.0) * cos_w0 + 2.0 * sqrt_a * alpha)
            b1 = -2.0 * a * ((a - 1.0) + (a + 1.0) * cos_w0)
            b2 = a * ((a + 1.0) + (a - 1.0) * cos_w0 - 2.0 * sqrt_a * alpha)
            a0 = (a + 1.0) - (a - 1.0) * cos_w0 + 2.0 * sqrt_a * alpha
            a1 = 2.0 * ((a - 1.0) - (a + 1.0) * cos_w0)
            a2 = (a + 1.0) - (a - 1.0) * cos_w0 - 2.0 * sqrt_a * alpha
        case FilterType.LOW_PASS:
            b0 = (1.0 - cos_w0) / 2.0
            b1 = 1.0 - cos_w0
            b2 = (1.0 - cos_w0) / 2.0
            a0 = 1.0 + alpha
            a1 = -2.0 * cos_w0
            a2 = 1.0 - alpha
        case FilterType.HIGH_PASS:
            b0 = (1.0 + cos_w0) / 2.0
            b1 = -(1.0 + cos_w0)
            b2 = (1.0 + cos_w0) / 2.0
            a0 = 1.0 + alpha
            a1 = -2.0 * cos_w0
            a2 = 1.0 - alpha
        case _ as unreachable:
            assert_never(unreachable)

    return BiquadCoefficients(b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0)


def magnitude_response_db(
    coefficients: BiquadCoefficients,
    frequencies_hz: NDArray[np.float64],
    sample_rate: float,
) -> NDArray[np.float64]:
    """Steady-state gain of the filter, in dB, at each requested frequency.

    Evaluates the transfer function
    ``H(z) = (b0 + b1*z^-1 + b2*z^-2) / (1 + a1*z^-1 + a2*z^-2)``
    on the unit circle ``z = e^{jw}``.

    Vectorized: one call computes an entire response curve. This is the
    NumPy idiom — instead of looping per frequency point (as a C or Rust
    implementation would), we push the loop down into compiled code by
    operating on whole arrays.
    """
    w = 2.0 * np.pi * frequencies_hz / sample_rate
    z1 = np.exp(-1j * w)
    z2 = np.exp(-2j * w)

    c = coefficients
    numerator = c.b0 + c.b1 * z1 + c.b2 * z2
    denominator = 1.0 + c.a1 * z1 + c.a2 * z2
    magnitude = np.abs(numerator / denominator)

    # Floor before log10: a perfect notch has magnitude 0, and log10(0)
    # would emit -inf plus a runtime warning. -240 dB is "silence" for
    # any practical purpose.
    result: NDArray[np.float64] = 20.0 * np.log10(np.maximum(magnitude, 1e-12))
    return result
