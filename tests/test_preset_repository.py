"""Tests for the SQLite repository — against a real, temporary database.

The Protocol tests (test_preset_library) prove the *logic*; these prove
the *adapter* really persists to SQLite: bands survive a roundtrip in
order, upsert replaces cleanly, cascade delete leaves no orphans.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from trxmp.domain.equalizer import EqBand, EqPreset
from trxmp.dsp.biquad import FilterType
from trxmp.infrastructure.database import BandRow, create_database_engine
from trxmp.infrastructure.preset_repository import SqlitePresetRepository


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return create_database_engine(tmp_path / "test.db")


@pytest.fixture
def repository(engine: Engine) -> SqlitePresetRepository:
    return SqlitePresetRepository(engine)


def _multiband_preset() -> EqPreset:
    return EqPreset(
        bands=(
            EqBand(FilterType.LOW_SHELF, 60.0, 4.0, 0.7),
            EqBand(FilterType.PEAKING, 1_000.0, -3.0, 1.5),
            EqBand(FilterType.HIGH_SHELF, 10_000.0, 2.0, 0.7),
        ),
        requested_preamp_db=-2.0,
    )


def test_get_missing_returns_none(repository: SqlitePresetRepository) -> None:
    assert repository.get("nothing") is None


def test_upsert_then_get_preserves_everything_including_band_order(
    repository: SqlitePresetRepository,
) -> None:
    repository.upsert("multi", "three bands", _multiband_preset())
    stored = repository.get("multi")

    assert stored is not None
    assert stored.description == "three bands"
    assert stored.preset.requested_preamp_db == -2.0
    # Order must survive: a graphic EQ reordered on reload is a real bug.
    types = [band.filter_type for band in stored.preset.bands]
    assert types == [FilterType.LOW_SHELF, FilterType.PEAKING, FilterType.HIGH_SHELF]
    assert stored.preset.bands[1].gain_db == -3.0


def test_upsert_is_idempotent_on_name_and_replaces_bands(
    repository: SqlitePresetRepository, engine: Engine
) -> None:
    repository.upsert("x", "", _multiband_preset())  # 3 bands
    repository.upsert("x", "", EqPreset(bands=(EqBand(FilterType.PEAKING, 500.0, 1.0, 1.0),)))

    assert len(repository.list_all()) == 1  # still one preset, not two
    stored = repository.get("x")
    assert stored is not None
    assert len(stored.preset.bands) == 1

    # The delete-orphan cascade must have removed the old 3 bands, not
    # left them dangling with a null parent.
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(BandRow)) == 1


def test_delete_removes_preset_and_reports_success(repository: SqlitePresetRepository) -> None:
    repository.upsert("temp", "", _multiband_preset())
    assert repository.delete("temp") is True
    assert repository.delete("temp") is False
    assert repository.get("temp") is None


def test_deleting_preset_cascades_to_bands(
    repository: SqlitePresetRepository, engine: Engine
) -> None:
    repository.upsert("temp", "", _multiband_preset())
    repository.delete("temp")
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(BandRow)) == 0


def test_list_all_is_sorted_by_name(repository: SqlitePresetRepository) -> None:
    for name in ("charlie", "alpha", "bravo"):
        repository.upsert(name, "", EqPreset.flat())
    assert [item.name for item in repository.list_all()] == ["alpha", "bravo", "charlie"]
