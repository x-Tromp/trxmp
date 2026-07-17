"""Parsing Equalizer APO config text — the inverse of ``config_format``.

This is the single most valuable importer in the app, because it isn't
really "Equalizer APO's format": it's what AutoEQ publishes as
``ParametricEQ.txt`` for every headphone in its database. One parser,
thousands of measured correction curves::

    Preamp: -6.8 dB
    Filter 1: ON PK Fc 105 Hz Gain 1.0 dB Q 0.70
    Filter 2: ON LSC Fc 105 Hz Gain 1.0 dB Q 0.70

Line-oriented and regex-based rather than a grammar, deliberately:
APO's own parser ignores anything it doesn't recognise, which is exactly
how ``#`` comments work in a format with no comment syntax. We follow
that for *decoration* (headers, blank lines, ``OFF`` placeholders) but
not for *content* — a filter line we half-understand is refused, never
skipped, because a silently dropped filter is a curve that lies.
"""

from __future__ import annotations

import re

from trxmp.domain.equalizer import EqBand, EqPreset
from trxmp.domain.errors import EqualizerError, PresetImportError
from trxmp.dsp.biquad import FilterType

# Butterworth / RBJ "S=1" default: the Q an APO filter type implies when
# it carries no Q of its own.
_DEFAULT_Q = 0.7071

_PREAMP = re.compile(r"^\s*Preamp\s*:\s*(?P<db>[-+]?[\d.]+)\s*dB", re.IGNORECASE)
# The filter number is cosmetic ("not interpreted and can be omitted",
# per APO's reference), so it's optional here too.
_FILTER = re.compile(
    r"^\s*Filter\s*\d*\s*:\s*(?P<state>ON|OFF)\s+(?P<type>[A-Za-z]+)(?P<rest>.*)$",
    re.IGNORECASE,
)
_FC = re.compile(r"Fc\s+(?P<hz>[\d.]+)\s*Hz", re.IGNORECASE)
_GAIN = re.compile(r"Gain\s+(?P<db>[-+]?[\d.]+)\s*dB", re.IGNORECASE)
_Q = re.compile(r"\bQ\s+(?P<q>[\d.]+)", re.IGNORECASE)
_BANDWIDTH = re.compile(r"\bBW\s+Oct\s+[\d.]+", re.IGNORECASE)

_TYPES = {
    "PK": FilterType.PEAKING,
    "PEQ": FilterType.PEAKING,
    "LSC": FilterType.LOW_SHELF,
    "HSC": FilterType.HIGH_SHELF,
    "LPQ": FilterType.LOW_PASS,
    "HPQ": FilterType.HIGH_PASS,
    "LP": FilterType.LOW_PASS,
    "HP": FilterType.HIGH_PASS,
    "LS": FilterType.LOW_SHELF,
    "HS": FilterType.HIGH_SHELF,
}

# Real filter types with no equivalent in our five-shape domain. Importing
# one as something else would change the sound, so we stop.
_UNREPRESENTABLE = {
    "NO": "notch",
    "AP": "all-pass",
    "BP": "band-pass",
    "MODAL": "modal",
}

# Types whose Q we infer rather than read.
_SLOPE_SHELVES = {"LS", "HS"}


def parse_apo_config(text: str) -> tuple[EqPreset, tuple[str, ...]]:
    """Parse APO/AutoEQ config text into a preset plus any warnings."""
    preamp_db = 0.0
    bands: list[EqBand] = []
    warnings: list[str] = []

    for number, line in enumerate(text.splitlines(), start=1):
        preamp_match = _PREAMP.match(line)
        if preamp_match:
            preamp_db = float(preamp_match.group("db"))
            continue

        filter_match = _FILTER.match(line)
        if filter_match is None:
            continue  # headers, comments, blank lines — APO ignores these too
        if filter_match.group("state").upper() == "OFF":
            continue  # a disabled slot, not a filter

        band = _parse_filter(filter_match, number, line, warnings)
        if band is not None:
            bands.append(band)

    if not bands and preamp_db == 0.0:
        raise PresetImportError(
            "no Equalizer APO filters found — is this an APO or AutoEQ ParametricEQ file?"
        )

    # APO allows a positive preamp; our domain does not (gain staging is
    # for safety, never for loudness). Clamping and saying so beats
    # refusing an otherwise perfectly good AutoEQ file.
    if preamp_db > 0.0:
        warnings.append(
            f"the file asks for a +{preamp_db:.1f} dB preamp; Trxmp caps preamp at 0 dB "
            "and computes safe headroom from the bands instead"
        )
        preamp_db = 0.0

    try:
        return EqPreset(bands=tuple(bands), requested_preamp_db=preamp_db), tuple(warnings)
    except EqualizerError as error:
        raise PresetImportError(f"the file is not a valid equalizer preset: {error}") from error


def _parse_filter(
    match: re.Match[str], number: int, line: str, warnings: list[str]
) -> EqBand | None:
    filter_name = match.group("type").upper()
    rest = match.group("rest")

    if filter_name == "NONE":
        return None  # an empty slot; REW-style files are full of them
    if filter_name in _UNREPRESENTABLE:
        raise PresetImportError(
            f"line {number}: Trxmp cannot represent a {_UNREPRESENTABLE[filter_name]} "
            f"filter ({filter_name}), and importing it as anything else would change "
            f"how this preset sounds:\n  {line.strip()}"
        )
    if filter_name not in _TYPES:
        raise PresetImportError(
            f"line {number}: unknown filter type {filter_name!r}:\n  {line.strip()}"
        )
    if _BANDWIDTH.search(rest):
        raise PresetImportError(
            f"line {number}: bandwidth (BW Oct) is not supported — the octave-to-Q "
            f"conversion is frequency-dependent and Trxmp will not guess. Re-export "
            f"with Q values instead:\n  {line.strip()}"
        )

    frequency = _FC.search(rest)
    if frequency is None:
        raise PresetImportError(f"line {number}: filter has no centre frequency:\n  {line.strip()}")

    gain_match = _GAIN.search(rest)
    q_match = _Q.search(rest)

    if filter_name in _SLOPE_SHELVES and q_match is None:
        warnings.append(
            f"line {number}: {filter_name} is a slope-defined shelf with no Q; "
            f"imported as a Q={_DEFAULT_Q} shelf, which may differ slightly"
        )

    try:
        return EqBand(
            filter_type=_TYPES[filter_name],
            frequency_hz=float(frequency.group("hz")),
            gain_db=float(gain_match.group("db")) if gain_match else 0.0,
            q=float(q_match.group("q")) if q_match else _DEFAULT_Q,
        )
    except EqualizerError as error:
        raise PresetImportError(f"line {number}: {error}\n  {line.strip()}") from error
