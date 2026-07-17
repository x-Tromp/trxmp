"""Pushes the on-screen EQ out to the audio backend, live.

Two jobs, both about behaving well:

**Debouncing.** Dragging a handle emits a change per mouse pixel — tens
per second. Writing a config file that often would hammer the disk and,
worse, make Equalizer APO reload its filters mid-gesture. A single-shot
QTimer that restarts on every change collapses a whole drag into one
write, ~120 ms after the user stops moving. This is the canonical Qt
debounce, and it's the difference between "live" and "unusable".

**Not stealing the audio on startup.** Trxmp does not apply anything
until the user asks. Opening the window on a machine where Peace (or
anything else) owns Equalizer APO must not silently take it over — the
first real gesture does, and the status line says so. Hence the explicit
:meth:`start`: this object listens to nothing until told to.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal

from trxmp.application.audio_backend import AudioBackend, BackendError, BackendState, BackendStatus
from trxmp.ui.view_models import EqViewModel

DEFAULT_DEBOUNCE_MS = 120


class BackendController(QObject):
    """Binds an :class:`EqViewModel` to an :class:`AudioBackend`."""

    # `object`, not `BackendStatus`: PySide6 marshals arbitrary Python
    # objects through `object` signals without needing a registered
    # meta-type for our dataclass.
    status_changed = Signal(object)

    def __init__(
        self,
        model: EqViewModel,
        backend: AudioBackend,
        debounce_ms: int = DEFAULT_DEBOUNCE_MS,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._model = model
        self._backend = backend
        self._started = False

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(debounce_ms)
        self._timer.timeout.connect(self._apply_now)

    @property
    def status(self) -> BackendStatus:
        return self._backend.status

    def start(self) -> None:
        """Begin following the model. Applies nothing by itself."""
        if self._started:
            return
        self._started = True
        self._model.bands_changed.connect(self._schedule)
        self._model.preamp_changed.connect(self._schedule)
        self._model.powered_changed.connect(self._schedule)
        self._model.preset_loaded.connect(self._schedule)

    def _schedule(self) -> None:
        # start() on a running single-shot timer restarts it, which is
        # exactly the debounce: the clock only expires once the changes
        # stop coming.
        self._timer.start()

    def flush(self) -> None:
        """Apply any pending change immediately (used by tests and on
        deliberate user actions that shouldn't wait out the debounce)."""
        if self._timer.isActive():
            self._timer.stop()
            self._apply_now()

    def _apply_now(self) -> None:
        if not self._backend.status.is_usable:
            self.status_changed.emit(self._backend.status)
            return
        try:
            if self._model.powered:
                self._backend.apply(self._model.to_preset())
            else:
                self._backend.disable()
        except BackendError as error:
            # A backend that can't write must never take the UI down with
            # it: report it and let the user keep editing.
            self.status_changed.emit(BackendStatus(BackendState.ERROR, str(error)))
            return
        self.status_changed.emit(self._backend.status)
