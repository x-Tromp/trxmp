"""WASAPI loopback capture via PyAudioWPatch.

Why this library: stock ``sounddevice``/PortAudio cannot open WASAPI
loopback streams (probed and confirmed on this machine — its
``WasapiSettings`` has no ``loopback`` argument). PyAudioWPatch is the
maintained PyAudio fork built for exactly this: it exposes every render
device's loopback twin as an *input* device, so capturing "what Windows
is playing" becomes an ordinary input stream. This is the dependency the
project spec meant by "PyAudio only if necessary" — this is necessary.

Threading is the whole design here. PyAudio delivers audio on its own
callback thread; the UI reads at ~30 fps from the GUI thread. Between
them sits :class:`MonoRingBuffer` — the only object both threads touch,
with one lock and two methods. Keeping the shared surface that small is
what makes the threading reviewable at a glance.

Everything degrades instead of raising: no WASAPI, no loopback twin, a
device that vanishes mid-stream — all become ``start() -> False`` or
"no new data", never a crash. The analyzer is decoration; decoration
must never take the app down.
"""

from __future__ import annotations

import contextlib
import sys
import threading

import numpy as np
from numpy.typing import NDArray

if sys.platform == "win32":
    import pyaudiowpatch as pyaudio

_DEFAULT_SAMPLE_RATE = 48_000
_CALLBACK_FRAMES = 1024


class MonoRingBuffer:
    """Fixed-capacity mono sample buffer, safe across two threads.

    ``write`` is called from the audio callback, ``read_latest`` from the
    GUI thread. The freshness flag is what implements the capture
    Protocol's ``None`` contract: a read consumes it, so two reads with
    no write between them return data once and ``None`` after — which is
    how the analyzer knows the OS went quiet.
    """

    def __init__(self, capacity: int) -> None:
        self._buffer = np.zeros(capacity, dtype=np.float32)
        self._capacity = capacity
        self._write_pos = 0
        self._filled = 0
        self._fresh = False
        self._lock = threading.Lock()

    def write(self, samples: NDArray[np.float32]) -> None:
        with self._lock:
            n = len(samples)
            if n >= self._capacity:  # keep only what fits: the newest
                self._buffer[:] = samples[-self._capacity :]
                self._write_pos = 0
                self._filled = self._capacity
            else:
                end = self._write_pos + n
                if end <= self._capacity:
                    self._buffer[self._write_pos : end] = samples
                else:
                    first = self._capacity - self._write_pos
                    self._buffer[self._write_pos :] = samples[:first]
                    self._buffer[: end % self._capacity] = samples[first:]
                self._write_pos = end % self._capacity
                self._filled = min(self._filled + n, self._capacity)
            self._fresh = True

    def read_latest(self, num_frames: int) -> NDArray[np.float32] | None:
        with self._lock:
            if not self._fresh or self._filled == 0:
                return None
            self._fresh = False
            n = min(num_frames, self._filled)
            start = (self._write_pos - n) % self._capacity
            if start + n <= self._capacity:
                latest = self._buffer[start : start + n].copy()
            else:
                latest = np.concatenate(
                    (self._buffer[start:], self._buffer[: (start + n) % self._capacity])
                )
            if n < num_frames:  # not enough history yet: pad the past with silence
                latest = np.concatenate((np.zeros(num_frames - n, dtype=np.float32), latest))
            return latest


class LoopbackCapture:
    """``AudioCaptureSource`` over the default output's loopback twin."""

    def __init__(self, buffer_seconds: float = 2.0) -> None:
        self._buffer_seconds = buffer_seconds
        self._sample_rate = _DEFAULT_SAMPLE_RATE
        self._ring: MonoRingBuffer | None = None
        self._audio: object = None
        self._stream: object = None
        self.error: str | None = None

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    def start(self) -> bool:
        if sys.platform != "win32":
            self.error = "loopback capture is Windows-only"
            return False
        if self._stream is not None:
            return True
        try:
            audio = pyaudio.PyAudio()
        except Exception as error:
            self.error = f"could not initialise audio: {error}"
            return False
        try:
            wasapi = audio.get_host_api_info_by_type(pyaudio.paWASAPI)
            default_name = audio.get_device_info_by_index(wasapi["defaultOutputDevice"])["name"]
            loopback = next(
                (
                    device
                    for device in audio.get_loopback_device_info_generator()
                    if default_name in device["name"]
                ),
                None,
            )
            if loopback is None:
                self.error = f"no loopback device for {default_name!r}"
                audio.terminate()
                return False

            self._sample_rate = int(loopback["defaultSampleRate"])
            channels = max(1, int(loopback["maxInputChannels"]))
            ring = MonoRingBuffer(int(self._buffer_seconds * self._sample_rate))

            def callback(
                in_data: bytes | None, frame_count: int, time_info: object, status: int
            ) -> tuple[None, int]:
                if in_data:
                    frames = np.frombuffer(in_data, dtype=np.float32)
                    ring.write(frames.reshape(-1, channels).mean(axis=1).astype(np.float32))
                return (None, pyaudio.paContinue)

            self._stream = audio.open(
                format=pyaudio.paFloat32,
                channels=channels,
                rate=self._sample_rate,
                input=True,
                input_device_index=int(loopback["index"]),
                frames_per_buffer=_CALLBACK_FRAMES,
                stream_callback=callback,
            )
        except Exception as error:
            self.error = f"could not open loopback capture: {error}"
            audio.terminate()
            return False

        self._audio = audio
        self._ring = ring
        self.error = None
        return True

    def stop(self) -> None:
        stream, audio = self._stream, self._audio
        self._stream = self._audio = self._ring = None
        # suppress(Exception): a device that vanished mid-close throws
        # from inside PortAudio, and tearing down a dead stream is not
        # worth a crash.
        if stream is not None:
            with contextlib.suppress(Exception):
                stream.stop_stream()  # type: ignore[attr-defined]
                stream.close()  # type: ignore[attr-defined]
        if audio is not None:
            with contextlib.suppress(Exception):
                audio.terminate()  # type: ignore[attr-defined]

    def read_latest(self, num_frames: int) -> NDArray[np.float32] | None:
        ring = self._ring
        return None if ring is None else ring.read_latest(num_frames)
