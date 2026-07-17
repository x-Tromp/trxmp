"""Importing presets from other people's formats.

Trxmp's own format is a closed loop we control. These are not: an
AutoEQ `ParametricEQ.txt`, an Equalizer APO config, a `.peace` file
someone emailed you. They were written by tools with their own feature
sets, and the interesting engineering is not the parsing — it's deciding
what to do about the parts that don't fit.

Three responses, and the choice between them is the whole design:

- **Translate** what maps cleanly (a PK filter is our PEAKING band).
- **Warn** where we import something *smaller* than the file describes
  (Peace's per-channel gains, its extra bass boost). The user gets their
  curve and an honest note about what was left behind.
- **Refuse** where importing would produce *wrong audio* silently (a
  notch filter we cannot represent, a filter type code we'd be guessing
  at). Dropping a notch means an untamed resonance the user will hear
  and blame on us.

The rule underneath: never silently produce audio that differs from what
the file asked for. Warnings are for "less than you asked", errors are
for "different from what you asked".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from trxmp.domain.equalizer import EqPreset
from trxmp.domain.errors import PresetImportError
from trxmp.infrastructure.importers.apo_config import parse_apo_config
from trxmp.infrastructure.importers.peace_config import parse_peace_config
from trxmp.infrastructure.preset_files import load_preset_file


@dataclass(frozen=True, slots=True)
class ImportedPreset:
    """A preset from a foreign format, plus what got lost on the way."""

    name: str
    preset: EqPreset
    source_format: str
    description: str = ""
    warnings: tuple[str, ...] = field(default_factory=tuple)


def import_preset_file(path: Path) -> ImportedPreset:
    """Read any supported preset file.

    Dispatch is by extension, with ``.txt`` meaning "Equalizer APO or
    AutoEQ" — the format AutoEQ publishes for every headphone in its
    database, which is what makes that one parser worth more than the
    rest combined.
    """
    suffix = path.suffix.lower()
    text = _read_text(path)

    if suffix in (".json", ".yaml", ".yml", ".csv"):
        document = load_preset_file(path)
        return ImportedPreset(
            name=document.name,
            preset=document.to_domain(),
            source_format="trxmp",
            description=document.description,
        )
    if suffix == ".txt":
        preset, warnings = parse_apo_config(text)
        return ImportedPreset(
            name=path.stem, preset=preset, source_format="equalizer-apo", warnings=warnings
        )
    if suffix == ".peace":
        preset, description, warnings = parse_peace_config(text)
        return ImportedPreset(
            name=path.stem,
            preset=preset,
            source_format="peace",
            description=description,
            warnings=warnings,
        )
    raise PresetImportError(
        f"unsupported preset format {suffix!r} "
        "(use .json, .yaml, .csv, .txt for Equalizer APO/AutoEQ, or .peace)"
    )


def _read_text(path: Path) -> str:
    """Read a file written by someone else's tool.

    ``utf-8-sig`` strips the BOM Windows editors leave behind, and the
    latin-1 fallback exists because a .peace file written on a machine
    with a non-UTF-8 code page is a real thing to meet — and a headphone
    name with an accent in it is not a reason to refuse the import.
    """
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return path.read_text(encoding="latin-1")
