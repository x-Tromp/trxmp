"""End-to-end tests for the offline equalize use case (real files on disk)."""

from pathlib import Path

import numpy as np
import pytest

from trxmp.application.audio_files import equalize_wav_file
from trxmp.domain.equalizer import EqBand, EqPreset
from trxmp.dsp.biquad import FilterType
from trxmp.infrastructure.wav_io import load_wav, save_wav

SAMPLE_RATE = 44_100


@pytest.fixture
def sine_wav(tmp_path: Path) -> Path:
    """One second of 440 Hz stereo at moderate level, on disk."""
    t = np.arange(SAMPLE_RATE) / SAMPLE_RATE
    mono = 0.4 * np.sin(2.0 * np.pi * 440.0 * t)
    path = tmp_path / "input.wav"
    save_wav(path, np.tile(mono[:, np.newaxis], (1, 2)), SAMPLE_RATE)
    return path


def test_wav_roundtrip_preserves_audio(tmp_path: Path) -> None:
    rng = np.random.default_rng(seed=3)
    original = rng.uniform(-0.8, 0.8, size=(1_000, 2))
    path = tmp_path / "roundtrip.wav"
    save_wav(path, original, 48_000)
    loaded, sample_rate = load_wav(path)
    assert sample_rate == 48_000
    assert loaded.shape == original.shape
    # 16-bit quantization allows ~1/32767 of error per sample.
    np.testing.assert_allclose(loaded, original, atol=2.0 / 32_767.0)


def test_flat_preset_output_is_input_scaled_by_safety_margin(
    sine_wav: Path, tmp_path: Path
) -> None:
    """With no bands, the only change is the -0.5 dB headroom margin —
    and thanks to latency compensation the output aligns sample-for-
    sample with the input."""
    output_path = tmp_path / "flat.wav"
    preset = EqPreset.flat()
    report = equalize_wav_file(sine_wav, output_path, preset)

    original, _ = load_wav(sine_wav)
    processed, _ = load_wav(output_path)
    assert processed.shape == original.shape
    assert report.applied_preamp_db == pytest.approx(-0.5, abs=0.01)

    expected = original * 10.0 ** (-0.5 / 20.0)
    np.testing.assert_allclose(processed, expected, atol=1e-3)


def test_eq_preset_actually_changes_the_audio(sine_wav: Path, tmp_path: Path) -> None:
    output_path = tmp_path / "eq.wav"
    preset = EqPreset(
        bands=(EqBand(FilterType.PEAKING, 440.0, -9.0, 2.0),)  # notch our own sine
    )
    report = equalize_wav_file(sine_wav, output_path, preset)

    original, _ = load_wav(sine_wav)
    processed, _ = load_wav(output_path)

    # A -9 dB bell centered exactly on the tone should reduce its RMS
    # to roughly 10^(-9/20) ≈ 0.355 of the original (plus margin).
    original_rms = float(np.sqrt(np.mean(original**2)))
    processed_rms = float(np.sqrt(np.mean(processed**2)))
    assert processed_rms < original_rms * 0.45
    assert report.peak_response_db == pytest.approx(0.0, abs=0.1)
