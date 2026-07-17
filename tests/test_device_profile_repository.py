"""SQLite device-profile repository, against a real temp database."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import Engine

from trxmp.infrastructure.database import create_database_engine
from trxmp.infrastructure.device_profile_repository import SqliteDeviceProfileRepository

ARCTIS_ID = "{0.0.0.00000000}.{bff4659e-58c3-4471-88a6-858356f87748}"


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return create_database_engine(tmp_path / "test.db")


@pytest.fixture
def repository(engine: Engine) -> SqliteDeviceProfileRepository:
    return SqliteDeviceProfileRepository(engine)


def test_get_missing_returns_none(repository: SqliteDeviceProfileRepository) -> None:
    assert repository.get("nothing") is None


def test_upsert_then_get_roundtrips(repository: SqliteDeviceProfileRepository) -> None:
    repository.upsert(ARCTIS_ID, "Arctis Nova 5", "Gaming")
    profile = repository.get(ARCTIS_ID)
    assert profile is not None
    assert profile.device_name == "Arctis Nova 5"
    assert profile.preset_name == "Gaming"


def test_upsert_is_idempotent_per_device(repository: SqliteDeviceProfileRepository) -> None:
    repository.upsert(ARCTIS_ID, "Arctis Nova 5", "Gaming")
    repository.upsert(ARCTIS_ID, "Arctis Nova 5", "Music")
    assert len(repository.list_all()) == 1
    profile = repository.get(ARCTIS_ID)
    assert profile is not None
    assert profile.preset_name == "Music"


def test_rebinding_refreshes_a_renamed_device(repository: SqliteDeviceProfileRepository) -> None:
    """Windows renames endpoints when drivers update. A profile showing a
    name from two years ago is a small lie the UI would repeat."""
    repository.upsert(ARCTIS_ID, "Headphones (Arctis Nova 5)", "Gaming")
    repository.upsert(ARCTIS_ID, "Headphones (2- Arctis Nova 5)", "Gaming")
    profile = repository.get(ARCTIS_ID)
    assert profile is not None
    assert profile.device_name == "Headphones (2- Arctis Nova 5)"


def test_profiles_survive_a_new_connection(engine: Engine) -> None:
    SqliteDeviceProfileRepository(engine).upsert(ARCTIS_ID, "Arctis", "Gaming")
    assert SqliteDeviceProfileRepository(engine).get(ARCTIS_ID) is not None


def test_delete(repository: SqliteDeviceProfileRepository) -> None:
    repository.upsert(ARCTIS_ID, "Arctis", "Gaming")
    assert repository.delete(ARCTIS_ID) is True
    assert repository.delete(ARCTIS_ID) is False
    assert repository.get(ARCTIS_ID) is None


def test_list_all_is_sorted_by_device_name(repository: SqliteDeviceProfileRepository) -> None:
    repository.upsert("id-c", "Zeta speakers", "A")
    repository.upsert("id-a", "Alpha headphones", "B")
    assert [p.device_name for p in repository.list_all()] == [
        "Alpha headphones",
        "Zeta speakers",
    ]
