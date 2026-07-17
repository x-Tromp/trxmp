"""Parsing Peace's ``.peace`` files (an INI dialect).

Peace is the other popular Equalizer APO front-end, and its presets look
like this::

    [Frequencies]
    Frequency1=35
    [Gains]
    Gain1=0.2
    [Qualities]
    Quality1=1.56
    [Filters]
    Filter4=14
    [General]
    PreAmp=-5.6
    Description=Sundara Headphones

Three things this format does that our domain doesn't, all of which are
handled explicitly rather than ignored:

**Per-channel EQ.** ``[Gains1]``, ``[Gains2]``… hold left/right/surround
curves. Trxmp is stereo-symmetric, so we import the all-channels curve
and warn if any per-channel gains are actually set. (Peace writes empty
``[Frequencies1..8]`` scaffolding into almost every file even when
unused, so warning on the *frequency* sections would cry wolf on nearly
every import — only non-zero gains count.)

**An extra bass boost.** ``Bass Gain``/``Bass Frequency`` is a Peace
feature layered on top of the bands. We can't represent it; if it's set,
the user is told their import is missing it.

**Filter type codes.** ``Filter4=14`` means band 4 isn't a peak. The
mapping below is *inferred from evidence, not documented* — see the note
on ``_FILTER_CODES``. Codes we haven't identified are refused rather
than guessed, because a mis-guessed filter type is wrong audio with no
error attached.
"""

from __future__ import annotations

import configparser
from collections.abc import Mapping
from io import StringIO

from trxmp.domain.equalizer import EqBand, EqPreset
from trxmp.domain.errors import EqualizerError, PresetImportError
from trxmp.dsp.biquad import FilterType

# Peace writes a numeric type code per band, and only for bands that
# aren't plain peaks (an absent entry means peaking).
#
# These two are INFERRED, not documented. Across 40 real .peace files
# from a Peace user's collection, code 14 appeared 12 times and always on
# a low band (105-250 Hz), code 15 appeared 12 times and always on a high
# one (4-16 kHz) — exactly the pattern of a low and a high shelf, and
# consistent with the shelf pair being adjacent in Peace's own list. No
# other code occurred anywhere in that collection.
#
# The confidence is good but it is not certainty, which is why any other
# code raises instead of falling back to "probably a peak".
_FILTER_CODES = {
    14: FilterType.LOW_SHELF,
    15: FilterType.HIGH_SHELF,
}

_MAX_CHANNEL_SECTIONS = 8


def parse_peace_config(text: str) -> tuple[EqPreset, str, tuple[str, ...]]:
    """Parse a .peace file into ``(preset, description, warnings)``."""
    parser = configparser.ConfigParser(strict=False)
    # strict=False above and this try/except below are both about the same
    # thing: these files are written by another program across many
    # versions, and a duplicate key is not our problem to die on.
    try:
        parser.read_file(StringIO(text))
    except configparser.Error as error:
        raise PresetImportError(f"this is not a readable .peace file: {error}") from error

    if not parser.has_section("Frequencies"):
        raise PresetImportError("no [Frequencies] section — is this a .peace preset?")

    warnings: list[str] = []
    bands = _parse_bands(parser)
    if not bands:
        raise PresetImportError("the file defines no equalizer bands")

    _warn_about_unrepresentable_features(parser, warnings)

    general = parser["General"] if parser.has_section("General") else {}
    description = general.get("description", "").strip()
    preamp_db = _parse_preamp(general, warnings)

    try:
        preset = EqPreset(bands=tuple(bands), requested_preamp_db=preamp_db)
    except EqualizerError as error:
        raise PresetImportError(f"the file is not a valid equalizer preset: {error}") from error
    return preset, description, tuple(warnings)


