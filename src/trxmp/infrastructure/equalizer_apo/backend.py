"""The Equalizer APO :class:`AudioBackend` implementation.

Being a good citizen on someone else's system is most of what this file
is about. Equalizer APO reads exactly one entry point — ``config.txt`` —
and other tools claim it too: on a machine with Peace installed, that
file says ``Include: peace.txt`` and holds years of the user's presets
behind it. Blindly overwriting it would silently destroy their setup.

So Trxmp:

1. keeps its own filters in a separate ``trxmp.txt`` and never writes
   anyone else's file;
2. backs up ``config.txt`` before claiming it, exactly once, and
3. can put the original back on request.

The two controllers can't both be live — APO would stack both filter
chains and the result would be neither one's EQ — so taking over is a
real, visible act. :attr:`status` names whoever is currently in charge
so the UI can say so out loud rather than quietly stealing the audio.
"""

from __future__ import annotations

from pathlib import Path

from trxmp.application.audio_backend import BackendError, BackendState, BackendStatus
from trxmp.domain.equalizer import EqPreset
from trxmp.infrastructure.atomic_write import write_text_atomic
from trxmp.infrastructure.equalizer_apo.config_format import (
    TRXMP_CONFIG_FILENAME,
    render_bypass_config,
    render_config,
)
from trxmp.infrastructure.equalizer_apo.detection import ApoInstallation

CONFIG_FILENAME = "config.txt"
BACKUP_FILENAME = "config.txt.trxmp-backup"

# Equalizer APO resamples everything to the device's rate; 48 kHz is the
# near-universal Windows shared-mode rate and the rate our headroom
# figures are quoted at. The filter *shapes* barely move between 44.1 and
# 48 kHz at audible frequencies, so this is a safe constant rather than
# something to chase per-device.
_SAMPLE_RATE_HZ = 48_000.0

_ROOT_CONFIG = (
    "# Managed by Trxmp.\n"
    f"# Your previous config.txt was saved next to this file as {BACKUP_FILENAME}.\n"
    f"Include: {TRXMP_CONFIG_FILENAME}\n"
)

# Config filenames we recognise, so the status line can name a rival by
# its product name instead of showing the user a filename.
_KNOWN_CONTROLLERS = {"peace.txt": "Peace"}


class EqualizerApoBackend:
    """Drives Equalizer APO by writing its config files.

    Takes the installation as a constructor argument (``None`` meaning
    "not installed") rather than detecting it internally: that keeps the
    class testable against a temp directory, which is what makes the
    logic above verifiable without a real APO install.
    """

    def __init__(self, installation: ApoInstallation | None) -> None:
        self._installation = installation

    @property
    def name(self) -> str:
        return "Equalizer APO"

    @property
    def status(self) -> BackendStatus:
        if self._installation is None:
            return BackendStatus(
                BackendState.UNAVAILABLE,
                "Equalizer APO is not installed — install it to equalize system audio.",
            )

        includes = self._root_includes()
        others = [name for name in includes if name.lower() != TRXMP_CONFIG_FILENAME]

        if TRXMP_CONFIG_FILENAME in [name.lower() for name in includes]:
            if self._our_config_has_filters():
                return BackendStatus(BackendState.ACTIVE, "Equalizing all system audio.")
            return BackendStatus(BackendState.READY, "Connected — equalizer is off.")

        if others:
            rival = _describe_controller(others[0])
            return BackendStatus(
                BackendState.READY, f"Ready — {rival} currently controls system audio."
            )
        return BackendStatus(BackendState.READY, "Ready — turn the equalizer on to apply.")

    def apply(self, preset: EqPreset) -> None:
        self._write(render_config(preset, _SAMPLE_RATE_HZ))

    def disable(self) -> None:
        """Switch the EQ off without unhooking.

        Writes a do-nothing config rather than removing our Include line,
        so switching back on is one file write instead of another
        take-over. Audio is untouched either way.
        """
        self._write(render_bypass_config())

    def restore_previous_config(self) -> bool:
        """Hand ``config.txt`` back to whoever had it before Trxmp.

        Returns whether there was anything to restore. This is the undo
        for :meth:`apply` — without it, "I tried Trxmp once" would be a
        one-way door for someone's Peace setup.
        """
        installation = self._require_installation()
        backup = installation.config_dir / BACKUP_FILENAME
        if not backup.is_file():
            return False
        try:
            write_text_atomic(
                installation.config_dir / CONFIG_FILENAME, backup.read_text(encoding="utf-8")
            )
            backup.unlink()
        except OSError as error:
            raise BackendError(
                f"Could not restore the previous Equalizer APO config: {error}"
            ) from error
        return True

    # ── Internals ─────────────────────────────────────────────────────
    def _write(self, config_text: str) -> None:
        installation = self._require_installation()
        try:
            write_text_atomic(installation.config_dir / TRXMP_CONFIG_FILENAME, config_text)
            self._claim_root_config()
        except PermissionError as error:
            raise BackendError(
                f"No permission to write to {installation.config_dir}. "
                "Equalizer APO's installer normally grants this — try reinstalling it."
            ) from error
        except OSError as error:
            raise BackendError(f"Could not write the Equalizer APO config: {error}") from error

    def _claim_root_config(self) -> None:
        """Point ``config.txt`` at our file, backing up what was there."""
        installation = self._require_installation()
        config_path = installation.config_dir / CONFIG_FILENAME
        current = _read_text_or_empty(config_path)
        if current.strip() == _ROOT_CONFIG.strip():
            return  # already ours; nothing to do and nothing to back up

        if current:
            backup = installation.config_dir / BACKUP_FILENAME
            # Only ever back up once. Without this guard, the second
            # take-over would overwrite the user's real original with our
            # own generated file — destroying the thing the backup exists
            # to protect.
            if not backup.exists():
                write_text_atomic(backup, current)
        write_text_atomic(config_path, _ROOT_CONFIG)

    def _root_includes(self) -> list[str]:
        installation = self._require_installation()
        text = _read_text_or_empty(installation.config_dir / CONFIG_FILENAME)
        return [
            line.split(":", 1)[1].strip()
            for line in text.splitlines()
            if line.strip().lower().startswith("include:")
        ]

    def _our_config_has_filters(self) -> bool:
        installation = self._require_installation()
        text = _read_text_or_empty(installation.config_dir / TRXMP_CONFIG_FILENAME)
        return any(line.strip().lower().startswith("filter") for line in text.splitlines())

    def _require_installation(self) -> ApoInstallation:
        if self._installation is None:
            raise BackendError("Equalizer APO is not installed.")
        return self._installation


def _describe_controller(config_filename: str) -> str:
    return _KNOWN_CONTROLLERS.get(config_filename.lower(), config_filename)


def _read_text_or_empty(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        # Missing is normal. Unreadable/binary means someone else's mess:
        # treat it as "nothing we recognise" so status still renders
        # instead of taking the whole window down with it.
        return ""
