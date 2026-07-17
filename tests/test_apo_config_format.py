"""Equalizer APO config rendering — pure text, tested to the decimal.

APO silently ignores lines it can't parse. That means a formatting
mistake here doesn't raise anything: it just quietly drops a filter and
the user hears the wrong EQ forever. These tests are the only thing
standing between a typo and a silent failure.
"""

from __future__ import annotations

from trxmp.domain.equalizer import EqBand, EqPreset
from trxmp.dsp.biquad import FilterType
from trxmp.infrastructure.equalizer_apo.config_format import (
    render_bypass_config,
    render_config,
)

SAMPLE_RATE = 48_000.0


def _lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip() and not line.startswith("#")]


def test_flat_preset_renders_only_a_preamp() -> None:
    assert _lines(render_config(EqPreset.flat(), SAMPLE_RATE)) == ["Preamp: -0.50 dB"]


def test_peaking_band_matches_apo_syntax_exactly() -> None:
    preset = EqPreset(bands=(EqBand(FilterType.PEAKING, 1_000.0, -3.0, 1.5),))
    assert _lines(render_config(preset, SAMPLE_RATE))[1] == (
        "Filter 1: ON PK Fc 1000.00 Hz Gain -3.00 dB Q 1.5000"
    )


def test_shelves_use_the_q_parameterised_variants() -> None:
    """LSC/HSC, not LS/HS: the plain variants have no Q parameter, so a
    band's Q would be silently dropped and the sound would stop matching
    the curve on screen."""
    preset = EqPreset(
        bands=(
            EqBand(FilterType.LOW_SHELF, 60.0, 4.0, 0.7),
            EqBand(FilterType.HIGH_SHELF, 10_000.0, 1.5, 0.71),
        )
    )
    lines = _lines(render_config(preset, SAMPLE_RATE))
    assert lines[1] == "Filter 1: ON LSC Fc 60.00 Hz Gain 4.00 dB Q 0.7000"
    assert lines[2] == "Filter 2: ON HSC Fc 10000.00 Hz Gain 1.50 dB Q 0.7100"


def test_pass_filters_carry_q_but_no_gain() -> None:
    preset = EqPreset(
        bands=(
            EqBand(FilterType.LOW_PASS, 8_000.0, 0.0, 0.707),
            EqBand(FilterType.HIGH_PASS, 30.0, 0.0, 0.5),
        )
    )
    lines = _lines(render_config(preset, SAMPLE_RATE))
    assert lines[1] == "Filter 1: ON LPQ Fc 8000.00 Hz Q 0.7070"
    assert lines[2] == "Filter 2: ON HPQ Fc 30.00 Hz Q 0.5000"
    assert "Gain" not in lines[1]


def test_preamp_is_the_computed_safe_value_not_the_requested_one() -> None:
    """The headline of this whole project reaching system audio: ask for
    0 dB preamp with a +6 dB boost and Trxmp writes -6.5 dB anyway, so
    the driver never clips."""
    preset = EqPreset(
        bands=(EqBand(FilterType.PEAKING, 1_000.0, 6.0, 1.0),), requested_preamp_db=0.0
    )
    assert _lines(render_config(preset, SAMPLE_RATE))[0] == "Preamp: -6.50 dB"


def test_numbers_use_a_decimal_point_never_a_comma() -> None:
    """APO's native syntax is period-separated. A comma (from a locale
    slip) would be parsed as a different number entirely — or the line
    dropped — with no error anywhere."""
    preset = EqPreset(bands=(EqBand(FilterType.PEAKING, 1_234.5, -2.25, 1.41),))
    assert "," not in render_config(preset, SAMPLE_RATE)


def test_every_band_gets_a_line_in_order() -> None:
    preset = EqPreset(
        bands=(
            EqBand(FilterType.PEAKING, 100.0, 1.0, 1.0),
            EqBand(FilterType.PEAKING, 200.0, 2.0, 1.0),
            EqBand(FilterType.PEAKING, 300.0, 3.0, 1.0),
        )
    )
    filters = [line for line in _lines(render_config(preset, SAMPLE_RATE)) if "Filter" in line]
    assert len(filters) == 3
    assert filters[0].startswith("Filter 1:")
    assert "Fc 300.00 Hz" in filters[2]


def test_config_is_commented_as_generated() -> None:
    text = render_config(EqPreset.flat(), SAMPLE_RATE)
    assert text.startswith("#")
    assert "Trxmp" in text
    assert text.endswith("\n")  # APO parses line by line; no truncated tail


def test_bypass_config_has_no_filters_and_a_zero_preamp() -> None:
    assert _lines(render_bypass_config()) == ["Preamp: 0.00 dB"]
