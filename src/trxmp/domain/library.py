"""Preset library entities.

:class:`~trxmp.domain.equalizer.EqPreset` is a *value object*: two
presets with the same bands are interchangeable, like two copies of the
number 7. :class:`StoredPreset` is an *entity*: it has an identity (its
name) that persists while its contents change over time. Keeping the
distinction explicit is classic domain modeling — value objects stay
free to be shared and compared by value; entities carry identity and
audit history.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from trxmp.domain.equalizer import EqPreset
from trxmp.domain.errors import InvalidPresetError

MAX_NAME_LENGTH = 100


@dataclass(frozen=True, slots=True)
class StoredPreset:
    """A named preset as it exists in the library.

    Timestamps are UTC. This object is a read model — instances are
    produced by the repository; mutating the library happens through
    the :class:`~trxmp.application.preset_library.PresetLibrary` service.
    """

    name: str
    description: str
    preset: EqPreset
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise InvalidPresetError("preset name cannot be empty")
        if len(self.name) > MAX_NAME_LENGTH:
            raise InvalidPresetError(
                f"preset name is {len(self.name)} characters; max is {MAX_NAME_LENGTH}"
            )
