"""Loading and validating the bundled knowledge base.

Pydantic at the boundary, same rule as every other file this app reads
(``preset_files.py``, the M6 importers): the YAML shape is validated
with ``extra="forbid"`` so a typo'd key fails loudly at load time
instead of silently vanishing, and the *values* are validated a second
time by constructing real domain objects — a correction band with an
out-of-range gain is rejected by :class:`~trxmp.domain.equalizer.EqBand`
itself, not by some parallel copy of its rules living here.

Loaded via :mod:`importlib.resources` rather than a path built from
``__file__``: that's what keeps this working whether Trxmp is running
from a source checkout, an installed wheel, or (in principle) a zipped
package — a plain ``Path(__file__).parent / "..."`` would break the
moment the package stops being a loose directory on disk.
"""

from __future__ import annotations

from functools import lru_cache
from importlib import resources

import yaml
from pydantic import BaseModel, ConfigDict

from trxmp.domain.equalizer import EqBand
from trxmp.domain.errors import EqualizerError, InvalidReferenceDataError
from trxmp.domain.reference import FrequencyBand, HeadphoneCategory, HeadphoneModel
from trxmp.dsp.biquad import FilterType

_FREQUENCY_BANDS_FILE = "frequency_bands.yaml"
_HEADPHONES_FILE = "headphones.yaml"


class _CorrectionBandDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filter_type: FilterType
    frequency_hz: float
    gain_db: float = 0.0
    q: float = 0.7071


class _HeadphoneDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    manufacturer: str
    category: HeadphoneCategory
    correction: tuple[_CorrectionBandDocument, ...] = ()
    notes: str = ""
    is_measured: bool = False
    source: str = ""


class _HeadphonesFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    headphones: tuple[_HeadphoneDocument, ...]


class _FrequencyBandDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    low_hz: float
    high_hz: float
    description: str


class _FrequencyBandsFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bands: tuple[_FrequencyBandDocument, ...]


def _read_bundled_yaml(filename: str) -> object:
    package = resources.files(__package__)
    with resources.as_file(package / filename) as path:
        text = path.read_text(encoding="utf-8")
    return yaml.safe_load(text)


def _load_headphones() -> tuple[HeadphoneModel, ...]:
    raw = _read_bundled_yaml(_HEADPHONES_FILE)
    try:
        document = _HeadphonesFile.model_validate(raw)
        headphones = []
        for entry in document.headphones:
            bands = tuple(
                EqBand(band.filter_type, band.frequency_hz, band.gain_db, band.q)
                for band in entry.correction
            )
            headphones.append(
                HeadphoneModel(
                    id=entry.id,
                    name=entry.name,
                    manufacturer=entry.manufacturer,
                    category=entry.category,
                    correction=bands,
                    notes=entry.notes,
                    is_measured=entry.is_measured,
                    source=entry.source,
                )
            )
    except EqualizerError as error:
        raise InvalidReferenceDataError(f"bundled headphone catalog is invalid: {error}") from error
    return tuple(headphones)


def _load_frequency_bands() -> tuple[FrequencyBand, ...]:
    raw = _read_bundled_yaml(_FREQUENCY_BANDS_FILE)
    try:
        document = _FrequencyBandsFile.model_validate(raw)
        bands = tuple(
            FrequencyBand(band.name, band.low_hz, band.high_hz, band.description)
            for band in document.bands
        )
    except EqualizerError as error:
        raise InvalidReferenceDataError(
            f"bundled frequency band reference is invalid: {error}"
        ) from error
    return bands


class YamlReferenceCatalog:
    """The real ``ReferenceCatalog``, backed by this package's YAML files.

    Parsed once per process via ``@lru_cache`` on the module-level
    loaders below: this is read-only reference data bundled with the
    app, so there is nothing to invalidate the cache for, and re-parsing
    two small YAML files on every UI interaction would be pointless work.
    """

    def list_headphones(self) -> list[HeadphoneModel]:
        return list(_cached_headphones())

    def get_headphone(self, headphone_id: str) -> HeadphoneModel | None:
        for headphone in _cached_headphones():
            if headphone.id == headphone_id:
                return headphone
        return None

    def list_frequency_bands(self) -> list[FrequencyBand]:
        return list(_cached_frequency_bands())

    def describe_frequency(self, frequency_hz: float) -> FrequencyBand | None:
        for band in _cached_frequency_bands():
            if band.contains(frequency_hz):
                return band
        return None


@lru_cache(maxsize=1)
def _cached_headphones() -> tuple[HeadphoneModel, ...]:
    return _load_headphones()


@lru_cache(maxsize=1)
def _cached_frequency_bands() -> tuple[FrequencyBand, ...]:
    return _load_frequency_bands()
