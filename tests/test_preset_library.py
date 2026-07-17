"""Tests for the PresetLibrary service — the payoff of the Protocol.

None of these touch a database. Because ``PresetLibrary`` depends on the
``PresetRepository`` *Protocol*, not on SQLite, we hand it a dict-backed
fake and test every business rule in microseconds. That is the concrete,
demonstrable reason Dependency Inversion is worth the indirection.
"""

from __future__ import annotations

import pytest

from tests.fakes import InMemoryPresetRepository
from trxmp.application.preset_library import PresetLibrary
from trxmp.domain.equalizer import EqBand, EqPreset
from trxmp.domain.errors import DuplicatePresetError, PresetNotFoundError
from trxmp.dsp.biquad import FilterType


@pytest.fixture
def library() -> PresetLibrary:
    return PresetLibrary(InMemoryPresetRepository())


def _preset() -> EqPreset:
    return EqPreset(bands=(EqBand(FilterType.PEAKING, 1_000.0, 3.0, 1.0),))


def test_save_then_get_roundtrips(library: PresetLibrary) -> None:
    library.save("My EQ", _preset(), description="test")
    stored = library.get("My EQ")
    assert stored.name == "My EQ"
    assert stored.description == "test"
    assert len(stored.preset.bands) == 1


def test_get_unknown_preset_raises(library: PresetLibrary) -> None:
    with pytest.raises(PresetNotFoundError):
        library.get("nope")


def test_saving_duplicate_without_overwrite_raises(library: PresetLibrary) -> None:
    library.save("dup", _preset())
    with pytest.raises(DuplicatePresetError):
        library.save("dup", _preset())


def test_overwrite_replaces_and_preserves_creation_time(library: PresetLibrary) -> None:
    first = library.save("x", EqPreset.flat())
    updated = library.save("x", _preset(), overwrite=True)
    assert updated.created_at == first.created_at
    assert updated.updated_at >= first.updated_at
    assert len(library.get("x").preset.bands) == 1


def test_names_are_stripped_of_whitespace(library: PresetLibrary) -> None:
    library.save("  spacey  ", _preset())
    assert library.get("spacey").name == "spacey"


def test_delete_removes_and_missing_delete_raises(library: PresetLibrary) -> None:
    library.save("temp", _preset())
    library.delete("temp")
    with pytest.raises(PresetNotFoundError):
        library.get("temp")
    with pytest.raises(PresetNotFoundError):
        library.delete("temp")
