"""Lab mode tests: the preset hand-off, the capture-process-render loop,
and the backend's state machine — everything except real hardware
enumeration, which is verified against the user's actual VB-CABLE
install instead (the same split M4 draws around ``detect_installation``:
OS-level device discovery isn't unit-tested, the injectable classes
built on top of it are).
"""

from __future__ import annotations

import threading

import numpy as np
import pytest

from trxmp.application.audio_backend import BackendError, BackendState
from trxmp.domain.equalizer import EqPreset
from trxmp.dsp.engine import EqEngine
from trxmp.infrastructure.lab_mode import backend as backend_module
from trxmp.infrastructure.lab_mode.backend import LabModeBackend
from trxmp.infrastructure.lab_mode.cable_detection import VirtualCable
from trxmp.infrastructure.lab_mode.pipeline import BLOCK_FRAMES, LabModePipeline, _PendingPreset

SAMPLE_RATE = 48_000
CHANNELS = 2

CABLE = VirtualCable(
    capture_device_index=7,
    capture_device_name="CABLE Output (VB-Audio Virtual Cable)",
    sample_rate=SAMPLE_RATE,
    channels=CHANNELS,
    playback_device_name="CABLE Input (VB-Audio Virtual Cable)",
)


class TestPendingPreset:
    def test_starts_empty(self) -> None:
        assert _PendingPreset().take() is None

    def test_take_returns_what_was_set(self) -> None:
        box = _PendingPreset()
        preset = EqPreset.flat()
        box.set(preset)
        assert box.take() is preset

    def test_take_consumes_it_once(self) -> None:
        """The GUI thread may call set() many times before the audio
        thread gets around to a read; only the latest matters, and it's
        gone once taken — this is what keeps a stale preset from being
        re-applied every loop iteration forever."""
        box = _PendingPreset()
        box.set(EqPreset.flat())
        box.take()
        assert box.take() is None

    def test_a_newer_set_replaces_an_unread_older_one(self) -> None:
        box = _PendingPreset()
        first, second = EqPreset.flat(), EqPreset.flat(requested_preamp_db=-6.0)
        box.set(first)
        box.set(second)
        assert box.take() is second


def _tone_bytes(frequency_hz: float, frames: int, amplitude: float = 0.5) -> bytes:
    t = np.arange(frames) / SAMPLE_RATE
    mono = (amplitude * np.sin(2.0 * np.pi * frequency_hz * t)).astype(np.float32)
    stereo = np.tile(mono[:, np.newaxis], (1, CHANNELS))
    return stereo.tobytes()


def _peak(raw: bytes) -> float:
    return float(np.max(np.abs(np.frombuffer(raw, dtype=np.float32))))


class _CountingCaptureStream:
    """Feeds the same block forever, then stops the pipeline's loop
    after a fixed number of reads — a deterministic substitute for "let
    it run for a while and hope the timing works out"."""

    def __init__(self, block: bytes, running: threading.Event, stop_after: int) -> None:
        self._block = block
        self._running = running
        self._count = 0
        self._stop_after = stop_after

    def read(self, num_frames: int, exception_on_overflow: bool = False) -> bytes:
        self._count += 1
        if self._count >= self._stop_after:
            self._running.clear()
        return self._block

    def stop_stream(self) -> None:
        pass

    def close(self) -> None:
        pass


class _RecordingRenderStream:
    def __init__(self) -> None:
        self.written: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.written.append(data)

    def stop_stream(self) -> None:
        pass

    def close(self) -> None:
        pass


