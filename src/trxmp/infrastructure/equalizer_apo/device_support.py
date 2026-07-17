"""Is Equalizer APO actually installed *on this device*?

The question this module exists to answer prevents Trxmp's most
confusing possible failure. Equalizer APO is installed per audio device,
not once for the machine: its installer asks you to tick which endpoints
to hook. So a user can have APO installed, Trxmp reporting "active",
their curve looking perfect — and hear absolutely nothing change,
because they switched to a device APO was never attached to. They'd
blame their ears, or us.

Windows records each endpoint's effect chain under::

    HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\MMDevices\\Audio\\
        Render\\{endpoint-guid}\\FxProperties

where the value ``{d04e05a6-…},5`` (PKEY_FX_PreMixEffectClsid) names the
APO that runs before the mixer. If it's Equalizer APO's CLSID, we're in
that device's chain. On this developer's machine the Arctis Nova 5 and
the NVIDIA endpoint say Equalizer APO; the Realtek digital output says
``{EACD2258-…}`` — Realtek's own effects — and would silently ignore
everything Trxmp writes.

Read-only, and best-effort: if the key can't be read we say "unknown"
rather than "broken". A missing registry key is not a reason to refuse
to equalize.
"""

from __future__ import annotations

import sys

if sys.platform == "win32":
    import winreg

_MMDEVICES_RENDER = r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Render"

# PKEY_FX_PreMixEffectClsid / PKEY_FX_PostMixEffectClsid: the LFX and GFX
# slots in an endpoint's effect chain.
_PKEY_FX_PREMIX = "{d04e05a6-594b-4fb6-a80d-01af5eed7d1d},5"
_PKEY_FX_POSTMIX = "{d04e05a6-594b-4fb6-a80d-01af5eed7d1d},6"

# Equalizer APO's own CLSIDs, as its installer writes them.
_APO_CLSIDS = {
    "{C9453E73-8C5C-4463-9984-AF8BAB2F5447}",  # LFX
    "{13AB3EBD-137E-4903-9D89-60BE8277FD17}",  # GFX
}


def is_apo_enabled_for_device(device_id: str) -> bool | None:
    """True/False if we could tell, None if the registry didn't say.

    A tri-state on purpose: "no APO on this device" is a warning worth
    showing the user, but "couldn't read the registry" is not the same
    claim and must not be dressed up as one.
    """
    if sys.platform != "win32":
        return None
    guid = _endpoint_guid(device_id)
    if guid is None:
        return None
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, rf"{_MMDEVICES_RENDER}\{guid}\FxProperties"
        ) as key:
            values = {
                _read_value(key, _PKEY_FX_PREMIX),
                _read_value(key, _PKEY_FX_POSTMIX),
            }
    except OSError:
        return None
    if values == {None}:  # key exists but names no effects at all
        return False
    return bool(values & _APO_CLSIDS)


def _endpoint_guid(device_id: str) -> str | None:
    """``{0.0.0.00000000}.{bff4…}`` -> ``{bff4…}``, the registry key name."""
    _, separator, guid = device_id.partition("}.")
    if not separator or not guid.startswith("{"):
        return None
    return guid


def _read_value(key: object, name: str) -> str | None:
    try:
        value, _ = winreg.QueryValueEx(key, name)  # type: ignore[arg-type]
    except OSError:
        return None
    return value.upper() if isinstance(value, str) else None
