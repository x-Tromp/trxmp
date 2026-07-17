"""Spectrum math, ring buffer, and controller ballistics."""

from __future__ import annotations

import numpy as np
import pytest
from pytestqt.qtbot import QtBot

from tests.fakes import FakeCaptureSource
from trxmp.dsp.spectrum import FLOOR_DB, band_spectrum_db, log_band_edges
from trxmp.infrastructure.loopback_capture import MonoRingBuffer
from trxmp.ui.spectrum_controller import SpectrumController

SAMPLE_RATE = 48_000.0


def _tone(frequency_hz: float, amplitude: float = 1.0, frames: int = 4096) -> np.ndarray:
    t = np.arange(frames) / SAMPLE_RATE
    return amplitude * np.sin(2.0 * np.pi * frequency_hz * t)


class TestBandSpectrum:
    def test_a_full_scale_tone_reads_zero_dbfs_in_its_band(self) -> None:
        """The calibration that makes the numbers mean something: a
        full-scale sine is 0 dBFS, by definition."""
        edges = log_band_edges(10.0, 20_000.0, 96)
        values = band_spectrum_db(_tone(1_000.0), SAMPLE_RATE, edges)
        assert values.max() == pytest.approx(0.0, abs=1.0)

    def test_the_peak_lands_in_the_band_containing_the_tone(self) -> None:
        edges = log_band_edges(10.0, 20_000.0, 96)
        values = band_spectrum_db(_tone(1_000.0), SAMPLE_RATE, edges)
        band = int(np.argmax(values))
        assert edges[band] <= 1_000.0 <= edges[band + 1]

    def test_amplitude_maps_to_db(self) -> None:
        edges = log_band_edges(10.0, 20_000.0, 96)
        values = band_spectrum_db(_tone(1_000.0, amplitude=0.1), SAMPLE_RATE, edges)
        assert values.max() == pytest.approx(-20.0, abs=1.0)  # 0.1 = -20 dBFS

    def test_silence_is_floored_not_minus_infinity(self) -> None:
        edges = log_band_edges(10.0, 20_000.0, 96)
        values = band_spectrum_db(np.zeros(4096), SAMPLE_RATE, edges)
        assert np.all(values == FLOOR_DB)

    def test_output_length_matches_band_count(self) -> None:
        edges = log_band_edges(10.0, 20_000.0, 64)
        assert len(band_spectrum_db(_tone(440.0), SAMPLE_RATE, edges)) == 64

    def test_edges_are_geometric(self) -> None:
        edges = log_band_edges(10.0, 20_000.0, 96)
        ratios = edges[1:] / edges[:-1]
        assert np.allclose(ratios, ratios[0])


class TestMonoRingBuffer:
    def test_reads_the_latest_frames(self) -> None:
        ring = MonoRingBuffer(capacity=8)
        ring.write(np.arange(1, 6, dtype=np.float32))  # 1..5
        latest = ring.read_latest(3)
        assert latest is not None
        np.testing.assert_array_equal(latest, [3.0, 4.0, 5.0])

    def test_wraps_around_without_losing_order(self) -> None:
        ring = MonoRingBuffer(capacity=4)
        ring.write(np.array([1, 2, 3], dtype=np.float32))
        ring.write(np.array([4, 5, 6], dtype=np.float32))  # wraps
        latest = ring.read_latest(4)
        assert latest is not None
        np.testing.assert_array_equal(latest, [3.0, 4.0, 5.0, 6.0])

    def test_a_write_larger_than_capacity_keeps_the_newest(self) -> None:
        ring = MonoRingBuffer(capacity=4)
        ring.write(np.arange(10, dtype=np.float32))
        latest = ring.read_latest(4)
        assert latest is not None
        np.testing.assert_array_equal(latest, [6.0, 7.0, 8.0, 9.0])

    def test_freshness_contract(self) -> None:
        """Two reads with no write between them: data once, None after.
        This is how the analyzer detects that WASAPI went quiet."""
        ring = MonoRingBuffer(capacity=8)
        ring.write(np.ones(4, dtype=np.float32))
        assert ring.read_latest(4) is not None
        assert ring.read_latest(4) is None
        ring.write(np.ones(2, dtype=np.float32))
        assert ring.read_latest(4) is not None

    def test_underfilled_reads_are_padded_with_leading_silence(self) -> None:
        ring = MonoRingBuffer(capacity=8)
        ring.write(np.array([5.0, 6.0], dtype=np.float32))
        latest = ring.read_latest(4)
        assert latest is not None
        np.testing.assert_array_equal(latest, [0.0, 0.0, 5.0, 6.0])

    def test_empty_buffer_reads_none(self) -> None:
        assert MonoRingBuffer(capacity=8).read_latest(4) is None


class TestSpectrumController:
    def test_start_requires_the_capture_to_open(self, qtbot: QtBot) -> None:
        capture = FakeCaptureSource(start_ok=False)
        controller = SpectrumController(capture)
        assert controller.start() is False
        assert not controller.is_running

    def test_audio_appears_instantly(self, qtbot: QtBot) -> None:
        capture = FakeCaptureSource()
        controller = SpectrumController(capture)
        controller.start()
        capture.block = _tone(1_000.0, amplitude=0.5)
        with qtbot.waitSignal(controller.spectrum_changed) as signal:
            controller.refresh()
        values = signal.args[0]
        assert values.max() == pytest.approx(-6.0, abs=1.5)  # 0.5 ~ -6 dBFS
        controller.stop()

    def test_silence_decays_instead_of_freezing(self, qtbot: QtBot) -> None:
        """WASAPI stops delivering packets when nothing plays; the
        display must fall like a meter, not freeze at the last frame."""
        capture = FakeCaptureSource()
        controller = SpectrumController(capture)
        controller.start()
        capture.block = _tone(1_000.0)
        controller.refresh()
        capture.block = None  # the OS goes quiet

        with qtbot.waitSignal(controller.spectrum_changed) as first:
            controller.refresh()
        with qtbot.waitSignal(controller.spectrum_changed) as second:
            controller.refresh()

        assert second.args[0].max() < first.args[0].max() <= 0.0
        controller.stop()

    def test_decay_bottoms_out_at_the_floor(self, qtbot: QtBot) -> None:
        capture = FakeCaptureSource()
        controller = SpectrumController(capture)
        controller.start()
        for _ in range(100):
            controller.refresh()
        with qtbot.waitSignal(controller.spectrum_changed) as signal:
            controller.refresh()
        assert np.all(signal.args[0] == FLOOR_DB)
        controller.stop()

    def test_stop_stops_the_capture_and_clears_the_display(self, qtbot: QtBot) -> None:
        capture = FakeCaptureSource()
        controller = SpectrumController(capture)
        controller.start()
        with qtbot.waitSignal(controller.spectrum_changed) as signal:
            controller.stop()
        assert signal.args[0] is None
        assert capture.stop_count == 1
        assert not controller.is_running

    def test_restart_capture_reopens_only_while_running(self, qtbot: QtBot) -> None:
        capture = FakeCaptureSource()
        controller = SpectrumController(capture)
        controller.restart_capture()  # not running: a no-op
        assert capture.start_count == 0
        controller.start()
        controller.restart_capture()
        assert capture.stop_count == 1
        assert capture.start_count == 2
        controller.stop()
