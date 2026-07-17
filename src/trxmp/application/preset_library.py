"""Use cases for managing the preset library.

This module *declares* the storage interface it needs
(:class:`PresetRepository`) and infrastructure *conforms* to it — the
Dependency Inversion Principle in its Python form. Note that the SQLite
implementation never imports this Protocol: Python Protocols are
structural ("if it has these methods, it fits"), so the dependency
arrow stays pointing inward while mypy still verifies the contract at
the composition root.
"""

from __future__ import annotations

from typing import Protocol

from trxmp.domain.equalizer import EqPreset
from trxmp.domain.errors import DuplicatePresetError, PresetNotFoundError
from trxmp.domain.library import StoredPreset


class PresetRepository(Protocol):
    """What the application needs from preset storage — nothing more."""

    def get(self, name: str) -> StoredPreset | None: ...

    def list_all(self) -> list[StoredPreset]: ...

    def upsert(self, name: str, description: str, preset: EqPreset) -> StoredPreset: ...

    def delete(self, name: str) -> bool: ...


class PresetLibrary:
    """The preset library's business rules, independent of storage.

    Policy lives here (duplicate handling, name normalization); the
    repository stays a dumb data mapper. That split is what makes this
    class testable with an in-memory fake — no database required.
    """

    def __init__(self, repository: PresetRepository) -> None:
        self._repository = repository

    def save(
        self,
        name: str,
        preset: EqPreset,
        description: str = "",
        *,
        overwrite: bool = False,
    ) -> StoredPreset:
        name = name.strip()
        if not overwrite and self._repository.get(name) is not None:
            raise DuplicatePresetError(
                f"a preset named {name!r} already exists (use overwrite to replace it)"
            )
        return self._repository.upsert(name, description, preset)

    def get(self, name: str) -> StoredPreset:
        stored = self._repository.get(name.strip())
        if stored is None:
            raise PresetNotFoundError(f"no preset named {name!r} in the library")
        return stored

    def list_all(self) -> list[StoredPreset]:
        return self._repository.list_all()

    def delete(self, name: str) -> None:
        if not self._repository.delete(name.strip()):
            raise PresetNotFoundError(f"no preset named {name!r} in the library")
