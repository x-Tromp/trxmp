"""Limiter tests, mirroring the Rust engine's."""

import numpy as np

from eqgenius.dsp.limiter import Limiter

SAMPLE_RATE = 48_000.0


def _process_in_blocks(limiter: Limiter, signal: np.ndarray, block: int = 128) -> np.ndarray:
    outputs = [
        limiter.process_block(signal[start : start + block])
        for start in range(0, len(signal), block)
    ]
    return np.vstack(outputs)


def test_introduces_only_lookahead_window_of_latency() -> None:
    # 1.5 ms at 48 kHz is 72 samples — inaudible as delay for playback.
    assert Limiter(SAMPLE_RATE, num_channels=2).latency_samples == 72


def test_passes_quiet_signal_unchanged_once_warmed_up() -> None:
    limiter = Limiter(SAMPLE_RATE, num_channels=1)
    t = np.arange(4_096) * 0.01
    signal = (0.1 * np.sin(t))[:, np.newaxis]
    output = _process_in_blocks(limiter, signal)
    latency = limiter.latency_samples
    # After the delay line fills, output is the input shifted by latency.
    np.testing.assert_allclose(output[latency:], signal[: len(signal) - latency], atol=1e-12)


def test_never_lets_output_exceed_ceiling() -> None:
    """A burst at 3x the ceiling simulates an unpredicted transient
    peak — exactly the case the limiter exists for."""
    ceiling_db = -0.3
    limiter = Limiter(SAMPLE_RATE, num_channels=1, ceiling_db=ceiling_db)
    threshold = 10.0 ** (ceiling_db / 20.0)

    signal = np.full((2_000, 1), 0.2)
    signal[400:450] = 3.0
    output = _process_in_blocks(limiter, signal)

    max_output = float(np.max(np.abs(output)))
    assert max_output <= threshold * 1.001, (
        f"limiter let {max_output} through, ceiling was {threshold}"
    )


def test_block_size_does_not_change_the_result() -> None:
    """Streaming correctness: processing the same signal in blocks of 64
    or 1024 must produce identical output. This is the property that
    catches state-carryover bugs (the hardest class of DSP bug)."""
    rng = np.random.default_rng(seed=7)
    signal = rng.uniform(-1.5, 1.5, size=(4_096, 2))

    out_small = _process_in_blocks(Limiter(SAMPLE_RATE, 2), signal, block=64)
    out_large = _process_in_blocks(Limiter(SAMPLE_RATE, 2), signal, block=1_024)
    np.testing.assert_allclose(out_small, out_large, atol=1e-12)
