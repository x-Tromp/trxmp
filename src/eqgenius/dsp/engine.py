"""The block-based EQ engine: preamp → biquad cascade → limiter.

Deliberately consumes plain :class:`BiquadCoefficients` + a preamp, not
domain presets — the DSP layer must not know the domain exists. The
application layer translates ``EqPreset → (coefficients, safe preamp)``
and hands the result here.

Filtering uses ``scipy.signal.lfilter`` with explicit initial conditions
(``zi``): SciPy carries each filter's internal state across block
boundaries for us, in compiled code. Hand-rolling the per-sample
Transposed Direct Form II loop (as the Rust engine did) would be both
slower and easier to get wrong in Python — knowing when *not* to
reimplement is part of the engineering.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

import numpy as np
from numpy.typing import NDArray
from scipy.signal import lfilter

from eqgenius.dsp.biquad import BiquadCoefficients
from eqgenius.dsp.limiter import Limiter

# Long enough to be genuinely inaudible as a transition, short enough
# that a manual EQ tweak feels immediate rather than sluggish.
DEFAULT_CROSSFADE_MS = 50.0

# -0.3 dBFS ceiling leaves room for inter-sample peaks introduced by the
# playback chain's own reconstruction filtering.
DEFAULT_LIMITER_CEILING_DB = -0.3


class _Chain:
    """One preset's runtime state: preamp + cascade filter memories."""

    def __init__(
        self,
        coefficients: Sequence[BiquadCoefficients],
        preamp_db: float,
        num_channels: int,
    ) -> None:
        self._ba = [c.as_ba() for c in coefficients]
        # One zi per band, shape (2, channels): scipy filters all
        # channels of a (frames, channels) block in a single call.
        self._zi = [np.zeros((2, num_channels)) for _ in coefficients]
        self._preamp_linear = 10.0 ** (preamp_db / 20.0)

    def process(self, block: NDArray[np.float64]) -> NDArray[np.float64]:
        y: NDArray[np.float64] = block * self._preamp_linear
        for i, (b, a) in enumerate(self._ba):
            # cast: scipy is untyped; we contain the Any right here at
            # the boundary instead of letting it infect our signatures.
            y, self._zi[i] = cast(
                "tuple[NDArray[np.float64], NDArray[np.float64]]",
                lfilter(b, a, y, axis=0, zi=self._zi[i]),
            )
        return y


class EqEngine:
    """Real-time-capable equalizer for interleaved-block audio.

    Blocks are ``(frames, channels)`` float64 arrays. Preset changes via
    :meth:`apply` are crossfaded so they never click; the engine starts
    in true bypass (flat, unity gain).
    """

    def __init__(
        self,
        sample_rate: float,
        num_channels: int,
        crossfade_ms: float = DEFAULT_CROSSFADE_MS,
        limiter_ceiling_db: float = DEFAULT_LIMITER_CEILING_DB,
    ) -> None:
        if sample_rate <= 0:
            raise ValueError(f"sample_rate must be positive, got {sample_rate}")
        if num_channels < 1:
            raise ValueError(f"num_channels must be >= 1, got {num_channels}")

        self._sample_rate = sample_rate
        self._num_channels = num_channels
        self._current = _Chain((), preamp_db=0.0, num_channels=num_channels)
        self._fading_out: _Chain | None = None
        self._fade_elapsed = 0
        self._fade_total = max(1, round((crossfade_ms / 1000.0) * sample_rate))
        self._limiter = Limiter(sample_rate, num_channels, ceiling_db=limiter_ceiling_db)

    @property
    def latency_samples(self) -> int:
        """Pipeline latency (the limiter's lookahead). The crossfade
        blends in place and adds none."""
        return self._limiter.latency_samples

    def apply(
        self,
        coefficients: Sequence[BiquadCoefficients],
        preamp_db: float,
        *,
        immediate: bool = False,
    ) -> None:
        """Swap in a new filter cascade.

        Crossfaded by default (click-free live tweaking). ``immediate``
        skips the fade — for offline processing, where you want the new
        curve from sample zero. Known v1 limitation (same as the Rust
        engine): applying mid-fade drops the outgoing chain abruptly.
        """
        new_chain = _Chain(coefficients, preamp_db, self._num_channels)
        if immediate:
            self._current = new_chain
            self._fading_out = None
            return
        self._fading_out = self._current
        self._current = new_chain
        self._fade_elapsed = 0

    def process_block(self, block: NDArray[np.float64]) -> NDArray[np.float64]:
        """EQ one block. Returns a new array; does not mutate the input."""
        data = np.asarray(block, dtype=np.float64)
        if data.ndim != 2 or data.shape[1] != self._num_channels:
            raise ValueError(
                f"expected block of shape (frames, {self._num_channels}), got {data.shape}"
            )

        y = self._current.process(data)

        if self._fading_out is not None:
            old_y = self._fading_out.process(data)
            num_frames = data.shape[0]
            # Linear ramp continuing from wherever the previous block
            # left off — the whole fade computed as one array op.
            positions = np.arange(num_frames, dtype=np.float64) + self._fade_elapsed
            blend = np.minimum(positions / self._fade_total, 1.0)[:, np.newaxis]
            y = old_y * (1.0 - blend) + y * blend
            self._fade_elapsed += num_frames
            if self._fade_elapsed >= self._fade_total:
                self._fading_out = None

        y = self._limiter.process_block(y)

        # Defensive final clamp, mirroring the Rust engine: the limiter
        # already enforces the ceiling; this guards float edge cases.
        return np.clip(y, -1.0, 1.0)
