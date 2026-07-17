"""WAV file reading/writing.

The rest of the app speaks exactly one audio dialect: float64 arrays of
shape ``(frames, channels)`` in [-1, 1]. This module is the *boundary*
that translates the messy outside world (mono files, int16/int32/uint8
PCM) into that dialect and back — boundary normalization keeps every
other layer free of format special-cases.
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import cast

import numpy as np
from numpy.typing import NDArray
from scipy.io import wavfile

# Normalization divisors per PCM dtype. uint8 WAVs are unsigned with
# midpoint 128 (a WAV format quirk), handled separately below.
_INT_SCALES = {
    np.dtype(np.int16): 32_768.0,
    np.dtype(np.int32): 2_147_483_648.0,
}


def load_wav(path: Path) -> tuple[NDArray[np.float64], int]:
    """Load a WAV as ``((frames, channels) float64 in [-1, 1], sample_rate)``."""
    with warnings.catch_warnings():
        # Real-world WAVs (e.g. everything in C:\Windows\Media) carry
        # metadata chunks scipy doesn't parse; it skips them correctly
        # but warns. Suppressing *only* this warning, *only* here: the
        # boundary absorbs the outside world's noise so callers don't.
        warnings.simplefilter("ignore", wavfile.WavFileWarning)
        result = wavfile.read(path)
    sample_rate = int(result[0])
    raw = np.asarray(result[1])

    if raw.ndim == 1:  # mono → (frames, 1), one shape for everyone downstream
        raw = raw[:, np.newaxis]

    if raw.dtype in _INT_SCALES:
        data = raw.astype(np.float64) / _INT_SCALES[raw.dtype]
    elif raw.dtype == np.uint8:
        data = (raw.astype(np.float64) - 128.0) / 128.0
    elif raw.dtype in (np.float32, np.float64):
        data = raw.astype(np.float64)
    else:
        raise ValueError(f"unsupported WAV sample format: {raw.dtype}")

    return data, sample_rate


def save_wav(path: Path, data: NDArray[np.float64], sample_rate: int) -> None:
    """Write ``(frames, channels)`` float audio as 16-bit PCM.

    16-bit because it's the format every player on earth handles. The
    clip is defensive: the engine already guarantees [-1, 1], but a file
    writer that *could* silently wrap around integer overflow must never
    trust its caller that much.
    """
    clipped = np.clip(data, -1.0, 1.0)
    pcm = cast(NDArray[np.int16], (clipped * 32_767.0).astype(np.int16))
    wavfile.write(path, sample_rate, pcm)
