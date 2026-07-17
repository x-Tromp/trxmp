"""The live capture -> EqEngine -> render loop.

One dedicated Python thread owns both PyAudio streams and calls
``EqEngine.process_block()`` in a plain, blocking read-process-write
loop. That's a deliberate simplification worth noticing: M7's spectrum
analyzer used a lock-guarded ring buffer because it had two independent
timelines to reconcile (PyAudio's own callback thread writing, the Qt
GUI thread polling at 30 fps on a schedule it doesn't control). Lab mode
has no such mismatch — capture, DSP, and render are one linear pipeline
with nothing else that needs to run in step with it — so a single
thread doing blocking I/O is not just simpler, it's the *more correct*
design for this specific shape of problem. Reaching for the M7 pattern
here out of habit would have been solving a problem this pipeline
doesn't have.

The one thing that *does* cross a thread boundary is the preset: the
Qt GUI thread calls :meth:`LabModePipeline.apply_preset` whenever the
user moves a slider, while the audio thread is in the middle of its
loop. :class:`_PendingPreset` is the entire handoff — one lock, "is
there a new one, take it" — the same minimal-shared-surface shape as
M7's ``MonoRingBuffer``.
"""

from __future__ import annotations

import sys
import threading
from typing import TYPE_CHECKING

import numpy as np
from numpy.typing import NDArray

from trxmp.application.live_engine import resolve_preset_for_engine
from trxmp.domain.equalizer import EqPreset
from trxmp.dsp.engine import EqEngine

if sys.platform == "win32":
    import pyaudiowpatch as pyaudio

if TYPE_CHECKING:
    from trxmp.infrastructure.lab_mode.cable_detection import VirtualCable

# 10 ms at 48 kHz: small enough to feel live, large enough that the
# per-block syscall and Python overhead stay well under the block's own
# playback duration — the same reasoning M1's offline processor and the
# original Rust prototype's 20 ms chunks both used, just tightened here
# because Lab mode is explicitly about the interactive experience.
BLOCK_FRAMES = 480


class _PendingPreset:
    """The only object the GUI thread and the audio thread both touch."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._preset: EqPreset | None = None

    def set(self, preset: EqPreset) -> None:
        with self._lock:
            self._preset = preset

    def take(self) -> EqPreset | None:
        with self._lock:
            preset, self._preset = self._preset, None
            return preset


class LabModePipeline:
    """Owns the audio thread and its two PyAudio streams.

    Takes the virtual cable and the chosen real render device as
    constructor arguments rather than discovering them itself — the
    same "detection happens at the composition root, not inside the
    thing being detected" split M4's backend uses for Equalizer APO.
    """

    def __init__(self, cable: VirtualCable, render_device_index: int) -> None:
        self._cable = cable
        self._render_device_index = render_device_index
        self._pending_preset = _PendingPreset()
        self._thread: threading.Thread | None = None
        self._running = threading.Event()
        self.error: str | None = None
        self.latency_samples = 0

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, initial_preset: EqPreset) -> bool:
        if self.is_running:
            return True
        self.error = None
        self._running.set()
        self._pending_preset.set(initial_preset)
        self._thread = threading.Thread(target=self._run, name="trxmp-lab-mode", daemon=True)
        self._thread.start()
        # A misconfigured device fails inside the first few milliseconds
        # of _run (stream open, not stream read) — waiting briefly here
        # turns that into a same-call False instead of a thread that's
        # silently dead by the time anyone checks is_running.
        self._thread.join(timeout=0.5)
        return self.is_running

    def stop(self) -> None:
        self._running.clear()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._thread = None

    def apply_preset(self, preset: EqPreset) -> None:
        self._pending_preset.set(preset)

    def _run(self) -> None:
        try:
            with pyaudio.PyAudio() as audio:
                capture = audio.open(
                    format=pyaudio.paFloat32,
                    channels=self._cable.channels,
                    rate=self._cable.sample_rate,
                    input=True,
                    input_device_index=self._cable.capture_device_index,
                    frames_per_buffer=BLOCK_FRAMES,
                )
                render = audio.open(
                    format=pyaudio.paFloat32,
                    channels=self._cable.channels,
                    rate=self._cable.sample_rate,
                    output=True,
                    output_device_index=self._render_device_index,
                    frames_per_buffer=BLOCK_FRAMES,
                )
                engine = EqEngine(float(self._cable.sample_rate), self._cable.channels)
                self.latency_samples = engine.latency_samples
                try:
                    self._loop(capture, render, engine)
                finally:
                    capture.stop_stream()
                    capture.close()
                    render.stop_stream()
                    render.close()
        except Exception as error:
            # A background thread's exception has nowhere else to go —
            # if it isn't caught here it vanishes silently, and the
            # pipeline just looks "stopped" with no explanation. Catching
            # broadly and reporting via .error is what lets status
            # surface *why*, matching every other backend's ERROR state.
            self.error = str(error)
        finally:
            self._running.clear()

    def _loop(self, capture: object, render: object, engine: EqEngine) -> None:
        while self._running.is_set():
            new_preset = self._pending_preset.take()
            if new_preset is not None:
                coefficients, preamp_db = resolve_preset_for_engine(
                    new_preset, float(self._cable.sample_rate)
                )
                engine.apply(coefficients, preamp_db)  # crossfaded: live tweaks must not click

            raw = capture.read(BLOCK_FRAMES, exception_on_overflow=False)  # type: ignore[attr-defined]
            block = _bytes_to_block(raw, self._cable.channels)
            processed = engine.process_block(block)
            render.write(_block_to_bytes(processed))  # type: ignore[attr-defined]


def _bytes_to_block(raw: bytes, channels: int) -> NDArray[np.float64]:
    interleaved = np.frombuffer(raw, dtype=np.float32).astype(np.float64)
    return interleaved.reshape(-1, channels)


def _block_to_bytes(block: NDArray[np.float64]) -> bytes:
    return block.astype(np.float32).tobytes()
