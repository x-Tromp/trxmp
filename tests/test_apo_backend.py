"""Equalizer APO backend tests — against a fake install in a temp folder.

The backend takes its installation as a constructor argument precisely
so these can exist. Everything except "does the real APO driver reload
the file" is exercised here, including the parts that would otherwise
only be discovered by destroying someone's Peace setup.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from trxmp.application.audio_backend import BackendError, BackendState
from trxmp.domain.equalizer import EqBand, EqPreset
from trxmp.dsp.biquad import FilterType
from trxmp.infrastructure.equalizer_apo.backend import (
    BACKUP_FILENAME,
    CONFIG_FILENAME,
    EqualizerApoBackend,
)
from trxmp.infrastructure.equalizer_apo.config_format import TRXMP_CONFIG_FILENAME
from trxmp.infrastructure.equalizer_apo.detection import ApoInstallation

PEACE_CONFIG = "Include: peace.txt\n"


@pytest.fixture
def install(tmp_path: Path) -> ApoInstallation:
    installation = ApoInstallation.at(tmp_path / "EqualizerAPO")
    installation.config_dir.mkdir(parents=True)
    return installation


@pytest.fixture
def backend(install: ApoInstallation) -> EqualizerApoBackend:
    return EqualizerApoBackend(install)


def _preset() -> EqPreset:
    return EqPreset(bands=(EqBand(FilterType.PEAKING, 1_000.0, 6.0, 1.0),))


class TestWithoutAnInstallation:
    def test_status_is_unavailable_and_explains_itself(self) -> None:
        status = EqualizerApoBackend(None).status
        assert status.state is BackendState.UNAVAILABLE
        assert "not installed" in status.detail
        assert not status.is_usable

    def test_applying_raises_a_backend_error_not_a_crash(self) -> None:
        with pytest.raises(BackendError, match="not installed"):
            EqualizerApoBackend(None).apply(_preset())


class TestApplying:
    def test_apply_writes_our_config_and_claims_config_txt(
        self, backend: EqualizerApoBackend, install: ApoInstallation
    ) -> None:
        backend.apply(_preset())

        ours = (install.config_dir / TRXMP_CONFIG_FILENAME).read_text(encoding="utf-8")
        assert "Filter 1: ON PK Fc 1000.00 Hz Gain 6.00 dB Q 1.0000" in ours
        assert "Preamp: -6.50 dB" in ours

        root = (install.config_dir / CONFIG_FILENAME).read_text(encoding="utf-8")
        assert f"Include: {TRXMP_CONFIG_FILENAME}" in root

    def test_status_becomes_active(self, backend: EqualizerApoBackend) -> None:
        backend.apply(_preset())
        status = backend.status
        assert status.state is BackendState.ACTIVE
        assert status.is_usable

    def test_disable_bypasses_but_stays_connected(
        self, backend: EqualizerApoBackend, install: ApoInstallation
    ) -> None:
        backend.apply(_preset())
        backend.disable()

        ours = (install.config_dir / TRXMP_CONFIG_FILENAME).read_text(encoding="utf-8")
        assert "Filter" not in ours
        assert "Preamp: 0.00 dB" in ours
        # Still wired: switching back on is one write, not a re-take-over.
        assert f"Include: {TRXMP_CONFIG_FILENAME}" in (
            install.config_dir / CONFIG_FILENAME
        ).read_text(encoding="utf-8")
        assert backend.status.state is BackendState.READY

    def test_applying_repeatedly_is_stable(
        self, backend: EqualizerApoBackend, install: ApoInstallation
    ) -> None:
        for gain in (1.0, 2.0, 3.0):
            backend.apply(EqPreset(bands=(EqBand(FilterType.PEAKING, 1_000.0, gain, 1.0),)))
        root = (install.config_dir / CONFIG_FILENAME).read_text(encoding="utf-8")
        assert root.count(f"Include: {TRXMP_CONFIG_FILENAME}") == 1  # not appended each time
        assert "Gain 3.00 dB" in (install.config_dir / TRXMP_CONFIG_FILENAME).read_text(
            encoding="utf-8"
        )


class TestCoexistingWithOtherControllers:
    """The scenario that matters on a real machine: Peace is already
    installed and owns config.txt, with the user's presets behind it."""

    def test_status_names_the_current_controller(
        self, backend: EqualizerApoBackend, install: ApoInstallation
    ) -> None:
        (install.config_dir / CONFIG_FILENAME).write_text(PEACE_CONFIG, encoding="utf-8")
        status = backend.status
        assert status.state is BackendState.READY
        assert "Peace" in status.detail  # the product name, not "peace.txt"

    def test_taking_over_backs_up_the_previous_config(
        self, backend: EqualizerApoBackend, install: ApoInstallation
    ) -> None:
        (install.config_dir / CONFIG_FILENAME).write_text(PEACE_CONFIG, encoding="utf-8")
        backend.apply(_preset())
        assert (install.config_dir / BACKUP_FILENAME).read_text(encoding="utf-8") == PEACE_CONFIG

    def test_we_never_write_someone_elses_config_file(
        self, backend: EqualizerApoBackend, install: ApoInstallation
    ) -> None:
        """Peace's own file is untouched — its presets survive Trxmp."""
        peace_file = install.config_dir / "peace.txt"
        peace_file.write_text("Filter: ON PK Fc 500 Hz Gain 5 dB Q 1\n", encoding="utf-8")
        (install.config_dir / CONFIG_FILENAME).write_text(PEACE_CONFIG, encoding="utf-8")

        backend.apply(_preset())

        assert peace_file.read_text(encoding="utf-8") == "Filter: ON PK Fc 500 Hz Gain 5 dB Q 1\n"

    def test_second_take_over_does_not_overwrite_the_original_backup(
        self, backend: EqualizerApoBackend, install: ApoInstallation
    ) -> None:
        """The subtle one. Without the 'back up only once' guard, the
        second apply would save *our own* config.txt over the user's
        original — quietly destroying the very thing the backup exists
        to protect, and making restore a no-op."""
        (install.config_dir / CONFIG_FILENAME).write_text(PEACE_CONFIG, encoding="utf-8")
        backend.apply(_preset())
        backend.apply(_preset())
        backend.disable()
        assert (install.config_dir / BACKUP_FILENAME).read_text(encoding="utf-8") == PEACE_CONFIG

    def test_restore_hands_config_back_and_removes_the_backup(
        self, backend: EqualizerApoBackend, install: ApoInstallation
    ) -> None:
        (install.config_dir / CONFIG_FILENAME).write_text(PEACE_CONFIG, encoding="utf-8")
        backend.apply(_preset())

        assert backend.restore_previous_config() is True

        assert (install.config_dir / CONFIG_FILENAME).read_text(encoding="utf-8") == PEACE_CONFIG
        assert not (install.config_dir / BACKUP_FILENAME).exists()
        assert "Peace" in backend.status.detail  # Peace is back in charge

    def test_restore_without_a_backup_reports_nothing_to_do(
        self, backend: EqualizerApoBackend
    ) -> None:
        assert backend.restore_previous_config() is False


