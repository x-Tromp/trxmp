"""JSON-file preferences storage, written crash-safely.

Two production concerns this file exists to handle:

**Atomic writes.** ``save`` writes to a temporary file, flushes it to
the physical disk, then ``os.replace``s it over the real one — an
atomic operation on both Windows and POSIX. The naive
``path.write_text(...)`` truncates the file *first*, so a power cut or
a crash mid-write leaves a half-written settings file. The temp+replace
dance means the file on disk is always either the complete old version
or the complete new one, never a corpse in between.

**Tolerant loads.** ``load`` never raises. A settings file that's
missing, unreadable, corrupt, or written by a future version falls back
to defaults. Refusing to open someone's equalizer because a preference
file got truncated would be an absurd failure mode.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from trxmp.application.preferences import AccentColor, Preferences, ThemeMode

PREFERENCES_FILENAME = "preferences.json"


class _PreferencesDocument(BaseModel):
    """The on-disk shape. Pydantic at the boundary, as always — this is
    the one place an unknown accent name or a hand-edited typo can enter
    the app, so it's the one place that validates."""

    model_config = ConfigDict(extra="ignore")

    theme_mode: ThemeMode = ThemeMode.DARK
    accent: AccentColor = AccentColor.BLUE
    last_preset: str | None = None


class JsonPreferencesStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> Preferences:
        try:
            document = _PreferencesDocument.model_validate_json(
                self._path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError, ValidationError):
            # Missing, unreadable, malformed JSON, or invalid values —
            # all of them mean the same thing to the user: start fresh.
            return Preferences()
        return Preferences(
            theme_mode=document.theme_mode,
            accent=document.accent,
            last_preset=document.last_preset,
        )

    def save(self, preferences: Preferences) -> None:
        document = _PreferencesDocument(
            theme_mode=preferences.theme_mode,
            accent=preferences.accent,
            last_preset=preferences.last_preset,
        )
        payload = json.dumps(document.model_dump(mode="json"), indent=2) + "\n"

        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Same directory as the target: os.replace is only atomic within
        # a single filesystem, and %TEMP% may well be on another drive.
        descriptor, temporary_path = tempfile.mkstemp(
            dir=self._path.parent, prefix=self._path.name, suffix=".tmp"
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                file.write(payload)
                file.flush()
                os.fsync(file.fileno())  # force to the platter before swapping
            os.replace(temporary_path, self._path)
        except OSError:
            Path(temporary_path).unlink(missing_ok=True)
            raise
