"""Reading Windows' audio outputs, via pycaw's wrapper over Core Audio.

Three decisions worth knowing about:

**Render endpoints only.** ``AudioUtilities.GetAllDevices()`` returns
microphones and speakers in one list, and this machine's ID prefixes
(``{0.0.0.…}`` for output, ``{0.0.1.…}`` for input) make it tempting to
filter by string. We ask Core Audio properly instead —
``EnumAudioEndpoints(eRender, …)`` — because that's the documented
question, and guessing from an ID's shape is the kind of thing that
works until the day it doesn't.

**eMultimedia, not eConsole.** Windows keeps three "default device"
roles. Media players follow eMultimedia; eCommunications is the one that
flips to your headset when a call starts. An equalizer follows the music.

**Nothing here raises.** Core Audio is COM: devices vanish mid-call, the
service restarts, a driver misbehaves. Every failure here degrades to
"no devices" so a flaky driver can never take the window down. The
diagnosis belongs in a log, not in the user's face.
"""

from __future__ import annotations

import sys

from trxmp.domain.devices import AudioDevice, DeviceState

if sys.platform == "win32":
    from pycaw.constants import DEVICE_STATE, EDataFlow, ERole
    from pycaw.pycaw import AudioDeviceState, AudioUtilities

    _STATES = {
        AudioDeviceState.Active: DeviceState.ACTIVE,
        AudioDeviceState.Disabled: DeviceState.DISABLED,
        AudioDeviceState.Unplugged: DeviceState.UNPLUGGED,
        AudioDeviceState.NotPresent: DeviceState.NOT_PRESENT,
    }


class PycawDeviceService:
    """The real Windows implementation of ``AudioDeviceService``."""

    def list_output_devices(self) -> list[AudioDevice]:
        if sys.platform != "win32":
            return []
        try:
            default_id = self._default_id()
            enumerator = AudioUtilities.GetDeviceEnumerator()
            collection = enumerator.EnumAudioEndpoints(
                EDataFlow.eRender.value, DEVICE_STATE.MASK_ALL.value
            )
            devices = []
            for index in range(collection.GetCount()):
                raw = AudioUtilities.CreateDevice(collection.Item(index))
                device = _to_domain(raw, default_id)
                if device is not None:
                    devices.append(device)
        except Exception:  # COM throws a whole zoo; see the module docstring
            return []
        return sorted(devices, key=lambda d: (not d.is_default, d.name.lower()))

    def default_output_device(self) -> AudioDevice | None:
        if sys.platform != "win32":
            return None
        try:
            raw = AudioUtilities.GetSpeakers()
            return _to_domain(raw, default_id=raw.id)
        except Exception:
            return None

    def _default_id(self) -> str | None:
        try:
            enumerator = AudioUtilities.GetDeviceEnumerator()
            endpoint = enumerator.GetDefaultAudioEndpoint(
                EDataFlow.eRender.value, ERole.eMultimedia.value
            )
            return str(AudioUtilities.CreateDevice(endpoint).id)
        except Exception:  # having no default device at all is a legal state
            return None


def _to_domain(raw: object, default_id: str | None) -> AudioDevice | None:
    """pycaw object -> domain value object, or None if unusable.

    Windows will happily report an endpoint with no friendly name (a
    half-installed driver). Dropping it beats showing the user a blank
    row or crashing the domain's non-empty-name rule.
    """
    device_id = getattr(raw, "id", None)
    name = getattr(raw, "FriendlyName", None)
    if not device_id or not name:
        return None
    return AudioDevice(
        id=str(device_id),
        name=str(name),
        state=_STATES.get(getattr(raw, "state", None), DeviceState.NOT_PRESENT),
        is_default=str(device_id) == default_id,
    )
