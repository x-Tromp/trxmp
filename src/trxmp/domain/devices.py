"""Audio output devices and the presets bound to them.

Two shapes again, for the same reason as the preset library:
:class:`AudioDevice` is a *value object* — a snapshot of what Windows
reports right now, replaced wholesale on the next poll, never edited.
:class:`DeviceProfile` is an *entity* — "the Sundara uses my Harman
curve" is a decision with an identity that outlives any snapshot, and
survives the headphones being unplugged.

The device ID is Windows' endpoint ID (``{0.0.0.00000000}.{guid}``).
It's stable across reboots, which is what makes profiles work at all —
but *not* always across re-enumeration: a wireless dongle can come back
with a fresh GUID, and Windows then treats it as a new device. That's
why :class:`DeviceProfile` also remembers ``device_name``: it lets the
UI say "Arctis Nova 5" for a profile whose device isn't currently
present, and it's the hook a future "this looks like the same
headphones" migration would hang on.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from trxmp.domain.errors import InvalidDeviceError

MAX_DEVICE_NAME_LENGTH = 200


class DeviceState(StrEnum):
    """Mirrors Windows' own endpoint states, because the distinctions
    are real and the UI needs all four."""

    ACTIVE = "active"  # plugged in and usable right now
    DISABLED = "disabled"  # exists, switched off in Sound settings
    UNPLUGGED = "unplugged"  # jack is empty, driver still there
    NOT_PRESENT = "not_present"  # hardware is gone; a ghost of a past device


@dataclass(frozen=True, slots=True)
class AudioDevice:
    """One audio *output*, as Windows sees it this instant.

    Outputs only. Windows enumerates microphones from the same API, and
    binding an EQ preset to a microphone is nonsense — the infrastructure
    layer filters to render endpoints so this type can't represent one.
    """

    id: str
    name: str
    state: DeviceState
    is_default: bool = False

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise InvalidDeviceError("device id cannot be empty")
        if not self.name.strip():
            raise InvalidDeviceError("device name cannot be empty")

    @property
    def is_usable(self) -> bool:
        """Whether audio can actually play through this device now."""
        return self.state is DeviceState.ACTIVE

    @property
    def is_known(self) -> bool:
        """Whether this device is worth showing at all.

        A real machine accumulates ghosts — this one reports 83 endpoints,
        61 of them NOT_PRESENT relics of monitors and headsets long gone.
        Listing those would bury the three devices the user actually owns.
        """
        return self.state is not DeviceState.NOT_PRESENT


@dataclass(frozen=True, slots=True)
class DeviceProfile:
    """A remembered decision: this device should use this preset."""

    device_id: str
    device_name: str
    preset_name: str
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if not self.device_id.strip():
            raise InvalidDeviceError("device id cannot be empty")
        if not self.preset_name.strip():
            raise InvalidDeviceError("profile must name a preset")
        if len(self.device_name) > MAX_DEVICE_NAME_LENGTH:
            raise InvalidDeviceError(
                f"device name is {len(self.device_name)} characters; "
                f"max is {MAX_DEVICE_NAME_LENGTH}"
            )
