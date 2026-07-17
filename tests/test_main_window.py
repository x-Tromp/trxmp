"""Main window tests — the whole shell, with fakes instead of a disk.

The window takes its library and preferences store as constructor
arguments, so these tests hand it in-memory doubles: no SQLite file, no
AppData directory, no cleanup. That's dependency injection paying for
itself, and it's why the architecture rule "ui must not import
infrastructure" is worth enforcing.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pytestqt.qtbot import QtBot

from trxmp.application.audio_backend import BackendState, BackendStatus
from trxmp.application.preferences import AccentColor, Preferences, ThemeMode
from trxmp.application.preset_library import PresetLibrary
from trxmp.domain.equalizer import EqBand, EqPreset
from trxmp.domain.library import StoredPreset
from trxmp.dsp.biquad import FilterType
from trxmp.ui.main_window import MainWindow


class FakeRepository:
    def __init__(self) -> None:
        self.items: dict[str, StoredPreset] = {}

    def get(self, name: str) -> StoredPreset | None:
        return self.items.get(name)

    def list_all(self) -> list[StoredPreset]:
        return [self.items[name] for name in sorted(self.items)]

    def upsert(self, name: str, description: str, preset: EqPreset) -> StoredPreset:
        now = datetime.now(UTC)
        stored = StoredPreset(name, description, preset, created_at=now, updated_at=now)
        self.items[name] = stored
        return stored

    def delete(self, name: str) -> bool:
        return self.items.pop(name, None) is not None


class FakePreferencesStore:
    def __init__(self, preferences: Preferences | None = None) -> None:
        self.preferences = preferences or Preferences()
        self.save_count = 0

    def load(self) -> Preferences:
        return self.preferences

    def save(self, preferences: Preferences) -> None:
        self.preferences = preferences
        self.save_count += 1


class FakeBackend:
    """An audio backend that records instead of touching the system."""

    def __init__(self, state: BackendState = BackendState.READY) -> None:
        self.applied: list[EqPreset] = []
        self.state = state

    @property
    def name(self) -> str:
        return "Fake"

    @property
    def status(self) -> BackendStatus:
        return BackendStatus(self.state, "fake backend detail")

    def apply(self, preset: EqPreset) -> None:
        self.applied.append(preset)

    def disable(self) -> None:
        pass


@pytest.fixture
def repository() -> FakeRepository:
    return FakeRepository()


@pytest.fixture
def store() -> FakePreferencesStore:
    return FakePreferencesStore()


def _window(
    qtbot: QtBot,
    repository: FakeRepository,
    store: FakePreferencesStore,
    backend: FakeBackend | None = None,
) -> MainWindow:
    window = MainWindow(PresetLibrary(repository), store, backend or FakeBackend())
    qtbot.addWidget(window)
    return window


def _mode(window: MainWindow) -> ThemeMode:
    """Read the theme through a call, not an attribute.

    ``assert window._theme.mode is ThemeMode.DARK`` would narrow that
    attribute's type to Literal[DARK] for the rest of the function, and
    mypy has no idea a button click changed it — so the later check for
    LIGHT gets flagged as impossible. Going through a function returns a
    fresh, un-narrowed value each time.
    """
    return window._theme.mode


def test_window_opens_with_the_default_flat_eq(
    qtbot: QtBot, repository: FakeRepository, store: FakePreferencesStore
) -> None:
    window = _window(qtbot, repository, store)
    assert window.windowTitle() == "Trxmp"
    assert len(window._model.bands) == 10
    assert all(band.gain_db == 0.0 for band in window._model.bands)


def test_toggling_theme_updates_the_ui_and_persists_the_choice(
    qtbot: QtBot, repository: FakeRepository, store: FakePreferencesStore
) -> None:
    window = _window(qtbot, repository, store)
    assert _mode(window) is ThemeMode.DARK

    window._theme_button.click()

    assert _mode(window) is ThemeMode.LIGHT
    assert store.preferences.theme_mode is ThemeMode.LIGHT
    assert window._theme.palette.background in window.styleSheet()


def test_choosing_an_accent_persists_and_restyles(
    qtbot: QtBot, repository: FakeRepository, store: FakePreferencesStore
) -> None:
    window = _window(qtbot, repository, store)
    window._accent_buttons[AccentColor.PINK].click()
    assert store.preferences.accent is AccentColor.PINK
    assert window._theme.palette.accent in window.styleSheet()


def test_preferences_are_restored_on_open(qtbot: QtBot, repository: FakeRepository) -> None:
    store = FakePreferencesStore(Preferences(ThemeMode.LIGHT, AccentColor.TEAL))
    window = _window(qtbot, repository, store)
    assert _mode(window) is ThemeMode.LIGHT
    assert window._theme.accent is AccentColor.TEAL


def test_saved_presets_appear_in_the_picker_and_load(
    qtbot: QtBot, repository: FakeRepository, store: FakePreferencesStore
) -> None:
    repository.upsert(
        "Sundara", "", EqPreset(bands=(EqBand(FilterType.PEAKING, 4_500.0, -3.0, 2.5),))
    )
    window = _window(qtbot, repository, store)

    index = window._preset_box.findData("Sundara")
    assert index >= 0
    window._preset_box.setCurrentIndex(index)
    window._on_preset_selected(index)

    assert len(window._model.bands) == 1
    assert window._model.bands[0].frequency_hz == 4_500.0
    assert store.preferences.last_preset == "Sundara"


def test_last_preset_is_restored_on_open(qtbot: QtBot, repository: FakeRepository) -> None:
    repository.upsert("Mine", "", EqPreset(bands=(EqBand(FilterType.PEAKING, 800.0, 2.0, 1.0),)))
    store = FakePreferencesStore(Preferences(last_preset="Mine"))
    window = _window(qtbot, repository, store)
    assert window._model.bands[0].frequency_hz == 800.0


def test_a_deleted_last_preset_does_not_break_startup(
    qtbot: QtBot, repository: FakeRepository
) -> None:
    """The preset was renamed or deleted since last run. The app must
    open on defaults and forget it, not greet the user with an error."""
    store = FakePreferencesStore(Preferences(last_preset="ghost"))
    window = _window(qtbot, repository, store)
    assert len(window._model.bands) == 10
    assert store.preferences.last_preset is None


def test_power_button_bypasses_the_eq(
    qtbot: QtBot, repository: FakeRepository, store: FakePreferencesStore
) -> None:
    window = _window(qtbot, repository, store)
    window._model.set_band_gain(0, 6.0)

    window._power_button.click()

    assert window._model.powered is False
    assert window._power_button.text() == "EQ OFF"
    assert window._model.effective_preset().bands == ()


def test_metrics_report_peak_and_auto_preamp(
    qtbot: QtBot, repository: FakeRepository, store: FakePreferencesStore
) -> None:
    """The readout is the app's honesty about gain staging — if it
    silently stopped updating, a user could clip without warning."""
    window = _window(qtbot, repository, store)
    assert "+0.0 dB" in window._metrics_label.text()

    window._model.set_band_gain(5, 6.0)  # 1 kHz +6 dB

    text = window._metrics_label.text()
    assert "peak +6" in text
    assert "-6.5" in text  # 6 dB peak + 0.5 dB safety margin


def test_reset_returns_to_flat(
    qtbot: QtBot, repository: FakeRepository, store: FakePreferencesStore
) -> None:
    window = _window(qtbot, repository, store)
    window._model.set_band_gain(0, 8.0)
    window._model.reset()
    assert all(band.gain_db == 0.0 for band in window._model.bands)


def test_backend_status_is_shown_on_open(
    qtbot: QtBot, repository: FakeRepository, store: FakePreferencesStore
) -> None:
    window = _window(qtbot, repository, store)
    assert "fake backend detail" in window._status_label.text()


def test_opening_the_window_does_not_touch_system_audio(
    qtbot: QtBot, repository: FakeRepository
) -> None:
    """Restoring the last preset at startup must not seize control of
    Equalizer APO from whatever is already using it."""
    repository.upsert("Mine", "", EqPreset(bands=(EqBand(FilterType.PEAKING, 800.0, 2.0, 1.0),)))
    store = FakePreferencesStore(Preferences(last_preset="Mine"))
    backend = FakeBackend()
    _window(qtbot, repository, store, backend)
    assert backend.applied == []


def test_status_line_survives_a_theme_change(
    qtbot: QtBot, repository: FakeRepository, store: FakePreferencesStore
) -> None:
    """Its indicator dot is palette-coloured, so it must be re-rendered
    rather than left showing the old theme's colour."""
    window = _window(qtbot, repository, store)
    window._theme_button.click()
    assert "fake backend detail" in window._status_label.text()