def _parse_bands(parser: configparser.ConfigParser) -> list[EqBand]:
    frequencies = parser["Frequencies"]
    gains = parser["Gains"] if parser.has_section("Gains") else {}
    qualities = parser["Qualities"] if parser.has_section("Qualities") else {}
    filters = parser["Filters"] if parser.has_section("Filters") else {}

    bands: list[EqBand] = []
    for index in _band_indices(frequencies):
        # A band with no Gain entry is a real and common case: Peace omits
        # the key entirely at 0 dB, and 14 of the 40 files surveyed had no
        # [Gains] section at all (flat templates).
        gain_db = _to_float(gains.get(f"Gain{index}"), default=0.0, label=f"Gain{index}")
        q = _to_float(qualities.get(f"Quality{index}"), default=1.0, label=f"Quality{index}")
        frequency_hz = _to_float(
            frequencies.get(f"Frequency{index}"), default=None, label=f"Frequency{index}"
        )
        try:
            bands.append(
                EqBand(
                    filter_type=_filter_type(filters, index),
                    frequency_hz=frequency_hz,
                    gain_db=gain_db,
                    q=q,
                )
            )
        except EqualizerError as error:
            raise PresetImportError(f"band {index}: {error}") from error
    return bands


def _band_indices(frequencies: configparser.SectionProxy) -> list[int]:
    indices = []
    for key in frequencies:
        if key.lower().startswith("frequency"):
            suffix = key[len("frequency") :]
            if suffix.isdigit():
                indices.append(int(suffix))
    return sorted(indices)


def _filter_type(filters: Mapping[str, str], index: int) -> FilterType:
    raw = filters.get(f"Filter{index}")
    if raw is None:
        return FilterType.PEAKING  # Peace's default; the key is only written for others
    try:
        code = int(raw)
    except ValueError:
        raise PresetImportError(f"band {index}: unreadable filter type {raw!r}") from None
    if code not in _FILTER_CODES:
        raise PresetImportError(
            f"band {index}: Peace filter type {code} is one Trxmp hasn't identified. "
            "Importing it as a peak could silently change how this preset sounds, "
            "so the import stopped instead."
        )
    return _FILTER_CODES[code]


def _parse_preamp(general: Mapping[str, str], warnings: list[str]) -> float:
    preamp_db = _to_float(general.get("preamp"), default=0.0, label="PreAmp")
    if preamp_db > 0.0:
        warnings.append(
            f"the file asks for a +{preamp_db:.1f} dB preamp; Trxmp caps preamp at 0 dB "
            "and computes safe headroom from the bands instead"
        )
        return 0.0
    return max(preamp_db, -24.0)


def _warn_about_unrepresentable_features(
    parser: configparser.ConfigParser, warnings: list[str]
) -> None:
    channels = [
        section
        for index in range(1, _MAX_CHANNEL_SECTIONS + 1)
        if (section := f"Gains{index}") in parser and _has_any_gain(parser[section])
    ]
    if channels:
        warnings.append(
            "this preset has per-channel equalization "
            f"({', '.join(channels)}); Trxmp applies one curve to both channels, "
            "so only the all-channels curve was imported"
        )

    if parser.has_section("General"):
        bass_gain = _to_float(parser["General"].get("bass gain"), default=0.0, label="Bass Gain")
        if bass_gain:
            warnings.append(
                f"Peace's extra bass boost (Bass Gain {bass_gain:g}) is not a Trxmp "
                "feature and was not imported"
            )
        if parser["General"].get("graphiceq"):
            warnings.append(
                "this preset uses Peace's GraphicEQ mode; only its parametric bands were imported"
            )

    if parser.has_section("Disabled"):
        warnings.append("this preset has disabled bands; Trxmp imported every band as enabled")


def _has_any_gain(section: configparser.SectionProxy) -> bool:
    return any(_to_float(value, default=0.0, label=key) for key, value in section.items())


def _to_float(raw: str | None, default: float | None, label: str) -> float:
    if raw is None or not raw.strip():
        if default is None:
            raise PresetImportError(f"{label} is missing")
        return default
    try:
        return float(raw)
    except ValueError:
        raise PresetImportError(f"{label} is not a number: {raw!r}") from None