class TestFreshInstall:
    def test_status_on_an_untouched_install_invites_action(
        self, backend: EqualizerApoBackend
    ) -> None:
        status = backend.status
        assert status.state is BackendState.READY
        assert "turn the equalizer on" in status.detail

    def test_apply_creates_config_txt_when_absent(
        self, backend: EqualizerApoBackend, install: ApoInstallation
    ) -> None:
        backend.apply(_preset())
        assert (install.config_dir / CONFIG_FILENAME).is_file()
        assert not (install.config_dir / BACKUP_FILENAME).exists()  # nothing to back up


class TestBrokenInstall:
    def test_unwritable_config_dir_raises_a_helpful_backend_error(
        self, install: ApoInstallation, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Windows normally lets users write here because APO's installer
        says so — but if it doesn't, the user needs a sentence they can
        act on, not a PermissionError traceback."""

        def deny(*args: object, **kwargs: object) -> None:
            raise PermissionError("access is denied")

        monkeypatch.setattr("trxmp.infrastructure.equalizer_apo.backend.write_text_atomic", deny)
        with pytest.raises(BackendError, match="permission"):
            EqualizerApoBackend(install).apply(_preset())

    def test_unreadable_config_txt_does_not_break_status(
        self, backend: EqualizerApoBackend, install: ApoInstallation
    ) -> None:
        (install.config_dir / CONFIG_FILENAME).write_bytes(b"\xff\xfe\x00binary junk")
        assert backend.status.state is BackendState.READY  # renders instead of crashing
