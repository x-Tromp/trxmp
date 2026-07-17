"""Spectrum analysis — turning a block of samples into band magnitudes.

Pure functions, same contract as the rest of ``trxmp.dsp``: no state, no
I/O, no Qt. The live analyzer is this module fed by a capture source and
drawn by a widget; this file is the only part with any math in it, which
is exactly why it's the part with exhaustive tests.

Design notes:

**Log-spaced bands, not raw FFT bins.** An FFT's bins are linearly
spaced, so of 2048 bins at 48 kHz, three cover the entire bass octave
20-40 Hz while a thousand cover the top octave nobody can resolve by
ear. Grouping bins into geometrically spaced bands matches both hearing
and the EQ curve's own axis — and because the bands are geometric, their
centres land *uniformly* across a log frequency axis, which makes the
widget's job trivial.

**Peak per band, not average.** Within each band we take the loudest
bin. Averaging dilutes a pure tone across whatever else the band holds,
which reads as "my 1 kHz test tone shows quieter than it is". Peak keeps
tones honest; the difference for broadband material is cosmetic.

**Hann window with amplitude correction.** The window stops spectral
leakage from smearing tones across bands; the ``2 / sum(window)``
normalisation makes a full-scale sine read 0 dBFS, so the analyzer's
numbers mean something absolute rather than "bigger is louder".
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

# Below this, the analyzer treats a band as silent. -90 dBFS is beneath
# the noise floor of 16-bit audio; nothing musical lives down there.
FLOOR_DB = -90.0

DEFAULT_NUM_BANDS = 96
DEFAULT_FFT_SIZE = 4096


def log_band_edges(low_hz: float, high_hz: float, num_bands: int) -> NDArray[np.float64]:
    """``num_bands + 1`` geometrically spaced band edges."""
    return np.geomspace(low_hz, high_hz, num_bands + 1)


def band_spectrum_db(
    samples: NDArray[np.floating],
    sample_rate: float,
    edges_hz: NDArray[np.float64],
) -> NDArray[np.float64]:
    """Peak amplitude per band, in dBFS, floored at :data:`FLOOR_DB`.

    ``samples`` is a mono block; a full-scale sine within one band reads
    ~0 dB. Bands with no FFT bin inside them (possible at the very bottom
    of the range, where bins are coarser than the bands) report the
    floor rather than inventing data.
    """
    block = np.asarray(samples, dtype=np.float64)
    window = np.hanning(len(block))
    # 2/sum(window): rfft halves a real sine's energy into the positive
    # bin, and the window eats amplitude; together this calibrates a
    # full-scale sine to 1.0.
    amplitudes = 2.0 * np.abs(np.fft.rfft(block * window)) / max(window.sum(), 1e-12)
    frequencies = np.fft.rfftfreq(len(block), 1.0 / sample_rate)

    bin_edges = np.searchsorted(frequencies, edges_hz)
    values = np.full(len(edges_hz) - 1, FLOOR_DB)
    for index in range(len(values)):
        segment = amplitudes[bin_edges[index] : bin_edges[index + 1]]
        if len(segment):
            values[index] = 20.0 * np.log10(max(float(segment.max()), 1e-12))
    floored: NDArray[np.float64] = np.maximum(values, FLOOR_DB)
    return floored
