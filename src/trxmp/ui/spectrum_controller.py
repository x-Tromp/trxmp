"""Drives the live spectrum: poll the capture, compute bands, animate.

The animation policy is the classic analyzer ballistics: **instant
attack, timed release**. A transient must appear the frame it happens
(miss it and the display feels laggy), but if bars also *fell* at frame
rate the whole thing would flicker unreadably — so each band falls at a
fixed dB-per-second instead, like a needle with mass.

The release doubles as the answer to WASAPI's quirk of delivering
nothing during silence: no data simply means every band keeps falling
until it reaches the floor. Pause your music and the spectrum melts
away, which is both correct and exactly what you'd expect it to do.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal

from trxmp.application.capture import AudioCaptureSource
from trxmp.domain.equalizer import MAX_FREQUENCY_HZ, MIN_FREQUENCY_HZ
from trxmp.dsp.spectrum import (
    DEFAULT_FFT_SIZE,
    DEFAULT_NUM_BANDS,
    FLOOR_DB,
    band_spectrum_db,
    log_band_edges,
)

DEFAULT_FPS = 30
RELEASE_DB_PER_SECOND = 60.0


class SpectrumController(QObject):
    """Polls an :class:`AudioCaptureSource` and emits animated band dBs."""

    # NDArray of per-band dBFS while running; None when stopped (the
    # widget clears rather than freezing a stale spectrum on screen).
    spectrum_changed = Signal(object)

    def __init__(
        self,
        capture: AudioCaptureSource,
        num_bands: int = DEFAULT_NUM_BANDS,
        fps: int = DEFAULT_FPS,
        fft_size: int = DEFAULT_FFT_SIZE,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._capture = capture
        self._fft_size = fft_size
        self._edges = log_band_edges(MIN_FREQUENCY_HZ, MAX_FREQUENCY_HZ, num_bands)
        self._values = np.full(num_bands, FLOOR_DB)
        self._release_per_tick = RELEASE_DB_PER_SECOND / fps
        self._timer = QTimer(self)
        self._timer.setInterval(max(1, 1000 // fps))
        self._timer.timeout.connect(self._tick)

    @property
    def is_running(self) -> bool:
        return self._timer.isActive()

    def start(self) -> bool:
        """True if the capture opened; False leaves the analyzer off."""
        if self.is_running:
            return True
        if not self._capture.start():
            return False
        self._values[:] = FLOOR_DB
        self._timer.start()
        return True

    def stop(self) -> None:
        self._timer.stop()
        self._capture.stop()
        self.spectrum_changed.emit(None)

    def restart_capture(self) -> None:
        """Follow a default-device change: the loopback twin we captured
        belongs to the *old* device, so reopen against the new one."""
        if self.is_running:
            self._capture.stop()
            if not self._capture.start():
                self.stop()

    def refresh(self) -> None:
        """One tick, now — the test seam, same as DeviceController's."""
        self._tick()

    def _tick(self) -> None:
        block = self._capture.read_latest(self._fft_size)
        fallen = np.maximum(self._values - self._release_per_tick, FLOOR_DB)
        if block is None:
            self._values = fallen
        else:
            measured = band_spectrum_db(block, self._capture.sample_rate, self._edges)
            self._values = np.maximum(measured, fallen)  # instant attack, timed release
        self.spectrum_changed.emit(self._values.copy())
