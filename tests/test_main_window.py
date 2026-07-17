"""Main window tests — the whole shell, with fakes instead of a disk.

The window takes its library and preferences store as constructor
arguments, so these tests hand it in-memory doubles: no SQLite file, no
AppData directory, no cleanup. That's dependency injection paying for
itself, and it's why the architecture rule "ui must not import
infrastructure" is worth enforcing.
"""

from __future__ import annotations

import pytest
from pytestqt.qtbot import QtBot

from tests.fakes import (
    ARCTIS,
    SPEAKERS,
    FakeBackend,
    FakeCaptureSource,
    FakeDeviceService,
    FakePreferencesStore,
    InMemoryDeviceProfileRepository,
    InMemoryPresetRepository,
)
from trxmp.application.devices import ProfileManager
from trxmp.application.preferences import AccentColor, Preferences, ThemeMode
from trxmp.application.preset_library import PresetLibrary
from trxmp.domain.equalizer import EqBand, EqPreset
from trxmp.dsp.biquad import FilterType
from trxmp.ui.main_window import MainWindow

FakeRepository = InMemoryPresetRepository


@pytest.fixture
def repository() -> InMemoryPresetRepository:
    return InMemoryPresetRepository()


@pytest.fixture
def store() -> FakePreferencesStore:
    return FakePreferencesStore()


def _window(
    qtbot: QtBot,
    repository: InMemoryPresetRepository,
    store: FakePreferencesStore,
    backend: FakeBackend | None = None,
    device_service: FakeDeviceService | None = None,
    profile_manager: ProfileManager | None = None,
    apo_support_check: object = None,
    capture_source: FakeCaptureSource | None = None,
) -> MainWindow:
    library = PresetLibrary(repository)
    window = MainWindow(
        library,
        store,
        backend or FakeBackend(),
        device_service or FakeDeviceService(),
        profile_manager or ProfileManager(InMemoryDeviceProfileRepository(), library),
        apo_support_check,  # type: ignore[arg-type]
        capture_source,
    )
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


class TestDeviceProfiles:
    def test_current_output_device_is_shown(
        self, qtbot: QtBot, repository: FakeRepository, store: FakePreferencesStore
    ) -> None:
        window = _window(qtbot, repository, store)
        assert "Arctis Nova 5" in window._device_label.text()

    def test_switching_to_a_bound_device_loads_its_preset(
        self, qtbot: QtBot, repository: FakeRepository, store: FakePreferencesStore
    ) -> None:
        """The headline of M5: plug in the headphones, get their curve."""
        library = PresetLibrary(repository)
        library.save("Gaming", EqPreset(bands=(EqBand(FilterType.LOW_SHELF, 60.0, 5.0, 0.7),)))
        manager = ProfileManager(InMemoryDeviceProfileRepository(), library)
        manager.bind(SPEAKERS, "Gaming")

        service = FakeDeviceService(default=ARCTIS)
        window = _window(qtbot, repository, store, device_service=service, profile_manager=manager)
        assert len(window._model.bands) == 10  # the default layout

        service.default = SPEAKERS
        window._device_controller.refresh()

        assert len(window._model.bands) == 1
        assert window._model.bands[0].gain_db == 5.0
        assert "Gaming" in window._device_label.text()

    def test_switching_to_an_unbound_device_leaves_the_eq_alone(
        self, qtbot: QtBot, repository: FakeRepository, store: FakePreferencesStore
    ) -> None:
        """Automatic behaviour must be earned by an explicit decision.
        Someone who never made a profile keeps their curve."""
        service = FakeDeviceService(default=ARCTIS)
        window = _window(qtbot, repository, store, device_service=service)
        window._model.set_band_gain(0, 7.0)

        service.default = SPEAKERS
        window._device_controller.refresh()

        assert window._model.bands[0].gain_db == 7.0

    def test_linking_requires_a_saved_preset(
        self, qtbot: QtBot, repository: FakeRepository, store: FakePreferencesStore
    ) -> None:
        """A profile stores a preset *name*; a live unsaved curve has
        none, so the button must explain rather than silently do nothing."""
        window = _window(qtbot, repository, store)
        assert window._preset_box.currentData() is None  # "Custom"
        assert window._link_button.isEnabled()

    def test_link_button_binds_and_unbinds_the_selected_preset(
        self, qtbot: QtBot, repository: FakeRepository, store: FakePreferencesStore
    ) -> None:
        repository.upsert("Gaming", "", EqPreset.flat())
        library = PresetLibrary(repository)
        manager = ProfileManager(InMemoryDeviceProfileRepository(), library)
        window = _window(qtbot, repository, store, profile_manager=manager)

        index = window._preset_box.findData("Gaming")
        window._preset_box.setCurrentIndex(index)
        window._on_preset_selected(index)
        window._link_button.click()

        profile = manager.profile_for(ARCTIS)
        assert profile is not None
        assert profile.preset_name == "Gaming"
        assert window._link_button.text() == "Unlink"

        window._link_button.click()
        assert manager.profile_for(ARCTIS) is None

    def test_warns_when_apo_is_missing_on_this_device(
        self, qtbot: QtBot, repository: FakeRepository, store: FakePreferencesStore
    ) -> None:
        """The silent failure this exists to prevent: EQ on, curve set,
        nothing happens, because APO was never hooked to this endpoint."""
        window = _window(qtbot, repository, store, apo_support_check=lambda _: False)
        assert "not installed on this device" in window._device_label.text()

    def test_no_warning_when_support_is_unknown(
        self, qtbot: QtBot, repository: FakeRepository, store: FakePreferencesStore
    ) -> None:
        """ "Couldn't read the registry" is not the same claim as "APO is
        missing", and must not be dressed up as one."""
        window = _window(qtbot, repository, store, apo_support_check=lambda _: None)
        assert "not installed on this device" not in window._device_label.text()

    def test_losing_all_output_is_handled(
        self, qtbot: QtBot, repository: FakeRepository, store: FakePreferencesStore
    ) -> None:
        service = FakeDeviceService(default=ARCTIS)
        window = _window(qtbot, repository, store, device_service=service)
        service.default = None
        window._device_controller.refresh()
        assert "No audio output" in window._device_label.text()
        assert not window._link_button.isEnabled()


