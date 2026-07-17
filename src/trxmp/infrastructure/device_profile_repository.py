"""SQLite implementation of ``DeviceProfileRepository``.

Same shape as the preset repository: one session per method, one
transaction, rows mapped back through the real domain constructors.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from trxmp.domain.devices import DeviceProfile
from trxmp.infrastructure.database import DeviceProfileRow


class SqliteDeviceProfileRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def get(self, device_id: str) -> DeviceProfile | None:
        with Session(self._engine) as session:
            row = session.scalar(
                select(DeviceProfileRow).where(DeviceProfileRow.device_id == device_id)
            )
            return None if row is None else _to_domain(row)

    def list_all(self) -> list[DeviceProfile]:
        with Session(self._engine) as session:
            rows = session.scalars(
                select(DeviceProfileRow).order_by(DeviceProfileRow.device_name)
            ).all()
            return [_to_domain(row) for row in rows]

    def upsert(self, device_id: str, device_name: str, preset_name: str) -> DeviceProfile:
        now = datetime.now(UTC)
        with Session(self._engine) as session, session.begin():
            row = session.scalar(
                select(DeviceProfileRow).where(DeviceProfileRow.device_id == device_id)
            )
            if row is None:
                row = DeviceProfileRow(device_id=device_id, created_at=now)
                session.add(row)
            # The name is refreshed on every bind: Windows renames endpoints
            # (drivers update, users rename them in Sound settings), and a
            # profile showing a name from two years ago is a small lie.
            row.device_name = device_name
            row.preset_name = preset_name
            row.updated_at = now
            session.flush()
            return _to_domain(row)

    def delete(self, device_id: str) -> bool:
        with Session(self._engine) as session, session.begin():
            row = session.scalar(
                select(DeviceProfileRow).where(DeviceProfileRow.device_id == device_id)
            )
            if row is None:
                return False
            session.delete(row)
            return True


def _to_domain(row: DeviceProfileRow) -> DeviceProfile:
    return DeviceProfile(
        device_id=row.device_id,
        device_name=row.device_name,
        preset_name=row.preset_name,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
