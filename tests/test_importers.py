"""Importer tests, built on real files rather than invented ones.

The APO samples are AutoEQ's published shape; the .peace samples are
trimmed copies of files from an actual Peace collection, including the
awkward parts (a missing Gain key, the empty per-channel scaffolding
Peace writes into nearly every file). Inventing tidy fixtures would have
tested a format that doesn't exist.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from trxmp.domain.errors import PresetImportError
from trxmp.dsp.biquad import FilterType
from trxmp.infrastructure.importers import import_preset_file
from trxmp.infrastructure.importers.apo_config import parse_apo_config
from trxmp.infrastructure.importers.peace_config import parse_peace_config

# What AutoEQ publishes for every headphone in its database.
AUTOEQ = """Preamp: -6.8 dB
Filter 1: ON LSC Fc 105 Hz Gain 5.6 dB Q 0.70
Filter 2: ON PK Fc 42 Hz Gain -1.9 dB Q 0.92
Filter 3: ON PK Fc 4500 Hz Gain -3.4 dB Q 2.51
Filter 4: ON HSC Fc 10000 Hz Gain 1.2 dB Q 0.70
"""

# Trimmed from the user's real HIFIMAN Sundara.peace.
SUNDARA_PEACE = """[Frequencies]
Frequency1=35
Frequency2=56
Frequency3=105
Frequency4=10000
[Gains]
Gain1=0.2
Gain2=-4.5
Gain3=8.9
Gain4=-3.1
[Qualities]
Quality1=1.56
Quality2=0.4
Quality3=0.7
Quality4=0.7
[Filters]
Filter3=14
Filter4=15
[General]
Description=Sundara Headphones
PreAmp=-5.6
"""


class TestApoConfig:
    def test_parses_an_autoeq_export(self) -> None:
        preset, warnings = parse_apo_config(AUTOEQ)
        assert warnings == ()
        assert preset.requested_preamp_db == -6.8
        assert len(preset.bands) == 4

        low_shelf = preset.bands[0]
        assert low_shelf.filter_type is FilterType.LOW_SHELF
        assert low_shelf.frequency_hz == 105.0
        assert low_shelf.gain_db == 5.6
        assert low_shelf.q == 0.70

    def test_roundtrips_with_our_own_renderer(self) -> None:
        """The strongest test available: render a preset to APO syntax
        with M4's writer, read it back with M6's parser, and require the
        same preset. Writer and parser can't drift apart without this
        failing."""
        from trxmp.domain.equalizer import EqBand, EqPreset
        from trxmp.infrastructure.equalizer_apo.config_format import render_config

        original = EqPreset(
            bands=(
                EqBand(FilterType.LOW_SHELF, 60.0, 4.0, 0.7),
                EqBand(FilterType.PEAKING, 1_000.0, -3.0, 1.5),
                EqBand(FilterType.HIGH_SHELF, 10_000.0, 1.5, 0.71),
                EqBand(FilterType.LOW_PASS, 18_000.0, 0.0, 0.707),
                EqBand(FilterType.HIGH_PASS, 25.0, 0.0, 0.5),
            ),
            requested_preamp_db=-2.0,
        )
        reparsed, _ = parse_apo_config(render_config(original, 48_000.0))
        assert reparsed.bands == original.bands
        # The rendered preamp is the *safe* one, not the requested one.
        assert reparsed.requested_preamp_db == pytest.approx(
            original.safe_preamp_db(48_000.0), abs=0.01
        )

    def test_filter_numbers_are_optional(self) -> None:
        preset, _ = parse_apo_config("Filter: ON PK Fc 1000 Hz Gain 3 dB Q 1\n")
        assert len(preset.bands) == 1

    def test_off_filters_and_empty_slots_are_skipped(self) -> None:
        preset, _ = parse_apo_config(
            "Filter 1: ON PK Fc 1000 Hz Gain 3 dB Q 1\n"
            "Filter 2: OFF PK Fc 2000 Hz Gain 9 dB Q 1\n"
            "Filter 3: ON None\n"
        )
        assert len(preset.bands) == 1

    def test_comments_and_junk_are_ignored(self) -> None:
        preset, _ = parse_apo_config(
            "# a comment\n"
            "Room EQ V5.01\n"
            "\n"
            "Device: Speakers\n"
            "Filter 1: ON PK Fc 1000 Hz Gain 3 dB Q 1\n"
        )
        assert len(preset.bands) == 1

    def test_pass_filters_without_q_get_the_butterworth_default(self) -> None:
        preset, _ = parse_apo_config("Filter 1: ON LP Fc 8000 Hz\n")
        assert preset.bands[0].filter_type is FilterType.LOW_PASS
        assert preset.bands[0].q == 0.7071

    def test_slope_shelves_are_approximated_with_a_warning(self) -> None:
        """LS has no Q; we substitute one. That's a real approximation
        and the user is told, rather than it being hidden."""
        preset, warnings = parse_apo_config("Filter 1: ON LS Fc 300 Hz Gain 5 dB\n")
        assert preset.bands[0].filter_type is FilterType.LOW_SHELF
        assert any("slope-defined shelf" in w for w in warnings)

    def test_unrepresentable_filters_are_refused_not_dropped(self) -> None:
        """A silently dropped notch is an untamed resonance the user will
        hear and blame on us."""
        with pytest.raises(PresetImportError, match="notch"):
            parse_apo_config(
                "Filter 1: ON PK Fc 1000 Hz Gain 3 dB Q 1\nFilter 2: ON NO Fc 800 Hz Q 10\n"
            )

    def test_bandwidth_is_refused_rather_than_guessed(self) -> None:
        with pytest.raises(PresetImportError, match="BW Oct"):
            parse_apo_config("Filter 1: ON PK Fc 1000 Hz Gain 3 dB BW Oct 0.5\n")

    def test_positive_preamp_is_clamped_with_a_warning(self) -> None:
        preset, warnings = parse_apo_config(
            "Preamp: 3.0 dB\nFilter 1: ON PK Fc 1000 Hz Gain 3 dB Q 1\n"
        )
        assert preset.requested_preamp_db == 0.0
        assert any("caps preamp at 0 dB" in w for w in warnings)

    def test_out_of_range_gain_is_reported_with_its_line(self) -> None:
        with pytest.raises(PresetImportError, match="line 1"):
            parse_apo_config("Filter 1: ON PK Fc 1000 Hz Gain 30 dB Q 1\n")

    def test_a_file_with_no_filters_is_refused(self) -> None:
        with pytest.raises(PresetImportError, match="no Equalizer APO filters"):
            parse_apo_config("this is a shopping list\nmilk\neggs\n")


class TestPeaceConfig:
    def test_parses_a_real_peace_preset(self) -> None:
        preset, description, warnings = parse_peace_config(SUNDARA_PEACE)
        assert description == "Sundara Headphones"
        assert preset.requested_preamp_db == -5.6
        assert len(preset.bands) == 4
        assert warnings == ()

    def test_filter_codes_map_to_shelves(self) -> None:
        preset, _, _ = parse_peace_config(SUNDARA_PEACE)
        assert preset.bands[0].filter_type is FilterType.PEAKING  # no code = peak
        assert preset.bands[2].filter_type is FilterType.LOW_SHELF  # code 14
        assert preset.bands[3].filter_type is FilterType.HIGH_SHELF  # code 15

    def test_a_missing_gain_key_means_zero(self) -> None:
        """Real behaviour from the user's Adele.peace: Peace omits the
        Gain key entirely at 0 dB rather than writing Gain5=0."""
        preset, _, _ = parse_peace_config(
            "[Frequencies]\nFrequency1=100\nFrequency2=200\n"
            "[Gains]\nGain1=3\n"
            "[Qualities]\nQuality1=1\nQuality2=1\n"
        )
        assert preset.bands[1].gain_db == 0.0

    def test_a_file_with_no_gains_section_is_a_flat_template(self) -> None:
        preset, _, _ = parse_peace_config(
            "[Frequencies]\nFrequency1=100\n[Qualities]\nQuality1=1\n"
        )
        assert preset.bands[0].gain_db == 0.0

    def test_empty_channel_scaffolding_does_not_warn(self) -> None:
        """Peace writes [Frequencies1..8] into nearly every file whether
        used or not. Warning on those would cry wolf on every import."""
        _, _, warnings = parse_peace_config(
            SUNDARA_PEACE + "\n[Frequencies1]\nFrequency1=100\n[Gains1]\nGain1=0\n"
        )
        assert warnings == ()

    def test_real_per_channel_gains_warn(self) -> None:
        _, _, warnings = parse_peace_config(SUNDARA_PEACE + "\n[Gains1]\nGain1=4.5\n")
        assert any("per-channel" in w for w in warnings)

    def test_bass_boost_warns_because_we_cannot_represent_it(self) -> None:
        _, _, warnings = parse_peace_config(
            SUNDARA_PEACE.replace("PreAmp=-5.6", "PreAmp=-5.6\nBass Gain=6\nBass Frequency=500")
        )
        assert any("bass boost" in w for w in warnings)

    def test_unknown_filter_codes_are_refused_not_guessed(self) -> None:
        """The mapping is inferred from evidence, not documentation. A
        code we haven't identified must stop the import rather than
        silently become a peak."""
        with pytest.raises(PresetImportError, match="hasn't identified"):
            parse_peace_config(SUNDARA_PEACE.replace("Filter3=14", "Filter3=7"))

    def test_a_thirteen_band_preset_imports(self) -> None:
        """23 of the user's 40 files have 13 bands — more than the old
        12-band domain limit allowed. This is the test that limit failed."""
        frequencies = "\n".join(f"Frequency{i}={i * 100}" for i in range(1, 14))
        qualities = "\n".join(f"Quality{i}=1" for i in range(1, 14))
        preset, _, _ = parse_peace_config(
            f"[Frequencies]\n{frequencies}\n[Qualities]\n{qualities}\n"
        )
        assert len(preset.bands) == 13

    def test_not_a_peace_file(self) -> None:
        with pytest.raises(PresetImportError, match="Frequencies"):
            parse_peace_config("[Something]\nkey=value\n")


class TestDispatch:
    def test_txt_is_read_as_equalizer_apo(self, tmp_path: Path) -> None:
        path = tmp_path / "HIFIMAN Sundara ParametricEQ.txt"
        path.write_text(AUTOEQ, encoding="utf-8")
        imported = import_preset_file(path)
        assert imported.source_format == "equalizer-apo"
        assert imported.name == "HIFIMAN Sundara ParametricEQ"  # the filename is the name
        assert len(imported.preset.bands) == 4

    def test_peace_files_carry_their_description(self, tmp_path: Path) -> None:
        path = tmp_path / "Sundara.peace"
        path.write_text(SUNDARA_PEACE, encoding="utf-8")
        imported = import_preset_file(path)
        assert imported.source_format == "peace"
        assert imported.description == "Sundara Headphones"

    def test_native_formats_still_work(self, tmp_path: Path) -> None:
        path = tmp_path / "p.json"
        path.write_text(
            '{"name": "Mine", "bands": [{"filter_type": "peaking", '
            '"frequency_hz": 1000, "gain_db": 3}]}',
            encoding="utf-8",
        )
        imported = import_preset_file(path)
        assert imported.source_format == "trxmp"
        assert imported.name == "Mine"

    def test_a_bom_does_not_break_the_import(self, tmp_path: Path) -> None:
        """Windows editors leave one behind; a headphone preset is not
        the place to explain byte-order marks to a user."""
        path = tmp_path / "bom.txt"
        path.write_text(AUTOEQ, encoding="utf-8-sig")
        assert len(import_preset_file(path).preset.bands) == 4

    def test_non_utf8_bytes_do_not_break_the_import(self, tmp_path: Path) -> None:
        path = tmp_path / "latin.peace"
        path.write_bytes(
            SUNDARA_PEACE.replace("Sundara Headphones", "Sennheiser Momentum").encode("latin-1")
        )
        assert import_preset_file(path).description == "Sennheiser Momentum"

    def test_unsupported_extension(self, tmp_path: Path) -> None:
        path = tmp_path / "preset.xml"
        path.write_text("<eq/>", encoding="utf-8")
        with pytest.raises(PresetImportError, match="unsupported preset format"):
            import_preset_file(path)
