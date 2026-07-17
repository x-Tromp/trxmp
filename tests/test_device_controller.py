"""DeviceController tests — polling, and not over-reacting to it."""

from __future__ import annotations

import pytest
from pytestqt.qtbot import QtBot

from tests.fakes import ARCTIS, SPEAKERS, FakeDeviceService
from trxmp.domain.devices import AudioDevice, DeviceState
from trxmp.ui.device_controller import DeviceController


@pytest.fixture
def service() -> FakeDeviceService:
    return FakeDeviceService()


def test_start_reads_the_device_without_announcing_a_change(
    qtbot: QtBot, service: FakeDeviceService
) -> None:
    """At startup there is no change to react to. Firing here would make
    the app auto-switch presets simply because the window opened."""
    controller = DeviceController(service, poll_ms=10_000)
    with qtbot.assertNotEmitted(controller.device_changed):
        controller.start()
    assert controller.current_device == ARCTIS


def test_switching_devices_emits(qtbot: QtBot, service: FakeDeviceService) -> None:
    controller = DeviceController(service, poll_ms=10_000)
    controller.start()
    service.default = SPEAKERS
    with qtbot.waitSignal(controller.device_changed) as signal:
        controller.refresh()
    assert signal.args[0] == SPEAKERS
    assert controller.current_device == SPEAKERS


def test_polling_the_same_device_emits_nothing(qtbot: QtBot, service: FakeDeviceService) -> None:
    controller = DeviceController(service, poll_ms=10_000)
    controller.start()
    with qtbot.assertNotEmitted(controller.device_changed):
        for _ in range(5):
            controller.refresh()


def test_identity_is_the_id_not_the_whole_value(qtbot: QtBot, service: FakeDeviceService) -> None:
    """`state` and `is_default` wobble between polls on the same physical
    device. Comparing whole values would reload the preset under the
    user's hands every couple of seconds."""
    controller = DeviceController(service, poll_ms=10_000)
    controller.start()
    service.default = AudioDevice(
        id=ARCTIS.id, name=ARCTIS.name, state=DeviceState.ACTIVE, is_default=False
    )
    with qtbot.assertNotEmitted(controller.device_changed):
        controller.refresh()


def test_losing_all_audio_output_emits_none(qtbot: QtBot, service: FakeDeviceService) -> None:
    controller = DeviceController(service, poll_ms=10_000)
    controller.start()
    service.default = None
    with qtbot.waitSignal(controller.device_changed) as signal:
        controller.refresh()
    assert signal.args[0] is None


def test_the_timer_actually_polls(qtbot: QtBot, service: FakeDeviceService) -> None:
    controller = DeviceController(service, poll_ms=10)
    controller.start()
    service.default = SPEAKERS
    with qtbot.waitSignal(controller.device_changed, timeout=1_000):
        pass  # no manual refresh: the timer must do it
    controller.stop()


def test_stop_ends_polling(qtbot: QtBot, service: FakeDeviceService) -> None:
    controller = DeviceController(service, poll_ms=10)
    controller.start()
    controller.stop()
    count = service.poll_count
    qtbot.wait(60)
    assert service.poll_count == count
