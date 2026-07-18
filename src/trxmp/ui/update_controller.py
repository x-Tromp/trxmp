"""Checking for a newer release, once, without blocking the window.

Unlike :class:`~trxmp.ui.device_controller.DeviceController`'s polling
(cheap enough to run right on the GUI thread), this does a real network
call with a multi-second timeout — blocking Qt's event loop for that
long would freeze the whole window on every launch. A single background
thread that reports back through a signal is the whole fix: one check,
one result, no polling loop to manage.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Signal

from trxmp.application.update_check import ReleaseSource, check_for_update


class UpdateController(QObject):
    """Emits once, only if a newer release actually exists."""

    update_available = Signal(object)  # UpdateNotice

    def __init__(
        self,
        current_version: str,
        source: ReleaseSource,
        releases_url: str,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._current_version = current_version
        self._source = source
        self._releases_url = releases_url

    def start(self) -> None:
        """Kick off the check in the background. Fire-and-forget: a
        Trxmp window that closes before the check lands simply never
        hears back — the check runs against a daemon thread with
        nothing left to clean up."""
        thread = threading.Thread(target=self._check, name="trxmp-update-check", daemon=True)
        thread.start()

    def _check(self) -> None:
        notice = check_for_update(self._current_version, self._source, self._releases_url)
        if notice is not None:
            # Signal.emit is thread-safe; PySide auto-queues delivery to
            # the receiver's own thread (the GUI thread, here), so the
            # connected slot still only ever runs on the Qt event loop.
            self.update_available.emit(notice)
