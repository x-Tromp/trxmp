"""Watching which device Windows is playing through.

**Why polling, when Core Audio offers callbacks.** ``IMMNotificationClient``
would tell us the instant the default device changes — but its callbacks
arrive on an arbitrary COM thread, and touching Qt widgets from a
non-GUI thread is undefined behaviour. Doing it properly means
registering a COM object, marshalling every event onto the Qt loop, and
unregistering it without deadlocking on shutdown.

Against that: reading the default endpoint costs well under a
millisecond. Once every two seconds that is roughly nothing, it runs on
the GUI thread where the rest of the UI already lives, and the worst
case is that a profile switch lands two seconds late — which nobody can
perceive while they are still putting their headphones on.

The complexity is real and the benefit is imperceptible. Polling wins.
This is worth saying out loud because "polling is lazy" is a reflex, and
reflexes are not engineering: the callback version would be more code,
more threads, and more ways to crash, to save 2000 milliseconds nobody
is counting.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal

from trxmp.application.devices import AudioDeviceService
from trxmp.domain.devices import AudioDevice

DEFAULT_POLL_MS = 2_000


class DeviceController(QObject):
    """Emits when the system's default output device changes."""

    # `object` carries an `AudioDevice | None` — None meaning Windows has
    # no usable output at all (every device unplugged, or the audio
    # service restarting).
    device_changed = Signal(object)

    def __init__(
        self,
        service: AudioDeviceService,
        poll_ms: int = DEFAULT_POLL_MS,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._current: AudioDevice | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(poll_ms)
        self._timer.timeout.connect(self._poll)

    @property
    def current_device(self) -> AudioDevice | None:
        return self._current

    def start(self) -> None:
        """Read the device once, then watch for changes.

        The first read deliberately does *not* emit: at startup there's
        no "change" to react to, and firing here would make the window
        auto-switch presets simply because it opened.
        """
        self._current = self._service.default_output_device()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def refresh(self) -> None:
        """Check right now instead of waiting for the next tick."""
        self._poll()

    def _poll(self) -> None:
        device = self._service.default_output_device()
        # Compare by id, not by value: `is_default` and `state` can churn
        # between polls on the same physical device, and re-firing on
        # every wobble would reload the preset under the user's hands.
        if _identity(device) == _identity(self._current):
            self._current = device
            return
        self._current = device
        self.device_changed.emit(device)


def _identity(device: AudioDevice | None) -> str | None:
    return None if device is None else device.id
