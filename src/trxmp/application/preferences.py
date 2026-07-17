"""User preferences: the vocabulary, and the interface for storing them.

The enums live here rather than in ``trxmp.ui`` on purpose. "The user
prefers dark mode with a green accent" is *configuration data* — the UI
merely renders it. Keeping the vocabulary in the application layer means
preferences can be persisted, validated, and tested without importing
Qt, and the UI converts them to pixels at the edge.

Storage follows the same shape as M2's preset repository: a Protocol
declared here, an adapter in infrastructure, wired at the composition
root. Same lesson, reinforced rather than reinvented.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Protocol


class ThemeMode(StrEnum):
    DARK = "dark"
    LIGHT = "light"

    def toggled(self) -> ThemeMode:
        return ThemeMode.LIGHT if self is ThemeMode.DARK else ThemeMode.DARK


class AccentColor(StrEnum):
    BLUE = "blue"
    GREEN = "green"
    PURPLE = "purple"
    ORANGE = "orange"
    PINK = "pink"
    TEAL = "teal"


@dataclass(frozen=True, slots=True)
class Preferences:
    """Everything the app remembers between runs.

    Frozen: preferences are replaced, never mutated in place
    (``dataclasses.replace`` gives us cheap "same but with X changed"),
    so a stale reference can never silently disagree with what was saved.
    """

    theme_mode: ThemeMode = ThemeMode.DARK
    accent: AccentColor = AccentColor.BLUE
    last_preset: str | None = None

    def with_theme_mode(self, mode: ThemeMode) -> Preferences:
        return replace(self, theme_mode=mode)

    def with_accent(self, accent: AccentColor) -> Preferences:
        return replace(self, accent=accent)

    def with_last_preset(self, name: str | None) -> Preferences:
        return replace(self, last_preset=name)


class PreferencesStore(Protocol):
    """What the app needs from preferences storage.

    ``load`` must never raise: a corrupt or missing settings file is a
    reason to fall back to defaults, not to prevent the user from
    opening their equalizer.
    """

    def load(self) -> Preferences: ...

    def save(self, preferences: Preferences) -> None: ...
