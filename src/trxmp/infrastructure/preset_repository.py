"""SQLite implementation of the application's ``PresetRepository``.

Deliberately does NOT import the Protocol it implements: Python
Protocols are structural, so conformance is checked where a
``SqlitePresetRepository`` is passed to something expecting a
``PresetRepository`` (the composition root), and the infrastructure
layer keeps zero dependencies on the application layer.

Each method is one session, one transaction (``session.begin()``
commits on success, rolls back on any exception) — short transactions
are what keep SQLite happy under concurrent access.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from trxmp.domain.equalizer import EqBand, EqPreset
from trxmp.domain.library import StoredPreset
from trxmp.dsp.biquad import FilterType
from trxmp.infrastructure.database import BandRow, PresetRow


class SqlitePresetRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def get(self, name: str) -> StoredPreset | None:
        with Session(self._engine) as session:
            row = session.scalar(select(PresetRow).where(PresetRow.name == name))
            return None if row is None else _to_domain(row)

    def list_all(self) -> list[StoredPreset]:
        with Session(self._engine) as session:
            rows = session.scalars(select(PresetRow).order_by(PresetRow.name)).all()
            return [_to_domain(row) for row in rows]

    def upsert(self, name: str, description: str, preset: EqPreset) -> StoredPreset:
        now = datetime.now(UTC)
        with Session(self._engine) as session, session.begin():
            row = session.scalar(select(PresetRow).where(PresetRow.name == name))
            if row is None:
                row = PresetRow(name=name, created_at=now)
                session.add(row)
            row.description = description
            row.requested_preamp_db = preset.requested_preamp_db
            row.updated_at = now
            # Reassigning the collection + delete-orphan cascade = old
            # bands deleted, new ones inserted, in one transaction.
            row.bands = [
                BandRow(
                    position=index,
                    filter_type=band.filter_type.value,
                    frequency_hz=band.frequency_hz,
                    gain_db=band.gain_db,
                    q=band.q,
                )
                for index, band in enumerate(preset.bands)
            ]
            session.flush()
            return _to_domain(row)

    def delete(self, name: str) -> bool:
        with Session(self._engine) as session, session.begin():
            row = session.scalar(select(PresetRow).where(PresetRow.name == name))
            if row is None:
                return False
            session.delete(row)
            return True


def _to_domain(row: PresetRow) -> StoredPreset:
    """Rows → domain objects. Reconstructing through the real domain
    constructors means data corrupted at rest still can't smuggle an
    invalid preset into the running app."""
    bands = tuple(
        EqBand(FilterType(band.filter_type), band.frequency_hz, band.gain_db, band.q)
        for band in row.bands
    )
    return StoredPreset(
        name=row.name,
        description=row.description,
        preset=EqPreset(bands=bands, requested_preamp_db=row.requested_preamp_db),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
