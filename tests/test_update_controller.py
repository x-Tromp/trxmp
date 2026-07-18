"""UpdateController — the background check and its one signal."""

from __future__ import annotations

from pytestqt.qtbot import QtBot

from trxmp.application.update_check import UpdateNotice
from trxmp.ui.update_controller import UpdateController

RELEASES_URL = "https://github.com/Equix/trxmp/releases"


class _FakeSource:
    def __init__(self, tag: str | None) -> None:
        self._tag = tag

    def latest_tag(self) -> str | None:
        return self._tag


def test_emits_when_a_newer_release_exists(qtbot: QtBot) -> None:
    controller = UpdateController("0.6.0", _FakeSource("v0.7.0"), RELEASES_URL)
    with qtbot.waitSignal(controller.update_available, timeout=1_000) as signal:
        controller.start()
    assert signal.args[0] == UpdateNotice(version="0.7.0", url=RELEASES_URL)


def test_does_not_emit_when_already_current(qtbot: QtBot) -> None:
    controller = UpdateController("0.6.0", _FakeSource("v0.6.0"), RELEASES_URL)
    received: list[object] = []
    controller.update_available.connect(received.append)
    controller.start()
    # Nothing to wait on — a background thread doing no I/O finishes
    # near-instantly; qtbot.wait pumps the event loop long enough for a
    # queued signal (if any were emitted) to actually arrive.
    qtbot.wait(200)
    assert received == []


def test_does_not_emit_when_the_source_cannot_answer(qtbot: QtBot) -> None:
    controller = UpdateController("0.6.0", _FakeSource(None), RELEASES_URL)
    received: list[object] = []
    controller.update_available.connect(received.append)
    controller.start()
    qtbot.wait(200)
    assert received == []
