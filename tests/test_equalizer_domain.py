"""Domain guardrail and headroom tests, mirroring the Rust engine's."""

import pytest

from trxmp.domain.equalizer import (
    HEADROOM_SAFETY_MARGIN_DB,
    MAX_BANDS,
    EqBand,
    EqPreset,
)
from trxmp.domain.errors import InvalidBandError, InvalidPresetError
from trxmp.dsp.biquad import FilterType

SAMPLE_RATE = 48_000.0


class TestBandGuardrails:
    def test_rejects_boost_beyond_ceiling(self) -> None:
        with pytest.raises(InvalidBandError, match="gain"):
            EqBand(FilterType.PEAKING, 1_000.0, gain_db=15.0, q=1.0)

    def test_accepts_the_values_real_presets_actually_use(self) -> None:
        """Regression for M6. All three of these were rejected until a
        real Peace collection proved the limits were taste, not
        engineering: Peace writes 10 Hz bands and Q=0.01 tilts routinely,
        and bass-boost presets reach +10 dB."""
        EqBand(FilterType.LOW_SHELF, 10.0, gain_db=6.0, q=0.7)
        EqBand(FilterType.PEAKING, 1_000.0, gain_db=1.0, q=0.01)
        EqBand(FilterType.LOW_SHELF, 60.0, gain_db=10.0, q=0.7)

    def test_rejects_extreme_q(self) -> None:
        with pytest.raises(InvalidBandError, match="Q"):
            EqBand(FilterType.PEAKING, 1_000.0, gain_db=3.0, q=50.0)

    def test_rejects_frequency_outside_audible_range(self) -> None:
        with pytest.raises(InvalidBandError, match="frequency"):
            EqBand(FilterType.PEAKING, 23_000.0, gain_db=3.0, q=1.0)

    def test_rejects_non_finite_values(self) -> None:
        with pytest.raises(InvalidBandError):
            EqBand(FilterType.PEAKING, float("nan"), gain_db=3.0, q=1.0)

    def test_rejects_frequency_near_nyquist_for_low_sample_rates(self) -> None:
        """19 kHz is a legal band — but not at a 32 kHz sample rate,
        where Nyquist is 16 kHz. Context-dependent validation has to be
        a separate step from construction."""
        band = EqBand(FilterType.PEAKING, 19_000.0, gain_db=3.0, q=1.0)
        band.validate_for_sample_rate(48_000.0)  # fine
        with pytest.raises(InvalidBandError, match="Nyquist"):
            band.validate_for_sample_rate(32_000.0)

    def test_accepts_reasonable_band(self) -> None:
        band = EqBand(FilterType.PEAKING, 1_000.0, gain_db=4.0, q=0.7)
        band.validate_for_sample_rate(SAMPLE_RATE)


class TestPresetHeadroom:
    def test_flat_preset_needs_almost_no_headroom(self) -> None:
        preamp = EqPreset.flat().safe_preamp_db(SAMPLE_RATE)
        assert preamp == pytest.approx(-HEADROOM_SAFETY_MARGIN_DB, abs=0.01)

    def test_single_boosted_band_demands_matching_attenuation(self) -> None:
        preset = EqPreset(bands=(EqBand(FilterType.PEAKING, 1_000.0, 6.0, 1.0),))
        peak = preset.peak_response_db(SAMPLE_RATE)
        assert peak == pytest.approx(6.0, abs=0.1)
        # Net gain at the worst frequency must end at or below the margin.
        assert peak + preset.safe_preamp_db(SAMPLE_RATE) <= -HEADROOM_SAFETY_MARGIN_DB + 0.05

    def test_overlapping_boosts_compound_and_still_get_full_correction(self) -> None:
        """Two bells close in frequency overlap: the safe preamp must
        account for the *combined* peak, not the larger individual one."""
        preset = EqPreset(
            bands=(
                EqBand(FilterType.PEAKING, 900.0, 5.0, 1.0),
                EqBand(FilterType.PEAKING, 1_100.0, 5.0, 1.0),
            )
        )
        peak = preset.peak_response_db(SAMPLE_RATE)
        assert peak > 5.0, f"overlapping boosts should compound, got {peak}"
        assert peak + preset.safe_preamp_db(SAMPLE_RATE) <= -HEADROOM_SAFETY_MARGIN_DB + 0.05

    def test_cuts_require_no_extra_headroom(self) -> None:
        preset = EqPreset(bands=(EqBand(FilterType.PEAKING, 300.0, -6.0, 1.0),))
        assert preset.safe_preamp_db(SAMPLE_RATE) == pytest.approx(
            -HEADROOM_SAFETY_MARGIN_DB, abs=0.05
        )

    def test_a_low_shelf_is_measured_at_its_plateau_not_its_corner(self) -> None:
        """Regression for a real clipping bug M6 uncovered.

        A low shelf has only *half* its boost at its corner frequency and
        the full amount below it. The scan used to start at the lowest
        legal band frequency, so a +12 dB shelf at 10 Hz measured as +6
        and the preamp came out 6 dB too high — subsonic content nobody
        can hear would have clipped anyway.
        """
        preset = EqPreset(bands=(EqBand(FilterType.LOW_SHELF, 10.0, 12.0, 0.7),))
        assert preset.peak_response_db(SAMPLE_RATE) == pytest.approx(12.0, abs=0.1)
        assert preset.safe_preamp_db(SAMPLE_RATE) == pytest.approx(-12.5, abs=0.1)

    def test_a_high_shelf_is_measured_above_the_audible_range_too(self) -> None:
        """The same bug at the other end: a shelf at 20 kHz reaches its
        full boost above it, and every sample up to Nyquist can overflow
        whether or not anyone can hear it."""
        preset = EqPreset(bands=(EqBand(FilterType.HIGH_SHELF, 20_000.0, 12.0, 0.7),))
        assert preset.peak_response_db(SAMPLE_RATE) == pytest.approx(12.0, abs=0.5)


class TestPresetGuardrails:
    def test_rejects_too_many_bands(self) -> None:
        bands = tuple(
            EqBand(FilterType.PEAKING, 100.0 + i * 50.0, 1.0, 1.0) for i in range(MAX_BANDS + 1)
        )
        with pytest.raises(InvalidPresetError, match="bands"):
            EqPreset(bands=bands)

    def test_rejects_positive_preamp(self) -> None:
        with pytest.raises(InvalidPresetError, match="preamp"):
            EqPreset.flat(requested_preamp_db=3.0)
