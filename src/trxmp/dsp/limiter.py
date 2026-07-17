"""Lookahead peak limiter — the safety net, not the gain strategy.

The preset-level headroom analysis (``EqPreset.safe_preamp_db``) does
the real work of preventing clipping ahead of time. This limiter exists
because steady-state magnitude analysis can't fully predict transient
peaks from multiple bands summing in phase on real program material.
If the upstream headroom math is doing its job, this engages rarely and
by small amounts — and that design invariant is exactly what makes the
fast path below legitimate.

Channels are limited independently (same documented v1 simplification
as the original Rust engine): a hard-limiting event can shift the
stereo image by a hair. Linked detection is a straightforward future
improvement.
"""

from __future__ import annotations

import math

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from numpy.typing import NDArray


class Limiter:
    """Processes blocks of shape ``(frames, channels)`` in float64.

    Instant attack (a detected upcoming peak is never let through),
    exponential release. Adds ``latency_samples`` of delay — the
    lookahead that lets the gain come down *before* the peak arrives.
    """

    def __init__(
        self,
        sample_rate: float,
        num_channels: int,
        ceiling_db: float = -0.3,
        lookahead_ms: float = 1.5,
        release_ms: float = 50.0,
    ) -> None:
        lookahead = max(1, round((lookahead_ms / 1000.0) * sample_rate))
        self._lookahead = lookahead
        self._threshold = 10.0 ** (ceiling_db / 20.0)
        self._release_coeff = 1.0 - math.exp(-1.0 / ((release_ms / 1000.0) * sample_rate))
        # Delay line of exactly `lookahead` frames: output is the input
        # from `lookahead` frames ago, so the gain computed from the
        # *current* input applies before that peak reaches the output.
        self._delay: NDArray[np.float64] = np.zeros((lookahead, num_channels))
        # Tail of |x| needed so the first windows of the next block are
        # complete (a trailing sliding max needs lookahead-1 past samples).
        self._abs_tail: NDArray[np.float64] = np.zeros((lookahead - 1, num_channels))
        self._envelope: NDArray[np.float64] = np.ones(num_channels)

    @property
    def latency_samples(self) -> int:
        return self._lookahead

    def process_block(self, block: NDArray[np.float64]) -> NDArray[np.float64]:
        num_frames = block.shape[0]

        buffered = np.vstack([self._delay, block])
        delayed = buffered[:num_frames]
        self._delay = buffered[num_frames:]

        # Trailing sliding-window maximum of |x|, fully vectorized:
        # window n covers |x[n-lookahead+1 .. n]|, exactly like the
        # sample-by-sample VecDeque in the Rust version — but computed
        # for the whole block in one shot.
        abs_block = np.abs(block)
        padded = np.vstack([self._abs_tail, abs_block])
        if self._lookahead > 1:
            self._abs_tail = padded[-(self._lookahead - 1) :]
        windows = sliding_window_view(padded, self._lookahead, axis=0)
        peaks: NDArray[np.float64] = windows.max(axis=-1)

        # Per-sample target gain; np.divide's `where=` avoids ever
        # evaluating threshold/0 (silence) instead of filtering warnings
        # after the fact.
        target = np.ones_like(peaks)
        np.divide(self._threshold, peaks, out=target, where=peaks > self._threshold)

        # Fast path: nothing over threshold and the envelope fully
        # recovered means gain is exactly 1.0 for the whole block. With
        # correct upstream headroom this is the overwhelmingly common
        # case, so the sequential loop below rarely runs.
        if np.all(self._envelope >= 1.0) and np.all(target >= 1.0):
            return delayed

        # Slow path: the envelope recursion (instant attack, exponential
        # release) is a nonlinear recurrence — each sample depends on the
        # previous — so it cannot be expressed as a NumPy array op.
        gains = np.empty_like(target)
        envelope = self._envelope
        release = self._release_coeff
        for i in range(num_frames):
            frame_target = target[i]
            envelope = np.where(
                frame_target < envelope,
                frame_target,
                envelope + (frame_target - envelope) * release,
            )
            gains[i] = envelope
        self._envelope = envelope

        return delayed * gains
