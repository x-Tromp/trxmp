"""The audio capture interface — what the analyzer needs from the OS.

Same Protocol pattern as every other boundary in the app: the analyzer
consumes this, infrastructure implements it with WASAPI loopback, and
tests hand in a fake that returns synthesized blocks.

One WASAPI reality is baked into the contract: **loopback capture goes
quiet when nothing is playing.** The OS simply stops delivering packets,
so "no new data" is a normal, frequent state — not an error. That's why
``read_latest`` returns ``None`` rather than blocking or raising: the
caller is expected to decay its display toward silence, exactly like a
hardware analyzer's needles falling.
"""

from __future__ import annotations

from typing import Protocol

import numpy as np
from numpy.typing import NDArray


class AudioCaptureSource(Protocol):
    """A source of the system's playback audio, read-only."""

    @property
    def sample_rate(self) -> int: ...

    def start(self) -> bool:
        """Begin capturing. False (not an exception) when the OS refused
        — a machine with no loopback support still has a working EQ, so
        the analyzer degrades to 'off' instead of taking the app down."""
        ...

    def stop(self) -> None: ...

    def read_latest(self, num_frames: int) -> NDArray[np.float32] | None:
        """The most recent ``num_frames`` of mono audio, or ``None`` if
        nothing new arrived since the last read."""
        ...