class TestSpectrum:
    def test_no_capture_source_means_no_button(
        self, qtbot: QtBot, repository: FakeRepository, store: FakePreferencesStore
    ) -> None:
        window = _window(qtbot, repository, store)
        assert not window._spectrum_button.isVisible()

    def test_starts_on_open_when_the_preference_says_so(
        self, qtbot: QtBot, repository: FakeRepository, store: FakePreferencesStore
    ) -> None:
        capture = FakeCaptureSource()
        window = _window(qtbot, repository, store, capture_source=capture)
        assert capture.started
        assert window._spectrum_button.isChecked()

    def test_stays_off_when_the_preference_says_off(
        self, qtbot: QtBot, repository: FakeRepository
    ) -> None:
        store = FakePreferencesStore(Preferences(show_spectrum=False))
        capture = FakeCaptureSource()
        _window(qtbot, repository, store, capture_source=capture)
        assert not capture.started

    def test_toggling_the_button_stops_capture_and_persists(
        self, qtbot: QtBot, repository: FakeRepository, store: FakePreferencesStore
    ) -> None:
        capture = FakeCaptureSource()
        window = _window(qtbot, repository, store, capture_source=capture)
        window._spectrum_button.setChecked(False)
        assert not capture.started
        assert store.preferences.show_spectrum is False
        window._spectrum_button.setChecked(True)
        assert capture.started
        assert store.preferences.show_spectrum is True

    def test_a_refused_capture_leaves_the_button_unchecked(
        self, qtbot: QtBot, repository: FakeRepository, store: FakePreferencesStore
    ) -> None:
        """No loopback on this machine: the analyzer quietly stays off
        instead of erroring at someone whose EQ works fine."""
        capture = FakeCaptureSource(start_ok=False)
        window = _window(qtbot, repository, store, capture_source=capture)
        assert not window._spectrum_button.isChecked()
        assert not capture.started

    def test_a_device_change_reopens_the_loopback(
        self, qtbot: QtBot, repository: FakeRepository, store: FakePreferencesStore
    ) -> None:
        """The captured loopback twin belongs to the old device; keeping
        it open would show the spectrum of headphones no longer in use."""
        capture = FakeCaptureSource()
        service = FakeDeviceService(default=ARCTIS)
        window = _window(qtbot, repository, store, device_service=service, capture_source=capture)
        assert capture.start_count == 1
        service.default = SPEAKERS
        window._device_controller.refresh()
        assert capture.stop_count == 1
        assert capture.start_count == 2

    def test_close_stops_the_capture_thread(
        self, qtbot: QtBot, repository: FakeRepository, store: FakePreferencesStore
    ) -> None:
        capture = FakeCaptureSource()
        window = _window(qtbot, repository, store, capture_source=capture)
        window.close()
        assert not capture.started
