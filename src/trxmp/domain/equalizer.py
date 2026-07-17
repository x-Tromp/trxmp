"""EQ bands and presets — the domain's core value objects.

Guardrails (ported from the Rust engine, with the same rationale):
- Boosts beyond +9 dB are rarely used by mastering engineers; past that
  a boost emphasizes resonances rather than correcting balance, and it
  eats headroom fast when bands overlap.
- Cuts remove energy (no clipping risk), so the range is wider; narrow
  notches for driver-resonance correction can legitimately need -18 dB.
- Q outside [0.1, 10] is either a near-flat tilt (redundant with a
  shelf) or risks audible ringing on transients.

Python-specific design choice: guardrails are enforced in
``__post_init__``, so an out-of-range band *cannot exist* — versus the
Rust engine's construct-then-``validate()`` flow. "Make invalid states
unrepresentable" beats "remember to validate". The one check that can't
live there is the Nyquist limit, because it depends on a sample rate the
band doesn't know — hence :meth:`validate_for_sample_rate`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from trxmp.domain.errors import InvalidBandError, InvalidPresetError
from trxmp.dsp.biquad import FilterType, design, magnitude_response_db

MAX_BOOST_DB = 9.0
MAX_CUT_DB = -18.0
MIN_Q = 0.1
MAX_Q = 10.0
MIN_FREQUENCY_HZ = 20.0
MAX_FREQUENCY_HZ = 20_000.0

MAX_BANDS = 12
MIN_PREAMP_DB = -24.0
# Capped at 0 dB on purpose: this engine's job is to keep playback safe,
# not to make things louder. "Louder" is a loudness-normalization
# concern for a different part of the pipeline — never bundled into EQ.
MAX_PREAMP_DB = 0.0

# True-peak margin below 0 dBFS absorbing reconstruction-filter
# overshoot and inter-sample peaks that steady-state analysis can't see.
HEADROOM_SAFETY_MARGIN_DB = 0.5

_RESPONSE_SCAN_POINTS = 256


@dataclass(frozen=True, slots=True)
class EqBand:
    """A single parametric EQ band: one filter, fully specified."""

    filter_type: FilterType
    frequency_hz: float
    gain_db: float
    q: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.frequency_hz) or not (
            MIN_FREQUENCY_HZ <= self.frequency_hz <= MAX_FREQUENCY_HZ
        ):
            raise InvalidBandError(
                f"band frequency {self.frequency_hz!r} Hz is outside the audible "
                f"range [{MIN_FREQUENCY_HZ}, {MAX_FREQUENCY_HZ}] Hz"
            )
        if not math.isfinite(self.gain_db) or not (MAX_CUT_DB <= self.gain_db <= MAX_BOOST_DB):
            raise InvalidBandError(
                f"band gain {self.gain_db!r} dB is outside the professional "
                f"guardrail range [{MAX_CUT_DB}, {MAX_BOOST_DB}] dB"
            )
        if not math.isfinite(self.q) or not (MIN_Q <= self.q <= MAX_Q):
            raise InvalidBandError(
                f"band Q {self.q!r} is outside the safe range [{MIN_Q}, {MAX_Q}]"
            )

    def validate_for_sample_rate(self, sample_rate: float) -> None:
        """Reject bands at/above ~Nyquist, where RBJ coefficient math
        becomes numerically unstable (we stay 1% below)."""
        max_safe_hz = sample_rate / 2.0 * 0.99
        if self.frequency_hz > max_safe_hz:
            raise InvalidBandError(
                f"band frequency {self.frequency_hz} Hz is too close to Nyquist "
                f"for sample rate {sample_rate} Hz (max safe: {max_safe_hz:.0f} Hz)"
            )


@dataclass(frozen=True, slots=True)
class EqPreset:
    """An ordered set of bands plus a requested preamp.

    ``bands`` is a tuple, not a list: a frozen dataclass holding a list
    is only *shallowly* immutable — anyone could still ``append`` to it.
    The tuple makes immutability real, which is what lets presets be
    shared, cached, and compared by value without defensive copying.

    The engine never trusts ``requested_preamp_db`` alone:
    :meth:`safe_preamp_db` recomputes what the cascade actually needs
    and uses whichever is lower.
    """

    bands: tuple[EqBand, ...] = ()
    requested_preamp_db: float = 0.0

    def __post_init__(self) -> None:
        if len(self.bands) > MAX_BANDS:
            raise InvalidPresetError(
                f"preset has {len(self.bands)} bands, exceeding the maximum of {MAX_BANDS}"
            )
        if not math.isfinite(self.requested_preamp_db) or not (
            MIN_PREAMP_DB <= self.requested_preamp_db <= MAX_PREAMP_DB
        ):
            raise InvalidPresetError(
                f"preamp {self.requested_preamp_db!r} dB is outside the allowed "
                f"range [{MIN_PREAMP_DB}, {MAX_PREAMP_DB}] dB"
            )

    @classmethod
    def flat(cls, requested_preamp_db: float = 0.0) -> EqPreset:
        return cls(bands=(), requested_preamp_db=requested_preamp_db)

    def validate_for_sample_rate(self, sample_rate: float) -> None:
        for band in self.bands:
            band.validate_for_sample_rate(sample_rate)

    def peak_response_db(self, sample_rate: float) -> float:
        """Worst-case (highest) combined gain of the cascade anywhere in
        the audible range, scanned on a log-spaced grid.

        This — not naively summing each band's gain_db — is the real,
        signal-independent way to know how much headroom a preset needs:
        naive summing over-corrects when bands don't overlap and
        under-corrects when they do.
        """
        if not self.bands:
            return 0.0

        highest_hz = min(sample_rate / 2.0 * 0.99, MAX_FREQUENCY_HZ)
        frequencies = np.geomspace(MIN_FREQUENCY_HZ, highest_hz, _RESPONSE_SCAN_POINTS)

        total = np.zeros(_RESPONSE_SCAN_POINTS)
        for band in self.bands:
            coefficients = design(
                band.filter_type, sample_rate, band.frequency_hz, band.gain_db, band.q
            )
            total += magnitude_response_db(coefficients, frequencies, sample_rate)
        return float(total.max())

    def safe_preamp_db(self, sample_rate: float) -> float:
        """The preamp the engine should actually apply: the lower (more
        attenuation) of what was requested and what the cascade's own
        peak response demands for clip-free playback, minus the margin."""
        peak = self.peak_response_db(sample_rate)
        required = -(peak + HEADROOM_SAFETY_MARGIN_DB) if peak > 0.0 else -HEADROOM_SAFETY_MARGIN_DB
        return min(self.requested_preamp_db, required)


# The classic ten-band graphic layout: one band per ISO octave centre,
# with shelves at the extremes so the lowest/highest controls tilt
# everything beyond them — a bell at 32 Hz would leave 20-25 Hz almost
# untouched, which is not what someone dragging the lowest control
# expects. It's a starting point, not a constraint: bands can be moved
# anywhere afterwards, and imported presets may have any layout at all.
GRAPHIC_EQ_LAYOUT: tuple[tuple[FilterType, float, float], ...] = (
    (FilterType.LOW_SHELF, 32.0, 0.7),
    (FilterType.PEAKING, 64.0, 1.0),
    (FilterType.PEAKING, 125.0, 1.0),
    (FilterType.PEAKING, 250.0, 1.2),
    (FilterType.PEAKING, 500.0, 1.2),
    (FilterType.PEAKING, 1_000.0, 1.2),
    (FilterType.PEAKING, 2_000.0, 1.2),
    (FilterType.PEAKING, 4_000.0, 1.0),
    (FilterType.PEAKING, 8_000.0, 1.0),
    (FilterType.HIGH_SHELF, 16_000.0, 0.7),
)


def default_graphic_preset() -> EqPreset:
    """A flat ten-band graphic EQ — the app's starting point."""
    return EqPreset(
        bands=tuple(
            EqBand(filter_type, frequency_hz, 0.0, q)
            for filter_type, frequency_hz, q in GRAPHIC_EQ_LAYOUT
        )
    )
