"""Engine tests, mirroring the Rust engine's end-to-end properties."""

import numpy as np
import pytest

from trxmp.domain.equalizer import EqBand, EqPreset
from trxmp.dsp.biquad import BiquadCoefficients, FilterType, design
from trxmp.dsp.engine import EqEngine

SAMPLE_RATE = 48_000.0


def _coefficients_for(preset: EqPreset, sample_rate: float) -> list[BiquadCoefficients]:
    return [
        design(band.filter_type, sample_rate, band.frequency_hz, band.gain_db, band.q)
        for band in preset.bands
    ]


def _sine(freq: float, num_frames: int, channels: int, amplitude: float = 0.5) -> np.ndarray:
    t = np.arange(num_frames) / SAMPLE_RATE
    mono = amplitude * np.sin(2.0 * np.pi * freq * t)
    return np.tile(mono[:, np.newaxis], (1, channels))


def test_flat_preset_does_not_meaningfully_alter_a_quiet_signal() -> None:
    preset = EqPreset.flat()
    engine = EqEngine(SAMPLE_RATE, num_channels=2)
    engine.apply(
        _coefficients_for(preset, SAMPLE_RATE), preset.safe_preamp_db(SAMPLE_RATE), immediate=True
    )

    signal = _sine(440.0, 4_096, channels=2)
    output = engine.process_block(signal)

    input_peak = float(np.max(np.abs(signal)))
    output_peak = float(np.max(np.abs(output)))
    # Close, never amplified: a small dip is expected from the headroom
    # safety margin.
    assert output_peak <= input_peak + 0.01
    assert output_peak > input_peak * 0.85


def test_never_clips_even_with_aggressive_overlapping_boosts() -> None:
    """A near-full-scale, harmonically rich signal is the worst case for
    multi-band phase summation — the exact scenario the headroom scan +
    limiter combination exists to survive."""
    preset = EqPreset(
        bands=(
            EqBand(FilterType.PEAKING, 60.0, 9.0, 0.8),
            EqBand(FilterType.PEAKING, 100.0, 9.0, 0.8),
            EqBand(FilterType.PEAKING, 3_000.0, 8.0, 1.2),
            EqBand(FilterType.HIGH_SHELF, 8_000.0, 7.0, 0.7),
        )
    )
    engine = EqEngine(SAMPLE_RATE, num_channels=2)
    engine.apply(
        _coefficients_for(preset, SAMPLE_RATE), preset.safe_preamp_db(SAMPLE_RATE), immediate=True
    )

    t = np.arange(48_000) / SAMPLE_RATE
    mono = 0.9 * (
        np.sin(2.0 * np.pi * 80.0 * t)
        + 0.5 * np.sin(2.0 * np.pi * 95.0 * t)
        + 0.3 * np.sin(2.0 * np.pi * 3_000.0 * t)
    )
    signal = np.tile(mono[:, np.newaxis], (1, 2))

    outputs = [
        engine.process_block(signal[start : start + 4_096])
        for start in range(0, len(signal), 4_096)
    ]
    peak = float(np.max(np.abs(np.vstack(outputs))))
    assert peak <= 1.0, f"output exceeded full scale: {peak}"


def test_preset_switch_crossfades_without_a_discontinuity_jump() -> None:
    quiet = EqPreset.flat(requested_preamp_db=-12.0)
    loud = EqPreset.flat()
    engine = EqEngine(SAMPLE_RATE, num_channels=1)
    engine.apply((), quiet.safe_preamp_db(SAMPLE_RATE), immediate=True)

    warmup = np.full((100, 1), 0.3)
    engine.process_block(warmup)

    engine.apply((), loud.safe_preamp_db(SAMPLE_RATE))  # crossfaded

    output = engine.process_block(np.full((4_800, 1), 0.3))

    # No sample-to-sample jump larger than a smooth 50 ms crossfade of a
    # constant signal implies.
    max_step = float(np.max(np.abs(np.diff(output[:, 0]))))
    assert max_step < 0.01, f"found a discontinuity of {max_step} during crossfade"


def test_rejects_block_with_wrong_channel_count() -> None:
    engine = EqEngine(SAMPLE_RATE, num_channels=2)
    with pytest.raises(ValueError, match="frames, 2"):
        engine.process_block(np.zeros((256, 3)))


def test_reports_limiter_lookahead_as_latency() -> None:
    assert EqEngine(SAMPLE_RATE, num_channels=2).latency_samples == 72
