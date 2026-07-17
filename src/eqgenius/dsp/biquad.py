"""Biquad (second-order IIR) filter design and analysis.

Every EQ band in this application is ultimately one of these filters.
Formulas follow Robert Bristow-Johnson's "Audio EQ Cookbook", the
industry-standard reference for parametric EQ filters — the same source
the original Rust engine used, which lets us cross-check results.

Milestone 0 ships only the peaking ("bell") filter as a walking
skeleton; shelves, passes, and notches arrive in Milestone 1.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray


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


def design_peaking(
    sample_rate: float, frequency_hz: float, gain_db: float, q: float
) -> BiquadCoefficients:
    """Design an RBJ peaking ("bell") filter.

    A peaking filter boosts or cuts ``gain_db`` decibels at
    ``frequency_hz``, with ``q`` controlling how narrow the bell is,
    and leaves frequencies far from the center untouched.
    """
    w0 = 2.0 * math.pi * frequency_hz / sample_rate
    cos_w0 = math.cos(w0)
    alpha = math.sin(w0) / (2.0 * q)
    a = 10.0 ** (gain_db / 40.0)

    b0 = 1.0 + alpha * a
    b1 = -2.0 * cos_w0
    b2 = 1.0 - alpha * a
    a0 = 1.0 + alpha / a
    a1 = -2.0 * cos_w0
    a2 = 1.0 - alpha / a
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
