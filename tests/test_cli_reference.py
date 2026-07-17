"""End-to-end CLI tests for the ``reference`` subcommand.

No data-directory isolation needed here (contrast with
test_cli_preset.py): the knowledge base is bundled, read-only reference
data, not something a test run could accidentally pollute.
"""

from __future__ import annotations

import pytest

from trxmp.cli import main


def test_headphones_lists_the_bundled_catalog(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["reference", "headphones"]) == 0
    out = capsys.readouterr().out
    assert "hifiman_sundara" in out
    assert "HiFiMan Sundara" in out


def test_headphone_shows_its_correction_bands(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["reference", "headphone", "hifiman_sundara"]) == 0
    out = capsys.readouterr().out
    assert "HiFiMan Sundara" in out
    assert "peaking" in out
    assert "4500.0 Hz" in out
    assert "approximate" in out  # honest about not being a lab measurement


def test_unknown_headphone_id_fails_with_a_clear_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["reference", "headphone", "does-not-exist"]) == 1
    assert "no headphone" in capsys.readouterr().err


def test_frequency_reports_the_named_region(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["reference", "frequency", "3500"]) == 0
    out = capsys.readouterr().out
    assert "Upper-mids" in out


def test_frequency_outside_the_range_does_not_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["reference", "frequency", "999999"]) == 0
    assert "outside" in capsys.readouterr().out
