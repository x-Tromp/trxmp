"""Use case: equalize an audio file offline.

This is the application layer doing its one job — orchestration:
domain (validate preset, compute safe preamp) → dsp (design filters,
run the engine) → infrastructure (read/write the file). No layer below
knows this workflow exists.

The file is processed in blocks even though it's fully in memory —
deliberately the same code path a real-time callback will use in Lab
mode, so the engine gets exercised exactly the way it will run live.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from eqgenius.domain.equalizer import EqPreset
from eqgenius.dsp.biquad import design
from eqgenius.dsp.engine import EqEngine
from eqgenius.infrastructure.wav_io import load_wav, save_wav

_BLOCK_FRAMES = 4096


@dataclass(frozen=True, slots=True)
class EqualizeReport:
    """What actually happened, for the caller (CLI/UI) to display."""

    sample_rate: int
    num_frames: int
    num_channels: int
    peak_response_db: float
    applied_preamp_db: float


def equalize_wav_file(input_path: Path, output_path: Path, preset: EqPreset) -> EqualizeReport:
    """EQ ``input_path`` with ``preset`` and write the result.

    The output is latency-compensated: the engine's limiter lookahead
    delay is flushed with silence and trimmed, so the output lines up
    sample-for-sample with the input.
    """
    data, sample_rate = load_wav(input_path)
    num_frames, num_channels = data.shape

    preset.validate_for_sample_rate(sample_rate)
    coefficients = [
        design(band.filter_type, sample_rate, band.frequency_hz, band.gain_db, band.q)
        for band in preset.bands
    ]
    applied_preamp_db = preset.safe_preamp_db(sample_rate)

    engine = EqEngine(sample_rate, num_channels)
    engine.apply(coefficients, applied_preamp_db, immediate=True)

    processed = [
        engine.process_block(data[start : start + _BLOCK_FRAMES])
        for start in range(0, num_frames, _BLOCK_FRAMES)
    ]
    latency = engine.latency_samples
    if latency:  # flush the delay line so the tail isn't cut off
        processed.append(engine.process_block(np.zeros((latency, num_channels))))

    output = np.vstack(processed)[latency : latency + num_frames]
    save_wav(output_path, output, sample_rate)

    return EqualizeReport(
        sample_rate=sample_rate,
        num_frames=num_frames,
        num_channels=num_channels,
        peak_response_db=preset.peak_response_db(sample_rate),
        applied_preamp_db=applied_preamp_db,
    )
