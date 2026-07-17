"""Tests for YamlReferenceCatalog — against the real bundled data files.

Unlike the repository tests elsewhere in this suite (which build a
throwaway SQLite database), there's nothing to fabricate here: the data
*is* the two YAML files this app actually ships. These tests are as much
about data integrity as code correctness — the same role
``test_importers.py``'s real-Peace-collection tests play for M6. A typo
in ``headphones.yaml`` should fail a test, not surface as a crash the
first time a user opens the headphone picker.
"""

from __future__ import annotations

from itertools import pairwise

from trxmp.domain.reference import HeadphoneCategory
from trxmp.dsp.biquad import FilterType
from trxmp.infrastructure.reference_data.catalog import YamlReferenceCatalog


class TestHeadphoneCatalog:
    def test_the_bundled_file_loads_and_is_not_empty(self) -> None:
        headphones = YamlReferenceCatalog().list_headphones()
        assert len(headphones) >= 5  # the five ported from the original app

    def test_every_bundled_headphone_has_a_unique_id(self) -> None:
        ids = [h.id for h in YamlReferenceCatalog().list_headphones()]
        assert len(ids) == len(set(ids))

    def test_every_correction_band_is_valid_at_a_real_sample_rate(self) -> None:
        """Every band already passed EqBand's own guardrails just by
        being constructed (catalog.py would have raised otherwise) —
        this additionally checks the Nyquist-dependent rule, which can
        only be checked against a real sample rate."""
        for headphone in YamlReferenceCatalog().list_headphones():
            for band in headphone.correction:
                band.validate_for_sample_rate(48_000.0)

    def test_get_headphone_finds_a_known_entry(self) -> None:
        headphone = YamlReferenceCatalog().get_headphone("hifiman_sundara")
        assert headphone is not None
        assert headphone.name == "HiFiMan Sundara"
        assert headphone.category is HeadphoneCategory.PLANAR
        assert len(headphone.correction) == 1
        assert headphone.correction[0].filter_type is FilterType.PEAKING
        assert headphone.correction[0].frequency_hz == 4_500.0

    def test_get_headphone_returns_none_for_an_unknown_id(self) -> None:
        assert YamlReferenceCatalog().get_headphone("does-not-exist") is None

    def test_none_of_the_ported_curves_are_silently_claimed_as_measured(self) -> None:
        """These are approximations ported from the original prototype,
        not lab measurements Trxmp has taken — the catalog must not
        overstate its own authority."""
        for headphone in YamlReferenceCatalog().list_headphones():
            assert headphone.is_measured is False
            assert headphone.source  # every entry names where it came from

    def test_repeated_calls_return_equal_data_the_cache_is_transparent(self) -> None:
        first = YamlReferenceCatalog().list_headphones()
        second = YamlReferenceCatalog().list_headphones()
        assert first == second


class TestFrequencyBandCatalog:
    def test_the_bundled_bands_cover_the_full_audible_range_with_no_gaps(self) -> None:
        """Adjacent bands must share an edge exactly — a gap would mean
        some frequency describe_frequency() can never place, and an
        overlap would mean two bands both claim it."""
        bands = sorted(YamlReferenceCatalog().list_frequency_bands(), key=lambda b: b.low_hz)
        assert bands[0].low_hz <= 20.0
        assert bands[-1].high_hz >= 20_000.0
        for earlier, later in pairwise(bands):
            assert earlier.high_hz == later.low_hz

    def test_describe_frequency_finds_the_right_band(self) -> None:
        catalog = YamlReferenceCatalog()
        sub_bass = catalog.describe_frequency(40.0)
        assert sub_bass is not None
        assert sub_bass.name == "Sub-bass"

        presence = catalog.describe_frequency(5_000.0)
        assert presence is not None
        assert presence.name == "Presence"

    def test_describe_frequency_returns_none_outside_the_covered_range(self) -> None:
        assert YamlReferenceCatalog().describe_frequency(200_000.0) is None