class TestLoop:
    def test_bypassed_audio_passes_through_close_to_unchanged(self) -> None:
        pipeline = LabModePipeline(CABLE, render_device_index=0)
        pipeline._running.set()
        engine = EqEngine(float(SAMPLE_RATE), CHANNELS)
        tone = _tone_bytes(1_000.0, BLOCK_FRAMES)
        capture = _CountingCaptureStream(tone, pipeline._running, stop_after=3)
        render = _RecordingRenderStream()

        pipeline._loop(capture, render, engine)

        assert len(render.written) == 3
        input_peak = _peak(tone)
        output_peak = _peak(render.written[-1])
        assert output_peak <= input_peak + 0.01
        assert output_peak > input_peak * 0.85

    def test_a_pending_preset_is_picked_up_and_crossfaded_in(self) -> None:
        """The one thing that crosses the thread boundary: apply_preset()
        called before the loop starts must be audible in the output by
        the time the 50 ms crossfade has had enough blocks to finish."""
        pipeline = LabModePipeline(CABLE, render_device_index=0)
        pipeline._running.set()
        engine = EqEngine(float(SAMPLE_RATE), CHANNELS)
        tone = _tone_bytes(1_000.0, BLOCK_FRAMES)
        # fade_total is 2_400 samples = 5 blocks of 480; run well past that.
        capture = _CountingCaptureStream(tone, pipeline._running, stop_after=12)
        render = _RecordingRenderStream()
        pipeline.apply_preset(EqPreset.flat(requested_preamp_db=-24.0))

        pipeline._loop(capture, render, engine)

        assert len(render.written) == 12
        input_peak = _peak(tone)
        final_peak = _peak(render.written[-1])
        # -24 dB is roughly an 18x drop; well past crossfade completion
        # by block 12, so this can't be explained by mid-fade blending.
        assert final_peak < input_peak * 0.2

    def test_stops_promptly_once_running_is_cleared(self) -> None:
        pipeline = LabModePipeline(CABLE, render_device_index=0)
        pipeline._running.set()
        engine = EqEngine(float(SAMPLE_RATE), CHANNELS)
        tone = _tone_bytes(1_000.0, BLOCK_FRAMES)
        capture = _CountingCaptureStream(tone, pipeline._running, stop_after=1)
        render = _RecordingRenderStream()

        thread = threading.Thread(target=pipeline._loop, args=(capture, render, engine))
        thread.start()
        thread.join(timeout=2.0)

        assert not thread.is_alive()
        assert len(render.written) == 1


class _FakePipeline:
    """Stands in for LabModePipeline so LabModeBackend's state machine
    can be tested without opening real PyAudio streams."""

    def __init__(self, cable: VirtualCable, render_device_index: int) -> None:
        self.cable = cable
        self.render_device_index = render_device_index
        self.error: str | None = None
        self.start_result = True
        self.start_calls = 0
        self.stop_calls = 0
        self.applied: list[EqPreset] = []
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self, preset: EqPreset) -> bool:
        self.start_calls += 1
        self.applied.append(preset)
        self._running = self.start_result
        return self.start_result

    def stop(self) -> None:
        self.stop_calls += 1
        self._running = False

    def apply_preset(self, preset: EqPreset) -> None:
        self.applied.append(preset)


@pytest.fixture
def fake_pipelines(monkeypatch: pytest.MonkeyPatch) -> list[_FakePipeline]:
    created: list[_FakePipeline] = []

    def factory(cable: VirtualCable, render_device_index: int) -> _FakePipeline:
        pipeline = _FakePipeline(cable, render_device_index)
        created.append(pipeline)
        return pipeline

    monkeypatch.setattr(backend_module, "LabModePipeline", factory)
    return created


def _preset() -> EqPreset:
    return EqPreset.flat()


class TestWithoutACable:
    def test_status_is_unavailable_and_mentions_installing_the_cable(self) -> None:
        status = LabModeBackend(None, render_device_index=0).status
        assert status.state is BackendState.UNAVAILABLE
        assert "VB-CABLE" in status.detail

    def test_apply_raises_instead_of_crashing(self) -> None:
        with pytest.raises(BackendError, match="VB-CABLE"):
            LabModeBackend(None, render_device_index=0).apply(_preset())


