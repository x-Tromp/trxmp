"""Finding the Equalizer APO installation.

Registry first (authoritative — it's what the installer wrote), then the
conventional paths as a fallback for installs whose registry entry is
missing or was written by a portable/unusual setup.

``winreg`` is Windows-only, so the import is guarded by ``sys.platform``
rather than a try/except: mypy understands the platform check and type
checks each branch correctly, and on any other OS detection simply
returns "not installed" instead of exploding on import.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

if sys.platform == "win32":
    import winreg

_REGISTRY_SUBKEY = r"SOFTWARE\EqualizerAPO"
_REGISTRY_VALUE = "InstallPath"

_CONVENTIONAL_PATHS = (
    Path(r"C:\Program Files\EqualizerAPO"),
    Path(r"C:\Program Files (x86)\EqualizerAPO"),
)


@dataclass(frozen=True, slots=True)
class ApoInstallation:
    """Where Equalizer APO lives on this machine."""

    install_path: Path
    config_dir: Path

    @classmethod
    def at(cls, install_path: Path) -> ApoInstallation:
        return cls(install_path=install_path, config_dir=install_path / "config")


def detect_installation() -> ApoInstallation | None:
    """The installed Equalizer APO, or None if there isn't one.

    A directory only counts if its ``config`` folder exists: an install
    path whose config directory is gone is a broken install, and saying
    "not installed" is more useful than failing later at write time.
    """
    for path in _candidate_paths():
        installation = ApoInstallation.at(path)
        if installation.config_dir.is_dir():
            return installation
    return None


def _candidate_paths() -> Iterator[Path]:
    registry_path = _registry_install_path()
    if registry_path is not None:
        yield registry_path
    yield from _CONVENTIONAL_PATHS


def _registry_install_path() -> Path | None:
    if sys.platform != "win32":
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _REGISTRY_SUBKEY) as key:
            value, value_type = winreg.QueryValueEx(key, _REGISTRY_VALUE)
    except OSError:
        # Key or value absent — the normal "not installed" path, not an
        # error worth propagating.
        return None
    if value_type != winreg.REG_SZ or not isinstance(value, str):
        return None
    return Path(value)
