"""Shared test doubles.

Every Protocol the application layer declares gets a fake here. They live
in one module rather than being imported test-file-to-test-file, which
keeps the dependency graph of the suite as tidy as the app's own.

That these are so short is the argument for Protocols in miniature: a
complete preset repository is fifteen lines and a dict. The real SQLite
one has its own tests; everything *above* it can be exercised at memory
speed with no database, no files, and no audio hardware.
"""

from __future__ import annotations

from datetime import UTC, datetime

from trxmp.application.audio_backend import BackendError, BackendState, BackendStatus
from trxmp.application.preferences import Preferences
from trxmp.domain.devices import AudioDevice, DeviceProfile, DeviceState
from trxmp.domain.equalizer import EqPreset
from trxmp.domain.library import StoredPreset

ARCTIS = AudioDevice(
    id="arctis-id", name="Arctis Nova 5", state=DeviceState.ACTIVE, is_default=True
)
SPEAKERS = AudioDevice(id="speaker-id", name="Speakers", state=DeviceState.ACTIVE)


class InMemoryPresetRepository:
    """A complete PresetRepository with no I/O — structural typing means
    it needs no base class or registration to satisfy the Protocol."""

    def __init__(self) -> None:
        self._items: dict[str, StoredPreset] = {}

    def get(self, name: str) -> StoredPreset | None:
        return self._items.get(name)

    def list_all(self) -> list[StoredPreset]:
        return [self._items[name] for name in sorted(self._items)]

    def upsert(self, name: str, description: str, preset: EqPreset) -> StoredPreset:
        now = datetime.now(UTC)
        created = self._items[name].created_at if name in self._items else now
        stored = StoredPreset(name, description, preset, created_at=created, updated_at=now)
        self._items[name] = stored
        return stored

    def delete(self, name: str) -> bool:
        return self._items.pop(name, None) is not None


class InMemoryDeviceProfileRepository:
    def __init__(self) -> None:
        self._items: dict[str, DeviceProfile] = {}

    def get(self, device_id: str) -> DeviceProfile | None:
        return self._items.get(device_id)

    def list_all(self) -> list[DeviceProfile]:
        return [self._items[key] for key in sorted(self._items)]

    def upsert(self, device_id: str, device_name: str, preset_name: str) -> DeviceProfile:
        now = datetime.now(UTC)
        created = self._items[device_id].created_at if device_id in self._items else now
        profile = DeviceProfile(device_id, device_name, preset_name, created, now)
        self._items[device_id] = profile
        return profile

    def delete(self, device_id: str) -> bool:
        return self._items.pop(device_id, None) is not None


class FakePreferencesStore:
    def __init__(self, preferences: Preferences | None = None) -> None:
        self.preferences = preferences or Preferences()
        self.save_count = 0

    def load(self) -> Preferences:
        return self.preferences

    def save(self, preferences: Preferences) -> None:
        self.preferences = preferences
        self.save_count += 1


class FakeBackend:
    """An audio backend that records instead of touching the system."""

    def __init__(self, state: BackendState = BackendState.READY) -> None:
        self.applied: list[EqPreset] = []
        self.disable_count = 0
        self.state = state
        self.fail_with: str | None = None

    @property
    def name(self) -> str:
        return "Fake"

    @property
    def status(self) -> BackendStatus:
        return BackendStatus(self.state, "fake backend detail")

    def apply(self, preset: EqPreset) -> None:
        if self.fail_with:
            raise BackendError(self.fail_with)
        self.applied.append(preset)
        self.state = BackendState.ACTIVE

    def disable(self) -> None:
        self.disable_count += 1
        self.state = BackendState.READY


class FakeDeviceService:
    def __init__(self, default: AudioDevice | None = ARCTIS) -> None:
        self.default = default
        self.poll_count = 0

    def list_output_devices(self) -> list[AudioDevice]:
        return [ARCTIS, SPEAKERS]

    def default_output_device(self) -> AudioDevice | None:
        self.poll_count += 1
        return self.default
