"""The Lab-mode :class:`AudioBackend` — the pure-Python half of the
Strategy pair promised since the project's README diagram.

One real difference from ``EqualizerApoBackend`` worth naming: APO's
``disable()`` writes a do-nothing config and leaves everything wired up,
because a text file sitting idle costs nothing. Lab mode's "idle" state
would still mean two open OS audio streams and a live thread doing
nothing useful — so its ``disable()`` actually tears the pipeline down.
Same Protocol, and deliberately not the same resource story underneath
it; that's exactly the kind of difference a Strategy interface is
supposed to let each implementation own.
"""

from __future__ import annotations

from trxmp.application.audio_backend import BackendError, BackendState, BackendStatus
from trxmp.domain.equalizer import EqPreset
from trxmp.infrastructure.lab_mode.cable_detection import VirtualCable, detect_virtual_cable
from trxmp.infrastructure.lab_mode.pipeline import LabModePipeline


class LabModeBackend:
    """Drives a virtual-cable capture -> EqEngine -> render pipeline.

    Takes the detected cable (or ``None``) as a constructor argument for
    the same reason ``EqualizerApoBackend`` takes its installation that
    way: detection happens once, at the composition root, which is what
    keeps this class testable against a fake ``VirtualCable`` instead of
    real hardware.
    """

    def __init__(self, cable: VirtualCable | None, render_device_index: int | None) -> None:
        self._cable = cable
        self._render_device_index = render_device_index
        self._pipeline: LabModePipeline | None = None
        if cable is not None and render_device_index is not None:
            self._pipeline = LabModePipeline(cable, render_device_index)

    @property
    def name(self) -> str:
        return "Lab Mode"

    @property
    def status(self) -> BackendStatus:
        if self._cable is None:
            return BackendStatus(
                BackendState.UNAVAILABLE,
                "No virtual audio cable found — install VB-CABLE and set it as your "
                "default output to use Lab mode.",
            )
        if self._render_device_index is None:
            return BackendStatus(
                BackendState.UNAVAILABLE,
                "A virtual cable was found, but no real output device was chosen to render to.",
            )
        assert self._pipeline is not None
        if self._pipeline.error is not None:
            return BackendStatus(BackendState.ERROR, self._pipeline.error)
        if self._pipeline.is_running:
            active_source = self._cable.playback_device_name
            if active_source is None:
                active_source = self._cable.capture_device_name
            return BackendStatus(
                BackendState.ACTIVE, f"Processing live audio routed through {active_source}."
            )
        playback = self._cable.playback_device_name
        detail = (
            f"Ready — set your Windows output to {playback!r} to route audio here."
            if playback
            else "Ready — route your audio into the virtual cable to use Lab mode."
        )
        return BackendStatus(BackendState.READY, detail)

    def apply(self, preset: EqPreset) -> None:
        if self._pipeline is None:
            raise BackendError(self.status.detail)
        if self._pipeline.is_running:
            self._pipeline.apply_preset(preset)
            return
        if not self._pipeline.start(preset):
            raise BackendError(self._pipeline.error or "Lab mode's audio pipeline failed to start.")

    def disable(self) -> None:
        if self._pipeline is not None:
            self._pipeline.stop()


def create_lab_mode_backend(render_device_index: int | None) -> LabModeBackend:
    """Composition-root convenience: detect the cable and build the
    backend in one call, mirroring ``EqualizerApoBackend(detect_installation())``."""
    return LabModeBackend(detect_virtual_cable(), render_device_index)
