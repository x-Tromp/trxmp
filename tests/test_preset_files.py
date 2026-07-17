"""Tests for preset import/export — the Pydantic boundary.

Two things get proven here: (1) a preset survives a roundtrip through
each format unchanged, and (2) malformed input is *rejected with a clear
error*, not silently half-parsed. The second is the whole reason
Pydantic is here rather than a hand-written ``json.loads``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from trxmp.domain.equalizer import EqBand, EqPreset
from trxmp.domain.errors import InvalidBandError
from trxmp.dsp.biquad import FilterType
from trxmp.infrastructure.preset_files import (
    PresetDocument,
    load_preset_file,
    save_preset_file,
)


def _preset() -> EqPreset:
    return EqPreset(
        bands=(
            EqBand(FilterType.LOW_SHELF, 60.0, 4.0, 0.7),
            EqBand(FilterType.PEAKING, 1_000.0, -3.0, 1.5),
        ),
        requested_preamp_db=-1.5,
    )


@pytest.mark.parametrize("extension", [".json", ".yaml", ".yml", ".csv"])
def test_export_then_import_roundtrips_bands(tmp_path: Path, extension: str) -> None:
    document = PresetDocument.from_domain("Test", _preset(), "a description")
    path = tmp_path / f"preset{extension}"
    save_preset_file(path, document)

    reloaded = load_preset_file(path).to_domain()
    original = _preset()

    assert len(reloaded.bands) == len(original.bands)
    for got, want in zip(reloaded.bands, original.bands, strict=True):
        assert got.filter_type == want.filter_type
        assert got.frequency_hz == pytest.approx(want.frequency_hz)
        assert got.gain_db == pytest.approx(want.gain_db)
        assert got.q == pytest.approx(want.q)


def test_json_roundtrip_preserves_name_description_and_preamp(tmp_path: Path) -> None:
    """CSV can't carry these (it's bands-only); JSON/YAML must."""
    document = PresetDocument.from_domain("Sundara", _preset(), "harman-ish")
    path = tmp_path / "p.json"
    save_preset_file(path, document)

    reloaded = load_preset_file(path)
    assert reloaded.name == "Sundara"
    assert reloaded.description == "harman-ish"
    assert reloaded.preamp_db == -1.5


def test_rejects_unknown_field(tmp_path: Path) -> None:
    """extra='forbid' turns a typo'd key into a loud error instead of
    silently dropped data — the single most valuable line in the model."""
    path = tmp_path / "typo.json"
    path.write_text(
        '{"format": "trxmp-preset", "version": 1, "name": "x", '
        '"bands": [{"filter_type": "peaking", "frequency_hz": 1000, "gian_db": 3}]}',
        encoding="utf-8",
    )
    with pytest.raises(ValidationError, match="gian_db"):
        load_preset_file(path)


def test_rejects_wrong_version(tmp_path: Path) -> None:
    path = tmp_path / "v2.json"
    path.write_text('{"name": "x", "version": 2, "bands": []}', encoding="utf-8")
    with pytest.raises(ValidationError):
        load_preset_file(path)


def test_rejects_unknown_filter_type(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(
        '{"name": "x", "bands": [{"filter_type": "wobble", "frequency_hz": 1000}]}',
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        load_preset_file(path)


def test_shape_valid_but_business_invalid_is_caught_by_domain(tmp_path: Path) -> None:
    """A perfectly well-formed file can still request an illegal +30 dB
    boost. Pydantic validates shape; only .to_domain() enforces the
    audio guardrails. This is why the two-layer split exists."""
    path = tmp_path / "loud.json"
    path.write_text(
        '{"name": "x", "bands": [{"filter_type": "peaking", "frequency_hz": 1000, "gain_db": 30}]}',
        encoding="utf-8",
    )
    document = load_preset_file(path)  # shape is fine
    with pytest.raises(InvalidBandError):  # business rules are not
        document.to_domain()


def test_unsupported_extension_raises(tmp_path: Path) -> None:
    path = tmp_path / "preset.txt"
    path.write_text("whatever", encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported preset format"):
        load_preset_file(path)


def test_csv_uses_filename_as_preset_name(tmp_path: Path) -> None:
    path = tmp_path / "my-curve.csv"
    path.write_text(
        "filter_type,frequency_hz,gain_db,q\npeaking,1000,3.0,1.0\n",
        encoding="utf-8",
    )
    document = load_preset_file(path)
    assert document.name == "my-curve"
    assert len(document.bands) == 1
