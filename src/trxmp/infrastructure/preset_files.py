"""Preset interchange: JSON / YAML / CSV import and export.

Pydantic lives HERE, at the file boundary — not in the domain. The
domain's dataclasses enforce business rules among trusted code; Pydantic
earns its keep parsing *untrusted input* (files a friend emailed you).

Two-layer validation, on purpose:
1. **Shape** (Pydantic): required fields, correct types, no unknown
   keys (``extra="forbid"`` turns typos like ``"gian_db"`` into errors
   instead of silently ignored data).
2. **Business rules** (domain): converting to :class:`EqPreset` runs
   the real guardrails — a file can be perfectly well-formed JSON and
   still demand a +30 dB boost; only the domain knows that's invalid.

CSV is a deliberately lossy format (bands only — no name, description
or preamp; a flat table can't represent them). It exists because
spreadsheets are how audio folks actually share measurement data.
"""

from __future__ import annotations

import csv
from io import StringIO
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from trxmp.domain.equalizer import EqBand, EqPreset
from trxmp.dsp.biquad import FilterType

_CSV_COLUMNS = ("filter_type", "frequency_hz", "gain_db", "q")


class BandDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filter_type: FilterType
    frequency_hz: float
    gain_db: float = 0.0
    q: float = 0.7071


class PresetDocument(BaseModel):
    """The on-disk preset format, version 1.

    ``format`` and ``version`` are ``Literal`` fields: a file claiming
    ``version: 2`` fails validation *now* with a clear message, instead
    of half-parsing under wrong assumptions. Cheap forward
    compatibility.
    """

    model_config = ConfigDict(extra="forbid")

    format: Literal["trxmp-preset"] = "trxmp-preset"
    version: Literal[1] = 1
    name: str = Field(min_length=1, max_length=100)
    description: str = ""
    preamp_db: float = 0.0
    bands: tuple[BandDocument, ...] = ()

    @classmethod
    def from_domain(cls, name: str, preset: EqPreset, description: str = "") -> PresetDocument:
        return cls(
            name=name,
            description=description,
            preamp_db=preset.requested_preamp_db,
            bands=tuple(
                BandDocument(
                    filter_type=band.filter_type,
                    frequency_hz=band.frequency_hz,
                    gain_db=band.gain_db,
                    q=band.q,
                )
                for band in preset.bands
            ),
        )

    def to_domain(self) -> EqPreset:
        """Shape-valid → rule-valid, or a domain error explaining why."""
        return EqPreset(
            bands=tuple(
                EqBand(band.filter_type, band.frequency_hz, band.gain_db, band.q)
                for band in self.bands
            ),
            requested_preamp_db=self.preamp_db,
        )


def load_preset_file(path: Path) -> PresetDocument:
    """Parse a preset file, dispatching on extension (.json/.yaml/.yml/.csv)."""
    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8")
    if suffix == ".json":
        return PresetDocument.model_validate_json(text)
    if suffix in (".yaml", ".yml"):
        return PresetDocument.model_validate(yaml.safe_load(text))
    if suffix == ".csv":
        return _csv_to_document(text, default_name=path.stem)
    raise ValueError(f"unsupported preset format {suffix!r} (use .json, .yaml, .yml or .csv)")


def save_preset_file(path: Path, document: PresetDocument) -> None:
    suffix = path.suffix.lower()
    if suffix == ".json":
        path.write_text(document.model_dump_json(indent=2) + "\n", encoding="utf-8")
    elif suffix in (".yaml", ".yml"):
        # mode="json" first: yaml doesn't know Pydantic models or enums,
        # so we hand it plain dicts/strings.
        text = yaml.safe_dump(document.model_dump(mode="json"), sort_keys=False)
        path.write_text(text, encoding="utf-8")
    elif suffix == ".csv":
        path.write_text(_document_to_csv(document), encoding="utf-8")
    else:
        raise ValueError(f"unsupported preset format {suffix!r} (use .json, .yaml, .yml or .csv)")


def _csv_to_document(text: str, default_name: str) -> PresetDocument:
    reader = csv.DictReader(StringIO(text))
    rows = [{key: value for key, value in row.items() if key in _CSV_COLUMNS} for row in reader]
    return PresetDocument(
        name=default_name,
        bands=tuple(BandDocument.model_validate(row) for row in rows),
    )


def _document_to_csv(document: PresetDocument) -> str:
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=_CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for band in document.bands:
        writer.writerow(band.model_dump(mode="json"))
    return buffer.getvalue()
