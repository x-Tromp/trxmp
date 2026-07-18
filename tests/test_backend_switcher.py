"""BackendSwitcher tests — presenting several backends as one."""

from __future__ import annotations

import pytest

from tests.fakes import FakeBackend
from trxmp.application.audio_backend import BackendState
from trxmp.application.backend_switcher import BackendSwitcher
from trxmp.domain.equalizer import EqBand, EqPreset
from trxmp.dsp.biquad import FilterType


def _preset() -> EqPreset:
    return EqPreset(bands=(EqBand(FilterType.PEAKING, 1_000.0, 3.0, 1.0),))


class TestConstruction:
    def test_requires_at_least_one_backend(self) -> None:
        with pytest.raises(ValueError, match="at least one"):
            BackendSwitcher({}, initial="anything")

    def test_the_initial_name_must_be_one_of_the_backends(self) -> None:
        with pytest.raises(ValueError, match="unknown backend"):
            BackendSwitcher({"A": FakeBackend()}, initial="B")


class TestDelegation:
    def test_status_and_name_come_from_the_current_backend(self) -> None:
        apo = FakeBackend(BackendState.READY)
        switcher = BackendSwitcher({"APO": apo, "Lab": FakeBackend()}, initial="APO")
        assert switcher.status.state is BackendState.READY

    def test_apply_goes_to_the_current_backend_only(self) -> None:
        apo, lab = FakeBackend(), FakeBackend()
        switcher = BackendSwitcher({"APO": apo, "Lab": lab}, initial="APO")
        switcher.apply(_preset())
        assert len(apo.applied) == 1
        assert lab.applied == []

    def test_disable_goes_to_the_current_backend_only(self) -> None:
        apo, lab = FakeBackend(), FakeBackend()
        switcher = BackendSwitcher({"APO": apo, "Lab": lab}, initial="APO")
        switcher.disable()
        assert apo.disable_count == 1
        assert lab.disable_count == 0

    def test_available_names_lists_every_backend(self) -> None:
        switcher = BackendSwitcher({"APO": FakeBackend(), "Lab": FakeBackend()}, initial="APO")
        assert switcher.available_names == ["APO", "Lab"]


class TestSelecting:
    def test_switching_disables_the_outgoing_backend(self) -> None:
        """Never two backends live at once — for a pair like Equalizer
        APO + Lab mode that would mean two independent EQ curves both
        touching the same audio."""
        apo, lab = FakeBackend(), FakeBackend()
        switcher = BackendSwitcher({"APO": apo, "Lab": lab}, initial="APO")
        switcher.apply(_preset())

        switcher.select("Lab")

        assert apo.disable_count == 1
        assert switcher.current_name == "Lab"

    def test_switching_does_not_apply_anything_to_the_incoming_backend(self) -> None:
        """BackendSwitcher knows nothing about the model or any preset —
        resyncing the newly active backend is the caller's job."""
        apo, lab = FakeBackend(), FakeBackend()
        switcher = BackendSwitcher({"APO": apo, "Lab": lab}, initial="APO")
        switcher.select("Lab")
        assert lab.applied == []

    def test_selecting_the_current_backend_is_a_no_op(self) -> None:
        apo = FakeBackend()
        switcher = BackendSwitcher({"APO": apo, "Lab": FakeBackend()}, initial="APO")
        switcher.select("APO")
        assert apo.disable_count == 0

    def test_selecting_an_unknown_name_raises(self) -> None:
        switcher = BackendSwitcher({"APO": FakeBackend()}, initial="APO")
        with pytest.raises(ValueError, match="unknown backend"):
            switcher.select("Ghost")

    def test_after_switching_delegation_follows_the_new_backend(self) -> None:
        apo, lab = FakeBackend(), FakeBackend(BackendState.ACTIVE)
        switcher = BackendSwitcher({"APO": apo, "Lab": lab}, initial="APO")
        switcher.select("Lab")
        switcher.apply(_preset())
        assert len(lab.applied) == 1
        assert switcher.status.state is BackendState.ACTIVE
