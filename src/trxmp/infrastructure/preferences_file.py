"""JSON-file preferences storage, written crash-safely.

Two production concerns this file exists to handle:

**Atomic writes**, via :func:`~trxmp.infrastructure.atomic_write.write_text_atomic`
— a settings file must never survive a crash half-written.

**Tolerant loads.** ``load`` never raises. A settings file that's
missing, unreadable, corrupt, or written by a future version falls back
to defaults. Refusing to open someone's equalizer because a preference
file got truncated would be an absurd failure mode.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from trxmp.application.preferences import AccentColor, Preferences, ThemeMode
from trxmp.infrastructure.atomic_write import write_text_atomic

PREFERENCES_FILENAME = "preferences.json"


class _PreferencesDocument(BaseModel):
    """The on-disk shape. Pydantic at the boundary, as always — this is
    the one place an unknown accent name or a hand-edited typo can enter
    the app, so it's the one place that validates."""

    model_config = ConfigDict(extra="ignore")

    theme_mode: ThemeMode = ThemeMode.DARK
    accent: AccentColor = AccentColor.BLUE
    last_preset: str | None = None
    show_spectrum: bool = True
    backend_name: str | None = None


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
            show_spectrum=document.show_spectrum,
            backend_name=document.backend_name,
        )

    def save(self, preferences: Preferences) -> None:
        document = _PreferencesDocument(
            theme_mode=preferences.theme_mode,
            accent=preferences.accent,
            last_preset=preferences.last_preset,
            show_spectrum=preferences.show_spectrum,
            backend_name=preferences.backend_name,
        )
        payload = json.dumps(document.model_dump(mode="json"), indent=2) + "\n"
        write_text_atomic(self._path, payload)
