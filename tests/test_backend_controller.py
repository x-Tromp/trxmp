"""BackendController tests — debouncing and not stealing the audio."""

from __future__ import annotations

import pytest
from pytestqt.qtbot import QtBot

from tests.fakes import FakeBackend
from trxmp.application.audio_backend import BackendState
from trxmp.domain.equalizer import EqBand, EqPreset
from trxmp.dsp.biquad import FilterType
from trxmp.ui.backend_controller import BackendController
from trxmp.ui.view_models import EqViewModel


@pytest.fixture
def model(qtbot: QtBot) -> EqViewModel:
    return EqViewModel()


@pytest.fixture
def backend() -> FakeBackend:
    return FakeBackend()


def test_nothing_is_applied_before_start(model: EqViewModel, backend: FakeBackend) -> None:
    """Opening the window must not seize control of the system's audio.
    Loading the last preset happens at startup and emits signals — none
    of them may reach the backend until the app says so."""
    BackendController(model, backend, debounce_ms=1)
    model.load(EqPreset(bands=(EqBand(FilterType.PEAKING, 500.0, 3.0, 1.0),)))
    model.set_band_gain(0, 5.0)
    assert backend.applied == []


def test_a_change_is_applied_after_the_debounce(
    qtbot: QtBot, model: EqViewModel, backend: FakeBackend
) -> None:
    controller = BackendController(model, backend, debounce_ms=10)
    controller.start()
    with qtbot.waitSignal(controller.status_changed, timeout=1_000):
        model.set_band_gain(0, 4.0)
    assert len(backend.applied) == 1
    assert backend.applied[0].bands[0].gain_db == 4.0


def test_a_burst_of_changes_collapses_into_one_write(
    qtbot: QtBot, model: EqViewModel, backend: FakeBackend
) -> None:
    """A drag emits a change per pixel. Without debouncing, each one
    would rewrite the config file and make APO reload mid-gesture."""
    controller = BackendController(model, backend, debounce_ms=30)
    controller.start()
    for gain in range(1, 20):
        model.set_band_gain(0, gain * 0.1)
    with qtbot.waitSignal(controller.status_changed, timeout=1_000):
        pass
    assert len(backend.applied) == 1
    assert backend.applied[0].bands[0].gain_db == pytest.approx(1.9)  # the final value


def test_powering_off_disables_instead_of_applying(
    qtbot: QtBot, model: EqViewModel, backend: FakeBackend
) -> None:
    controller = BackendController(model, backend, debounce_ms=10)
    controller.start()
    with qtbot.waitSignal(controller.status_changed, timeout=1_000):
        model.set_powered(False)
    assert backend.disable_count == 1
    assert backend.applied == []


def test_backend_errors_surface_as_status_not_exceptions(
    qtbot: QtBot, model: EqViewModel, backend: FakeBackend
) -> None:
    """A backend that can't write must never take the window down with
    it — the user keeps editing, and the status line says why."""
    backend.fail_with = "disk on fire"
    controller = BackendController(model, backend, debounce_ms=10)
    controller.start()
    with qtbot.waitSignal(controller.status_changed, timeout=1_000) as signal:
        model.set_band_gain(0, 3.0)
    status = signal.args[0]
    assert status.state is BackendState.ERROR
    assert "disk on fire" in status.detail


def test_an_unavailable_backend_is_never_written_to(qtbot: QtBot, model: EqViewModel) -> None:
    backend = FakeBackend(BackendState.UNAVAILABLE)
    controller = BackendController(model, backend, debounce_ms=10)
    controller.start()
    with qtbot.waitSignal(controller.status_changed, timeout=1_000):
        model.set_band_gain(0, 3.0)
    assert backend.applied == []


def test_flush_applies_immediately(model: EqViewModel, backend: FakeBackend) -> None:
    controller = BackendController(model, backend, debounce_ms=10_000)
    controller.start()
    model.set_band_gain(0, 2.0)
    controller.flush()
    assert len(backend.applied) == 1


def test_flush_with_nothing_pending_does_nothing(model: EqViewModel, backend: FakeBackend) -> None:
    controller = BackendController(model, backend, debounce_ms=10)
    controller.start()
    controller.flush()  # no edit happened; nothing is mid-debounce
    assert backend.applied == []


def test_resync_applies_even_with_nothing_pending(model: EqViewModel, backend: FakeBackend) -> None:
    """The scenario flush() can't cover: the model hasn't changed, but
    the backend underneath it just did (switching Strategy), so the
    already-on-screen curve has to reach it regardless."""
    controller = BackendController(model, backend, debounce_ms=10_000)
    controller.start()
    controller.resync()
    assert len(backend.applied) == 1


def test_resync_cancels_a_pending_debounce_instead_of_double_applying(
    model: EqViewModel, backend: FakeBackend
) -> None:
    controller = BackendController(model, backend, debounce_ms=10_000)
    controller.start()
    model.set_band_gain(0, 2.0)  # schedules a debounced apply
    controller.resync()
    assert len(backend.applied) == 1
    assert not controller._timer.isActive()