class TestWithACableButNoRenderDevice:
    def test_status_is_unavailable_and_explains_why(self) -> None:
        status = LabModeBackend(CABLE, render_device_index=None).status
        assert status.state is BackendState.UNAVAILABLE
        assert "no real output device" in status.detail

    def test_apply_raises(self) -> None:
        with pytest.raises(BackendError):
            LabModeBackend(CABLE, render_device_index=None).apply(_preset())


class TestReady:
    def test_status_is_ready_and_names_the_playback_device(
        self, fake_pipelines: list[_FakePipeline]
    ) -> None:
        status = LabModeBackend(CABLE, render_device_index=3).status
        assert status.state is BackendState.READY
        assert status.is_usable
        assert "CABLE Input" in status.detail


class TestApplying:
    def test_apply_starts_the_pipeline_lazily(self, fake_pipelines: list[_FakePipeline]) -> None:
        backend = LabModeBackend(CABLE, render_device_index=3)
        assert fake_pipelines[0].start_calls == 0  # not started just by constructing

        backend.apply(_preset())

        assert fake_pipelines[0].start_calls == 1
        assert fake_pipelines[0].applied == [_preset()]
        assert backend.status.state is BackendState.ACTIVE

    def test_applying_again_while_running_hands_off_instead_of_restarting(
        self, fake_pipelines: list[_FakePipeline]
    ) -> None:
        backend = LabModeBackend(CABLE, render_device_index=3)
        backend.apply(_preset())
        louder = EqPreset.flat(requested_preamp_db=-3.0)

        backend.apply(louder)

        pipeline = fake_pipelines[0]
        assert pipeline.start_calls == 1  # still just the one start
        assert pipeline.applied[-1] is louder

    def test_active_status_names_the_playback_device(
        self, fake_pipelines: list[_FakePipeline]
    ) -> None:
        backend = LabModeBackend(CABLE, render_device_index=3)
        backend.apply(_preset())
        assert "CABLE Input" in backend.status.detail

    def test_active_status_falls_back_to_the_capture_name_without_a_playback_name(
        self, fake_pipelines: list[_FakePipeline]
    ) -> None:
        no_playback_cable = VirtualCable(
            capture_device_index=7,
            capture_device_name="CABLE Output (VB-Audio Virtual Cable)",
            sample_rate=SAMPLE_RATE,
            channels=CHANNELS,
            playback_device_name=None,
        )
        backend = LabModeBackend(no_playback_cable, render_device_index=3)
        backend.apply(_preset())
        assert "CABLE Output" in backend.status.detail

    def test_a_failed_start_raises_a_backend_error(
        self, fake_pipelines: list[_FakePipeline]
    ) -> None:
        backend = LabModeBackend(CABLE, render_device_index=3)
        fake_pipelines[0].start_result = False
        fake_pipelines[0].error = "device is busy"

        with pytest.raises(BackendError, match="device is busy"):
            backend.apply(_preset())


class TestErrorState:
    def test_status_surfaces_a_pipeline_error(self, fake_pipelines: list[_FakePipeline]) -> None:
        backend = LabModeBackend(CABLE, render_device_index=3)
        fake_pipelines[0].error = "the render device disappeared"
        status = backend.status
        assert status.state is BackendState.ERROR
        assert status.detail == "the render device disappeared"


class TestDisabling:
    def test_disable_stops_the_pipeline(self, fake_pipelines: list[_FakePipeline]) -> None:
        backend = LabModeBackend(CABLE, render_device_index=3)
        backend.apply(_preset())

        backend.disable()

        assert fake_pipelines[0].stop_calls == 1
        assert backend.status.state is BackendState.READY

    def test_disable_without_ever_applying_is_a_safe_no_op(
        self, fake_pipelines: list[_FakePipeline]
    ) -> None:
        LabModeBackend(CABLE, render_device_index=3).disable()
        assert fake_pipelines[0].stop_calls == 1

    def test_disable_with_no_cable_is_a_safe_no_op(self) -> None:
        LabModeBackend(None, render_device_index=None).disable()  # must not raise
