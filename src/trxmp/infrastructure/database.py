"""SQLAlchemy setup: ORM rows and engine factories.

The ORM classes here are *persistence* models, deliberately separate
from the domain's dataclasses. Rows know about tables, foreign keys and
cascades; the domain knows about guardrails and headroom. Merging the
two (the Active Record shortcut) couples business rules to the database
forever — the repository translates between them instead.

Bands are a normalized child table rather than a JSON blob so the
schema is honest about its shape: position, per-band columns, and a
delete-orphan cascade that makes "replace this preset's bands" a single
assignment in the repository.

Schema creation is ``create_all`` (idempotent) — fine while the schema
is young. When it starts evolving with real user data in the wild,
Alembic migrations replace it (noted in the roadmap).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sqlalchemy import Engine, ForeignKey, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from trxmp.infrastructure.paths import data_dir

DATABASE_FILENAME = "trxmp.db"


class Base(DeclarativeBase):
    pass


class PresetRow(Base):
    __tablename__ = "presets"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    requested_preamp_db: Mapped[float] = mapped_column(default=0.0)
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]

    bands: Mapped[list[BandRow]] = relationship(
        back_populates="preset",
        cascade="all, delete-orphan",
        order_by="BandRow.position",
    )


class DeviceProfileRow(Base):
    """Which preset a device should use.

    Deliberately *not* a foreign key to ``presets``: a profile must
    survive its preset being deleted. The alternative (ON DELETE CASCADE)
    would silently erase the user's device bindings the moment they tidy
    up their preset list — losing a decision they never asked to undo.
    The stale binding is resolved by name at read time instead, and a
    dangling one simply means "don't switch automatically".
    """

    __tablename__ = "device_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    device_name: Mapped[str] = mapped_column(String(200))
    preset_name: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]


class BandRow(Base):
    __tablename__ = "preset_bands"

    id: Mapped[int] = mapped_column(primary_key=True)
    preset_id: Mapped[int] = mapped_column(ForeignKey("presets.id", ondelete="CASCADE"))
    position: Mapped[int]
    filter_type: Mapped[str] = mapped_column(String(20))
    frequency_hz: Mapped[float]
    gain_db: Mapped[float]
    q: Mapped[float]

    preset: Mapped[PresetRow] = relationship(back_populates="bands")


def create_database_engine(db_path: Path) -> Engine:
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    return engine


def create_default_engine() -> Engine:
    return create_database_engine(data_dir() / DATABASE_FILENAME)
