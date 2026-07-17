"""End-to-end CLI tests for the preset library.

These run the real ``main()`` against a real SQLite database in a temp
directory (via the TRXMP_DATA_DIR seam), exercising the full stack:
argparse -> application -> repository -> SQLite -> back out. The kind of
test that catches wiring mistakes unit tests can't see.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from trxmp.cli import main
from trxmp.infrastructure.paths import ENV_DATA_DIR


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the app's database at a throwaway directory for every test."""
    monkeypatch.setenv(ENV_DATA_DIR, str(tmp_path))


@pytest.fixture
def preset_file(tmp_path: Path) -> Path:
    path = tmp_path / "sundara.yaml"
    path.write_text(
        "format: trxmp-preset\n"
        "version: 1\n"
        "name: Sundara\n"
        "description: planar reference\n"
        "preamp_db: -1.0\n"
        "bands:\n"
        "  - filter_type: peaking\n"
        "    frequency_hz: 4500\n"
        "    gain_db: -3.0\n"
        "    q: 2.5\n",
        encoding="utf-8",
    )
    return path


def test_import_list_show_export_delete_cycle(
    preset_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["preset", "import", str(preset_file)]) == 0
    assert "imported 'Sundara'" in capsys.readouterr().out

    assert main(["preset", "list"]) == 0
    assert "Sundara" in capsys.readouterr().out

    assert main(["preset", "show", "Sundara"]) == 0
    show_out = capsys.readouterr().out
    assert "planar reference" in show_out
    assert "4500.0 Hz" in show_out

    export_path = tmp_path / "out.json"
    assert main(["preset", "export", "Sundara", str(export_path)]) == 0
    assert export_path.is_file()
    assert '"trxmp-preset"' in export_path.read_text(encoding="utf-8")

    assert main(["preset", "delete", "Sundara"]) == 0
    capsys.readouterr()  # discard the 'deleted' line before checking the list
    assert main(["preset", "list"]) == 0
    assert "Sundara" not in capsys.readouterr().out


def test_import_persists_across_separate_invocations(preset_file: Path) -> None:
    """Two independent main() calls = two processes' worth of isolation.
    The preset surviving proves it really hit disk, not just memory."""
    assert main(["preset", "import", str(preset_file)]) == 0
    assert main(["preset", "show", "Sundara"]) == 0  # fresh engine, still there


def test_duplicate_import_fails_without_overwrite(
    preset_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["preset", "import", str(preset_file)]) == 0
    capsys.readouterr()
    assert main(["preset", "import", str(preset_file)]) == 1
    assert "already exists" in capsys.readouterr().err
    assert main(["preset", "import", str(preset_file), "--overwrite"]) == 0


def test_process_can_use_an_imported_preset(
    preset_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The headline integration: a library preset drives real DSP."""
    main(["preset", "import", str(preset_file)])
    capsys.readouterr()

    import numpy as np

    from trxmp.infrastructure.wav_io import save_wav

    wav_in = tmp_path / "in.wav"
    t = np.arange(4_410) / 44_100.0
    tone = 0.3 * np.sin(2.0 * np.pi * 440.0 * t)
    save_wav(wav_in, np.tile(tone[:, np.newaxis], (1, 2)), 44_100)

    wav_out = tmp_path / "out.wav"
    assert main(["process", str(wav_in), str(wav_out), "--preset", "Sundara"]) == 0
    assert wav_out.is_file()
    assert "preset            : Sundara" in capsys.readouterr().out


def test_unknown_preset_reports_available_ones(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import numpy as np

    from trxmp.infrastructure.wav_io import save_wav

    wav_in = tmp_path / "in.wav"
    save_wav(wav_in, np.zeros((100, 2)), 44_100)

    assert main(["process", str(wav_in), str(tmp_path / "out.wav"), "--preset", "ghost"]) == 1
    err = capsys.readouterr().err
    assert "unknown preset" in err
    assert "bass-boost" in err  # lists builtins to help the user
