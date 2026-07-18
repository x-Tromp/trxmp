"""Preferences tests — the value type and its crash-safe JSON store."""

from __future__ import annotations

import json
from pathlib import Path

from trxmp.application.preferences import AccentColor, Preferences, ThemeMode
from trxmp.infrastructure.preferences_file import JsonPreferencesStore


class TestPreferencesValue:
    def test_defaults_are_sensible(self) -> None:
        preferences = Preferences()
        assert preferences.theme_mode is ThemeMode.DARK
        assert preferences.accent is AccentColor.BLUE
        assert preferences.last_preset is None
        assert preferences.backend_name is None

    def test_with_methods_return_new_objects_and_leave_the_original_alone(self) -> None:
        original = Preferences()
        changed = original.with_accent(AccentColor.PINK)
        assert changed.accent is AccentColor.PINK
        assert original.accent is AccentColor.BLUE  # immutability, proven
        assert changed.theme_mode is original.theme_mode  # everything else carried over

    def test_with_backend_name_returns_a_new_object(self) -> None:
        original = Preferences()
        changed = original.with_backend_name("Lab Mode")
        assert changed.backend_name == "Lab Mode"
        assert original.backend_name is None


class TestJsonPreferencesStore:
    def test_save_then_load_roundtrips(self, tmp_path: Path) -> None:
        store = JsonPreferencesStore(tmp_path / "prefs.json")
        saved = Preferences(ThemeMode.LIGHT, AccentColor.PURPLE, "Sundara")
        store.save(saved)
        assert store.load() == saved

    def test_missing_file_loads_defaults(self, tmp_path: Path) -> None:
        store = JsonPreferencesStore(tmp_path / "does-not-exist.json")
        assert store.load() == Preferences()

    def test_corrupt_file_loads_defaults_instead_of_crashing(self, tmp_path: Path) -> None:
        """The scenario this protects against: a power cut left the
        settings file truncated. Refusing to open the app over that
        would be an absurd failure mode."""
        path = tmp_path / "prefs.json"
        path.write_text('{"theme_mode": "lig', encoding="utf-8")
        assert JsonPreferencesStore(path).load() == Preferences()

    def test_invalid_values_load_defaults(self, tmp_path: Path) -> None:
        path = tmp_path / "prefs.json"
        path.write_text('{"theme_mode": "neon", "accent": "chartreuse"}', encoding="utf-8")
        assert JsonPreferencesStore(path).load() == Preferences()

    def test_unknown_keys_are_ignored_not_fatal(self, tmp_path: Path) -> None:
        """Unlike presets (extra='forbid'), preferences use
        extra='ignore': a settings file written by a *newer* version
        must not brick an older one. Different data, different policy."""
        path = tmp_path / "prefs.json"
        path.write_text(
            '{"theme_mode": "light", "future_setting": 42}',
            encoding="utf-8",
        )
        assert JsonPreferencesStore(path).load().theme_mode is ThemeMode.LIGHT

    def test_save_creates_parent_directory(self, tmp_path: Path) -> None:
        store = JsonPreferencesStore(tmp_path / "nested" / "deeper" / "prefs.json")
        store.save(Preferences())
        assert (tmp_path / "nested" / "deeper" / "prefs.json").is_file()

    def test_save_leaves_no_temporary_files_behind(self, tmp_path: Path) -> None:
        """The atomic write uses a temp file; if one survives, the
        replace didn't happen and we'd be leaking litter into the user's
        AppData on every single save."""
        store = JsonPreferencesStore(tmp_path / "prefs.json")
        store.save(Preferences())
        store.save(Preferences(ThemeMode.LIGHT))
        assert [p.name for p in tmp_path.iterdir()] == ["prefs.json"]

    def test_saved_file_is_readable_json(self, tmp_path: Path) -> None:
        path = tmp_path / "prefs.json"
        JsonPreferencesStore(path).save(Preferences(ThemeMode.LIGHT, AccentColor.TEAL, "X"))
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data == {
            "theme_mode": "light",
            "accent": "teal",
            "last_preset": "X",
            "show_spectrum": True,
            "backend_name": None,
        }

    def test_spectrum_preference_roundtrips_and_defaults_on(self, tmp_path: Path) -> None:
        store = JsonPreferencesStore(tmp_path / "prefs.json")
        store.save(Preferences(show_spectrum=False))
        assert store.load().show_spectrum is False
        # A prefs file from before M7 has no such key: defaults to on.
        (tmp_path / "old.json").write_text('{"theme_mode": "dark"}', encoding="utf-8")
        assert JsonPreferencesStore(tmp_path / "old.json").load().show_spectrum is True

    def test_backend_name_roundtrips_and_defaults_to_none(self, tmp_path: Path) -> None:
        store = JsonPreferencesStore(tmp_path / "prefs.json")
        store.save(Preferences(backend_name="Lab Mode"))
        assert store.load().backend_name == "Lab Mode"
        # A prefs file from before M11 has no such key: no opinion, let
        # the composition root pick its own default.
        (tmp_path / "old.json").write_text('{"theme_mode": "dark"}', encoding="utf-8")
        assert JsonPreferencesStore(tmp_path / "old.json").load().backend_name is None

    def test_overwriting_replaces_content_completely(self, tmp_path: Path) -> None:
        path = tmp_path / "prefs.json"
        store = JsonPreferencesStore(path)
        store.save(Preferences(ThemeMode.LIGHT, AccentColor.PINK, "a-very-long-preset-name"))
        store.save(Preferences())
        # A shorter write must not leave the old tail behind — the exact
        # bug that in-place rewriting causes and replace-based writing
        # cannot.
        assert json.loads(path.read_text(encoding="utf-8"))["last_preset"] is None
