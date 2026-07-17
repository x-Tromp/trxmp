"""Computing what the UI draws — the EQ's frequency response curve.

Lives in the application layer, not in the widget, for a reason: "what
does this preset do to the signal" is a question about the *audio*, not
about pixels. Keeping it here means the curve can be unit-tested with
no Qt in sight, and reused later by the spectrum analyzer view, a
report exporter, or a CLI plot.

Design note — the curve deliberately excludes the preamp. Every serious
EQ (Pro-Q, Peace, AutoEQ) draws the *shape* of the filtering and reports
gain staging as a separate number, because a curve that sinks 9 dB the
moment you boost one band is unreadable. The UI shows
``EqPreset.safe_preamp_db`` next to the curve instead.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from trxmp.domain.equalizer import MAX_FREQUENCY_HZ, MIN_FREQUENCY_HZ, EqPreset
from trxmp.dsp.biquad import design, magnitude_response_db

DEFAULT_SAMPLE_RATE_HZ = 48_000.0
DEFAULT_CURVE_POINTS = 256


@dataclass(frozen=True, slots=True)
class ResponseCurve:
    """A drawable curve: log-spaced frequencies and their combined gain."""

    frequencies_hz: NDArray[np.float64]
    magnitudes_db: NDArray[np.float64]


def compute_response_curve(
    preset: EqPreset,
    sample_rate: float = DEFAULT_SAMPLE_RATE_HZ,
    num_points: int = DEFAULT_CURVE_POINTS,
) -> ResponseCurve:
    """The cascade's combined magnitude response across the audible range.

    Log-spaced because hearing is logarithmic: an octave (20→40 Hz)
    deserves as much screen space as 10k→20k, which is exactly what a
    geometric grid gives us.
    """
    highest_hz = min(sample_rate / 2.0 * 0.99, MAX_FREQUENCY_HZ)
    frequencies = np.geomspace(MIN_FREQUENCY_HZ, highest_hz, num_points)

    total = np.zeros(num_points)
    for band in preset.bands:
        coefficients = design(
            band.filter_type, sample_rate, band.frequency_hz, band.gain_db, band.q
        )
        total += magnitude_response_db(coefficients, frequencies, sample_rate)

    return ResponseCurve(frequencies_hz=frequencies, magnitudes_db=total)
