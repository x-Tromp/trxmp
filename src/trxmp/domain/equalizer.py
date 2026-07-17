"""EQ bands and presets — the domain's core value objects.

A note on the guardrails below, because their history is the lesson.
They arrived from the Rust prototype justified by "professional
judgment": +9 dB is all a mastering engineer needs, Q below 0.1 is a
pointless near-flat tilt, 12 bands is plenty. Reasonable-sounding, and
invented in a vacuum.

Then M6 pointed the importers at a real Peace collection — 40 files a
real person actually uses — and the guardrails rejected 31 of them. Not
because the files were bad: because Peace routinely writes 10 Hz bands
(a shelf's corner sits below the audible range; its slope is what you
hear), Q values of 0.01 (a deliberate broad tilt), and 13-band presets.
The limits weren't protecting anyone. They were taste, dressed up as
expertise, silently deleting other people's work.

So each one now has to justify itself by physics, numerics, or evidence:

- **Frequency** [10 Hz, 20 kHz]: a *filter* may sit below hearing — what
  matters is where its slope lands. The floor is where real tools put
  theirs (Peace, Pro-Q), comfortably clear of the numerical trouble that
  only starts when w0 approaches zero.
- **Nyquist** (a separate, context-dependent check): real. RBJ
  coefficients genuinely destabilise as w0 approaches pi.
- **Gain** [-18, +12] dB: boosts eat headroom, and far past this a boost
  emphasises resonances rather than shaping balance. Cuts remove energy
  (no clipping risk) so the range is wider; narrow notches for
  driver-resonance correction can legitimately need -18 dB. The +12
  ceiling is still a judgment — but a mainstream one (it's the range
  most graphic EQs offer) rather than an idiosyncratic one, and the
  automatic headroom preamp is what makes a boost that large safe.
- **Q** [0.01, 10]: the floor is evidence (Peace uses 0.01 for wide
  tilts, and the maths is perfectly stable there). The ceiling is real:
  past Q≈10 a filter rings audibly on transients.

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

# Raised from 9.0 in M6: bass-boost presets in the wild reach +10, and a
# limit that rejects them while advertising automatic clipping protection
# is incoherent — the headroom preamp exists precisely so a boost this
# size is safe.
MAX_BOOST_DB = 12.0
MAX_CUT_DB = -18.0
# Lowered from 0.1 in M6: 8 of the user's own presets use Q=0.01 for a
# deliberate broad tilt, and the biquad maths is stable there (as Q
# falls, a peaking filter simply widens toward a flat gain).
MIN_Q = 0.01
MAX_Q = 10.0
# Lowered from 20 Hz in M6: 22 real Peace files place bands at 10 Hz.
# A filter is not a tone — its corner can sit below hearing while its
# slope shapes what you actually hear.
MIN_FREQUENCY_HZ = 10.0
MAX_FREQUENCY_HZ = 20_000.0

# Raised from 12 to 32 in M6, on evidence rather than taste. The old
# limit was inherited from the Rust prototype and never justified; when
# the importers met a real Peace collection it rejected 25 of 40 files —
# 23 of them ordinary 13-band presets, one a 31-band ISO third-octave
# graphic EQ. 32 covers that standard layout with room to spare, and the
# limit's real job is unchanged: stop a corrupt file claiming 100000
# bands, not enforce taste. Thirty-two biquads cost nothing (scipy runs
# them in compiled code, and Equalizer APO has no practical limit).
MAX_BANDS = 32
MIN_PREAMP_DB = -24.0
# Capped at 0 dB on purpose: this engine's job is to keep playback safe,
# not to make things louder. "Louder" is a loudness-normalization
# concern for a different part of the pipeline — never bundled into EQ.
MAX_PREAMP_DB = 0.0

# True-peak margin below 0 dBFS absorbing reconstruction-filter
# overshoot and inter-sample peaks that steady-state analysis can't see.
HEADROOM_SAFETY_MARGIN_DB = 0.5

_RESPONSE_SCAN_POINTS = 256

# The headroom scan's floor sits well below MIN_FREQUENCY_HZ on purpose,
# and this is a real bug fix rather than a tweak. A low shelf reaches its
# *full* boost below its corner frequency — at the corner itself it has
# only half of it. Scanning from the lowest legal band frequency would
# therefore find +6 dB on a +12 dB shelf and set the preamp 6 dB too
# high, and the clipping would land on subsonic content nobody can hear
# but every sample can overflow on. One hertz is far enough below any
# legal band for the plateau to be fully in view.
_ANALYSIS_FLOOR_HZ = 1.0


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

        The scan deliberately covers more than the audible range: it runs
        from :data:`_ANALYSIS_FLOOR_HZ` to just under Nyquist, because
        every one of those frequencies is a real sample that can really
        clip. Anything a shelf does out at the edges counts, whether or
        not a human would notice it directly.
        """
        if not self.bands:
            return 0.0

        highest_hz = sample_rate / 2.0 * 0.99
        frequencies = np.geomspace(_ANALYSIS_FLOOR_HZ, highest_hz, _RESPONSE_SCAN_POINTS)

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
