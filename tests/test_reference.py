"""Domain model tests for the knowledge base — FrequencyBand and
HeadphoneModel, independent of where their data actually comes from.
"""

from __future__ import annotations

import pytest

from trxmp.domain.equalizer import EqBand
from trxmp.domain.errors import InvalidReferenceDataError
from trxmp.domain.reference import FrequencyBand, HeadphoneCategory, HeadphoneModel
from trxmp.dsp.biquad import FilterType


class TestFrequencyBand:
    def test_contains_is_inclusive_low_exclusive_high(self) -> None:
        """Half-open intervals are what let a whole set of bands
        partition the spectrum without gaps or double-coverage at the
        boundary between two adjacent bands."""
        band = FrequencyBand("Bass", 60.0, 250.0, "warmth")
        assert band.contains(60.0)
        assert band.contains(249.9)
        assert not band.contains(250.0)  # belongs to the next band up
        assert not band.contains(59.9)

    def test_rejects_empty_name(self) -> None:
        with pytest.raises(InvalidReferenceDataError, match="name"):
            FrequencyBand("  ", 60.0, 250.0, "warmth")

    def test_rejects_a_backwards_or_zero_width_range(self) -> None:
        with pytest.raises(InvalidReferenceDataError, match="range"):
            FrequencyBand("Bad", 250.0, 60.0, "warmth")
        with pytest.raises(InvalidReferenceDataError, match="range"):
            FrequencyBand("Bad", 100.0, 100.0, "warmth")

    def test_rejects_a_non_positive_low_edge(self) -> None:
        with pytest.raises(InvalidReferenceDataError, match="range"):
            FrequencyBand("Bad", 0.0, 100.0, "warmth")


class TestHeadphoneModel:
    def _band(self) -> tuple[EqBand, ...]:
        return (EqBand(FilterType.PEAKING, 4_500.0, -3.0, 2.5),)

    def test_a_reasonable_headphone_is_accepted(self) -> None:
        headphone = HeadphoneModel(
            id="test_hp",
            name="Test Headphone",
            manufacturer="Test Co",
            category=HeadphoneCategory.PLANAR,
            correction=self._band(),
        )
        assert headphone.category is HeadphoneCategory.PLANAR
        assert len(headphone.correction) == 1

    def test_correction_bands_are_real_eqbands_not_a_parallel_type(self) -> None:
        """The whole point of reusing EqBand: a correction curve is
        exactly as valid — and exactly as safe — as any preset a user
        builds by hand, because it's literally made of the same object."""
        headphone = HeadphoneModel(
            id="x",
            name="X",
            manufacturer="Y",
            category=HeadphoneCategory.DYNAMIC,
            correction=self._band(),
        )
        assert isinstance(headphone.correction[0], EqBand)

    def test_rejects_empty_id_or_name(self) -> None:
        with pytest.raises(InvalidReferenceDataError):
            HeadphoneModel(
                id="",
                name="X",
                manufacturer="Y",
                category=HeadphoneCategory.DYNAMIC,
                correction=(),
            )
        with pytest.raises(InvalidReferenceDataError):
            HeadphoneModel(
                id="x",
                name="  ",
                manufacturer="Y",
                category=HeadphoneCategory.DYNAMIC,
                correction=(),
            )

    def test_a_headphone_may_have_no_correction_at_all(self) -> None:
        """A flat/reference headphone with nothing to correct is a
        legitimate catalog entry, not a malformed one."""
        headphone = HeadphoneModel(
            id="flat",
            name="Flat Reference",
            manufacturer="N/A",
            category=HeadphoneCategory.DYNAMIC,
            correction=(),
        )
        assert headphone.correction == ()
