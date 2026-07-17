"""Device domain + ProfileManager tests, with an in-memory repository."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from tests.fakes import InMemoryDeviceProfileRepository, InMemoryPresetRepository
from trxmp.application.devices import ProfileManager
from trxmp.application.preset_library import PresetLibrary
from trxmp.domain.devices import AudioDevice, DeviceProfile, DeviceState
from trxmp.domain.equalizer import EqBand, EqPreset
from trxmp.domain.errors import InvalidDeviceError, PresetNotFoundError
from trxmp.dsp.biquad import FilterType

# Real IDs and names from the developer's machine: the Arctis endpoint
# GUID and the shape Windows actually reports.
ARCTIS = AudioDevice(
    id="{0.0.0.00000000}.{bff4659e-58c3-4471-88a6-858356f87748}",
    name="Headphones (SteelSeries Arctis Nova 5)",
    state=DeviceState.ACTIVE,
    is_default=True,
)
SUNDARA = AudioDevice(
    id="{0.0.0.00000000}.{aaaaaaaa-0000-0000-0000-000000000000}",
    name="Speakers (Realtek(R) Audio)",
    state=DeviceState.UNPLUGGED,
)


class TestAudioDevice:
    def test_only_active_devices_are_usable(self) -> None:
        assert ARCTIS.is_usable
        assert not SUNDARA.is_usable  # unplugged: exists, can't play

    def test_ghost_devices_are_not_worth_showing(self) -> None:
        """A real machine reports dozens of NOT_PRESENT relics. Listing
        them would bury the devices the user actually owns."""
        ghost = AudioDevice(id="x", name="Old TV", state=DeviceState.NOT_PRESENT)
        assert not ghost.is_known
        assert SUNDARA.is_known  # unplugged, but real

    def test_rejects_empty_identity(self) -> None:
        with pytest.raises(InvalidDeviceError):
            AudioDevice(id="", name="Something", state=DeviceState.ACTIVE)
        with pytest.raises(InvalidDeviceError):
            AudioDevice(id="x", name="  ", state=DeviceState.ACTIVE)


class TestDeviceProfile:
    def test_rejects_a_profile_with_no_preset(self) -> None:
        now = datetime.now(UTC)
        with pytest.raises(InvalidDeviceError, match="preset"):
            DeviceProfile("id", "name", "", now, now)


@pytest.fixture
def library() -> PresetLibrary:
    library = PresetLibrary(InMemoryPresetRepository())
    library.save(
        "Sundara Harman", EqPreset(bands=(EqBand(FilterType.PEAKING, 4_500.0, -3.0, 2.5),))
    )
    library.save("Gaming", EqPreset(bands=(EqBand(FilterType.LOW_SHELF, 60.0, 4.0, 0.7),)))
    return library


@pytest.fixture
def profiles() -> InMemoryDeviceProfileRepository:
    return InMemoryDeviceProfileRepository()


@pytest.fixture
def manager(profiles: InMemoryDeviceProfileRepository, library: PresetLibrary) -> ProfileManager:
    return ProfileManager(profiles, library)


class TestProfileManager:
    def test_unbound_device_has_no_preset(self, manager: ProfileManager) -> None:
        assert manager.preset_for(ARCTIS) is None

    def test_bind_then_resolve(self, manager: ProfileManager) -> None:
        manager.bind(ARCTIS, "Sundara Harman")
        preset = manager.preset_for(ARCTIS)
        assert preset is not None
        assert preset.bands[0].frequency_hz == 4_500.0

    def test_binding_an_unknown_preset_fails_immediately(self, manager: ProfileManager) -> None:
        """Fail while the user is looking at the button they pressed —
        not silently, months later, when the profile never fires."""
        with pytest.raises(PresetNotFoundError):
            manager.bind(ARCTIS, "does not exist")

    def test_binding_remembers_the_device_name(self, manager: ProfileManager) -> None:
        profile = manager.bind(ARCTIS, "Gaming")
        assert profile.device_name == ARCTIS.name  # shown even when unplugged

    def test_rebinding_replaces_and_keeps_creation_time(self, manager: ProfileManager) -> None:
        first = manager.bind(ARCTIS, "Gaming")
        second = manager.bind(ARCTIS, "Sundara Harman")
        assert second.preset_name == "Sundara Harman"
        assert second.created_at == first.created_at
        assert len(manager.list_profiles()) == 1

    def test_a_stale_binding_resolves_to_nothing_instead_of_raising(
        self, manager: ProfileManager, library: PresetLibrary
    ) -> None:
        """Bind a preset, delete it months later, plug the headphones in.
        Nothing is broken — there's just no automatic switch."""
        manager.bind(ARCTIS, "Gaming")
        library.delete("Gaming")
        assert manager.preset_for(ARCTIS) is None
        assert manager.profile_for(ARCTIS) is not None  # the binding still exists

    def test_devices_are_independent(self, manager: ProfileManager) -> None:
        manager.bind(ARCTIS, "Gaming")
        manager.bind(SUNDARA, "Sundara Harman")

        arctis_profile = manager.profile_for(ARCTIS)
        sundara_profile = manager.profile_for(SUNDARA)
        assert arctis_profile is not None
        assert sundara_profile is not None
        assert arctis_profile.preset_name == "Gaming"
        assert sundara_profile.preset_name == "Sundara Harman"

    def test_unbind(self, manager: ProfileManager) -> None:
        manager.bind(ARCTIS, "Gaming")
        assert manager.unbind(ARCTIS) is True
        assert manager.preset_for(ARCTIS) is None
        assert manager.unbind(ARCTIS) is False
