"""Turning a domain preset into what :class:`~trxmp.dsp.engine.EqEngine`
actually needs — shared by every path that runs real audio through the
engine.

There are two such paths now: the offline WAV processor (M1), and Lab
mode's live pipeline (M8), which calls this every time the user changes
a band while listening. Two callers translating ``EqPreset -> (bands,
preamp)`` independently is exactly how they'd quietly drift apart —
one forgets the Nyquist check, the other rounds a Q differently — so
there's one function instead, and both paths call it.
"""

from __future__ import annotations

from trxmp.domain.equalizer import EqPreset
from trxmp.dsp.biquad import BiquadCoefficients, design


def resolve_preset_for_engine(
    preset: EqPreset, sample_rate: float
) -> tuple[list[BiquadCoefficients], float]:
    """Validate ``preset`` for ``sample_rate`` and design its filters.

    Returns exactly the two arguments ``EqEngine.apply()`` takes: the
    cascade's designed coefficients, and the headroom-safe preamp (the
    lower of what the preset requested and what its own peak response
    demands — never the raw, untrusted ``requested_preamp_db``).
    """
    preset.validate_for_sample_rate(sample_rate)
    coefficients = [
        design(band.filter_type, sample_rate, band.frequency_hz, band.gain_db, band.q)
        for band in preset.bands
    ]
    return coefficients, preset.safe_preamp_db(sample_rate)
