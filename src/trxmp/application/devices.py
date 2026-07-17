"""Use cases for devices and automatic profile switching.

Two Protocols and one service, following the same shape as M2: the
application declares what it needs, infrastructure conforms, the
composition root wires them. Neither pycaw nor the registry is visible
from here.

The interesting rule lives in :meth:`ProfileManager.preset_for`: a
profile can outlive the preset it points at. Someone binds "Sundara
Harman" to their headphones, deletes that preset months later, then
plugs the headphones in. Nothing is broken — the binding is simply
stale, and a stale binding means "no automatic switch", not a crash and
not a mystery EQ.
"""

from __future__ import annotations

from typing import Protocol

from trxmp.application.preset_library import PresetLibrary
from trxmp.domain.devices import AudioDevice, DeviceProfile
from trxmp.domain.equalizer import EqPreset
from trxmp.domain.errors import EqualizerError


class AudioDeviceService(Protocol):
    """Reading the machine's audio outputs. Never raises: a COM hiccup
    means "no devices right now", not a dead application."""

    def list_output_devices(self) -> list[AudioDevice]: ...

    def default_output_device(self) -> AudioDevice | None: ...


class DeviceProfileRepository(Protocol):
    def get(self, device_id: str) -> DeviceProfile | None: ...

    def list_all(self) -> list[DeviceProfile]: ...

    def upsert(self, device_id: str, device_name: str, preset_name: str) -> DeviceProfile: ...

    def delete(self, device_id: str) -> bool: ...


class ProfileManager:
    """Which preset belongs to which device, and why."""

    def __init__(self, profiles: DeviceProfileRepository, library: PresetLibrary) -> None:
        self._profiles = profiles
        self._library = library

    def profile_for(self, device: AudioDevice) -> DeviceProfile | None:
        return self._profiles.get(device.id)

    def preset_for(self, device: AudioDevice) -> EqPreset | None:
        """The preset this device should switch to, or None.

        None covers both "nothing bound" and "bound to a preset that no
        longer exists" — from the caller's point of view they're the same
        instruction: leave the current EQ alone.
        """
        profile = self._profiles.get(device.id)
        if profile is None:
            return None
        try:
            return self._library.get(profile.preset_name).preset
        except EqualizerError:
            return None  # stale binding; the preset was renamed or deleted

    def bind(self, device: AudioDevice, preset_name: str) -> DeviceProfile:
        """Remember that ``device`` should use ``preset_name``.

        Resolving the preset first is the point: binding to a name that
        doesn't exist would create a profile that silently never fires.
        Fail now, loudly, while the user is looking at the button they
        just pressed.
        """
        stored = self._library.get(preset_name)
        return self._profiles.upsert(device.id, device.name, stored.name)

    def unbind(self, device: AudioDevice) -> bool:
        return self._profiles.delete(device.id)

    def list_profiles(self) -> list[DeviceProfile]:
        return self._profiles.list_all()
