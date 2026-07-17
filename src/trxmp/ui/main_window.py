"""The main window — composes the shell, owns the theme, wires the parts.

Everything it needs arrives through its constructor (the preset library,
the preferences store). It never constructs a repository or reaches for
a file path: that's ``app.py``'s job. This is what makes the window
testable with fakes, and it's why the architecture test can forbid
``trxmp.ui`` from importing ``trxmp.infrastructure`` at all.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from trxmp.application.audio_backend import AudioBackend, BackendState, BackendStatus
from trxmp.application.devices import AudioDeviceService, ProfileManager
from trxmp.application.eq_analysis import DEFAULT_SAMPLE_RATE_HZ
from trxmp.application.preferences import AccentColor, Preferences, PreferencesStore, ThemeMode
from trxmp.application.preset_library import PresetLibrary
from trxmp.domain.devices import AudioDevice
from trxmp.domain.errors import EqualizerError
from trxmp.ui.backend_controller import BackendController
from trxmp.ui.device_controller import DeviceController
from trxmp.ui.theme import SPACE_LG, SPACE_MD, SPACE_SM, Theme
from trxmp.ui.view_models import EqViewModel
from trxmp.ui.widgets.band_controls import BandControls
from trxmp.ui.widgets.eq_curve import EqCurveWidget

_ACCENT_SWATCH_SIZE = 14

# Answers "will the EQ actually reach this device?"; injected because it
# reads the Windows registry, which the UI layer must not know about.
ApoSupportCheck = Callable[[str], bool | None]


class MainWindow(QMainWindow):
    def __init__(
        self,
        library: PresetLibrary,
        preferences_store: PreferencesStore,
        backend: AudioBackend,
        device_service: AudioDeviceService,
        profile_manager: ProfileManager,
        apo_support_check: ApoSupportCheck | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._library = library
        self._preferences_store = preferences_store
        self._preferences = preferences_store.load()
        self._theme = Theme(self._preferences.theme_mode, self._preferences.accent)
        self._model = EqViewModel()
        self._profile_manager = profile_manager
        self._apo_support_check = apo_support_check or (lambda _: None)
        self._accent_buttons: dict[AccentColor, QPushButton] = {}
        # Kept so a theme change can re-render the status line in the new
        # palette without asking the backend again (which touches disk).
        self._backend_status = BackendStatus(BackendState.READY, "")

        self.setWindowTitle("Trxmp")
        self.resize(1000, 700)
        self.setMinimumSize(820, 560)

        self._build_ui()
        self._apply_theme()
        self._reload_preset_list()
        self._restore_last_preset()

        self._model.bands_changed.connect(self._update_metrics)
        self._model.preamp_changed.connect(self._update_metrics)
        self._model.powered_changed.connect(self._update_metrics)
        self._update_metrics()

        # Wired last, and started explicitly: restoring the last preset
        # above emits signals, and none of them should push audio out to
        # the system before the user has touched anything.
        self._backend_controller = BackendController(self._model, backend, parent=self)
        self._backend_controller.status_changed.connect(self._show_backend_status)
        self._show_backend_status(self._backend_controller.status)
        self._backend_controller.start()

        self._device_controller = DeviceController(device_service, parent=self)
        self._device_controller.device_changed.connect(self._on_device_changed)
        self._device_controller.start()
        self._show_device(self._device_controller.current_device)

    # ── Construction ──────────────────────────────────────────────────
    def _build_ui(self) -> None:
        central = QWidget(self)
        root = QVBoxLayout(central)
        root.setContentsMargins(SPACE_LG, SPACE_LG, SPACE_LG, SPACE_LG)
        root.setSpacing(SPACE_MD)

        root.addLayout(self._build_header())
        root.addWidget(self._wrap_in_card(self._build_curve_section()), stretch=1)
        root.addWidget(self._wrap_in_card(BandControls(self._model, self)))
        self.setCentralWidget(central)

    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        header.setSpacing(SPACE_SM)

        brand = QLabel("Trxmp", self)
        brand.setObjectName("brand")
        header.addWidget(brand)
        header.addSpacing(SPACE_MD)

        status_column = QVBoxLayout()
        status_column.setSpacing(2)
        self._status_label = QLabel(self)
        self._status_label.setObjectName("caption")
        self._device_label = QLabel(self)
        self._device_label.setObjectName("caption")
        status_column.addWidget(self._status_label)
        status_column.addWidget(self._device_label)
        header.addLayout(status_column)
        header.addSpacing(SPACE_MD)

        self._preset_box = QComboBox(self)
        self._preset_box.setAccessibleName("Preset")
        self._preset_box.activated.connect(self._on_preset_selected)
        header.addWidget(self._preset_box)

        save_button = QPushButton("Save as…", self)
        save_button.clicked.connect(self._on_save_preset)
        header.addWidget(save_button)

        reset_button = QPushButton("Reset", self)
        reset_button.setObjectName("ghost")
        reset_button.clicked.connect(self._model.reset)
        header.addWidget(reset_button)

        self._link_button = QPushButton("Link to device", self)
        self._link_button.clicked.connect(self._on_link_clicked)
        header.addWidget(self._link_button)

        header.addStretch(1)

        for accent in AccentColor:
            header.addWidget(self._build_accent_swatch(accent))
        header.addSpacing(SPACE_SM)

        self._theme_button = QPushButton(self)
        self._theme_button.setObjectName("ghost")
        self._theme_button.setFixedWidth(64)
        self._theme_button.clicked.connect(self._on_toggle_theme)
        header.addWidget(self._theme_button)

        self._power_button = QPushButton("EQ ON", self)
        self._power_button.setObjectName("primary")
        self._power_button.setCheckable(True)
        self._power_button.setChecked(True)
        self._power_button.toggled.connect(self._on_power_toggled)
        header.addWidget(self._power_button)
        return header

    def _build_accent_swatch(self, accent: AccentColor) -> QPushButton:
        button = QPushButton(self)
        button.setFixedSize(_ACCENT_SWATCH_SIZE, _ACCENT_SWATCH_SIZE)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolTip(accent.value.capitalize())
        button.setAccessibleName(f"{accent.value} accent")
        # Default argument captures `accent` now; a bare closure would
        # see whatever the loop variable ends up as.
        button.clicked.connect(lambda _=False, a=accent: self._on_accent_selected(a))
        self._accent_buttons[accent] = button
        return button

    def _build_curve_section(self) -> QWidget:
        section = QWidget(self)
        layout = QVBoxLayout(section)
        layout.setContentsMargins(SPACE_MD, SPACE_MD, SPACE_MD, SPACE_SM)
        layout.setSpacing(SPACE_SM)

        self._curve = EqCurveWidget(self._model, self._theme.palette, self)
        layout.addWidget(self._curve, stretch=1)

        metrics = QHBoxLayout()
        metrics.setSpacing(SPACE_LG)
        hint = QLabel("Drag a handle · wheel for Q · double-click to flatten", self)
        hint.setObjectName("caption")
        metrics.addWidget(hint)
        metrics.addStretch(1)
        self._metrics_label = QLabel(self)
        self._metrics_label.setObjectName("metric")
        metrics.addWidget(self._metrics_label)
        layout.addLayout(metrics)
        return section

    def _wrap_in_card(self, content: QWidget) -> QFrame:
        card = QFrame(self)
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(content)
        return card

    # ── Theme ─────────────────────────────────────────────────────────
    def _apply_theme(self) -> None:
        self.setStyleSheet(self._theme.stylesheet())
        self._curve.set_palette(self._theme.palette)
        self._theme_button.setText("Light" if self._theme.mode is ThemeMode.DARK else "Dark")
        self._show_backend_status(self._backend_status)  # its dot is palette-coloured
        # Swatches are painted directly, not themed by the stylesheet:
        # each shows the accent it selects, in the *current* mode's
        # variant, so what you see is exactly what you'd get.
        for accent, button in self._accent_buttons.items():
            colour = Theme(self._theme.mode, accent).palette.accent
            selected = accent is self._theme.accent
            border = self._theme.palette.text_primary if selected else "transparent"
            button.setStyleSheet(
                f"QPushButton {{ background-color: {colour};"
                f" border: 2px solid {border};"
                f" border-radius: {_ACCENT_SWATCH_SIZE // 2}px; }}"
            )

    def _on_toggle_theme(self) -> None:
        toggled = self._preferences.theme_mode.toggled()
        self._update_preferences(self._preferences.with_theme_mode(toggled))

    def _on_accent_selected(self, accent: AccentColor) -> None:
        self._update_preferences(self._preferences.with_accent(accent))

    def _update_preferences(self, preferences: Preferences) -> None:
        self._preferences = preferences
        self._theme = Theme(preferences.theme_mode, preferences.accent)
        self._apply_theme()
        self._preferences_store.save(preferences)

    # ── Presets ───────────────────────────────────────────────────────
    def _reload_preset_list(self) -> None:
        self._preset_box.clear()
        self._preset_box.addItem("Custom", userData=None)
        for stored in self._library.list_all():
            self._preset_box.addItem(stored.name, userData=stored.name)

    def _restore_last_preset(self) -> None:
        name = self._preferences.last_preset
        if name is None:
            return
        try:
            self._model.load(self._library.get(name).preset)
        except EqualizerError:
            # Deleted or renamed since last run — not worth interrupting
            # startup over; forget it and move on.
            self._update_preferences(self._preferences.with_last_preset(None))
            return
        index = self._preset_box.findData(name)
        if index >= 0:
            self._preset_box.setCurrentIndex(index)

    def _on_preset_selected(self, index: int) -> None:
        name = self._preset_box.itemData(index)
        if name is None:
            return
        self._model.load(self._library.get(name).preset)
        self._update_preferences(self._preferences.with_last_preset(name))

    def _on_save_preset(self) -> None:
        name, accepted = QInputDialog.getText(self, "Save preset", "Preset name:")
        if not accepted or not name.strip():
            return
        try:
            self._library.save(name, self._model.to_preset(), overwrite=True)
        except EqualizerError as error:
            QMessageBox.warning(self, "Could not save preset", str(error))
            return
        self._reload_preset_list()
        index = self._preset_box.findData(name.strip())
        if index >= 0:
            self._preset_box.setCurrentIndex(index)
        self._update_preferences(self._preferences.with_last_preset(name.strip()))

    # ── Backend status ────────────────────────────────────────────────
    def _show_backend_status(self, status: BackendStatus) -> None:
        """One line telling the truth about where the audio actually is.

        A system-wide EQ that silently isn't running is worse than no EQ
        at all: the user turns knobs, hears nothing change, and blames
        their ears. The dot's colour carries the state at a glance and
        the text carries what to do about it.
        """
        self._backend_status = status
        dot = {
            BackendState.ACTIVE: self._theme.palette.accent,
            BackendState.READY: self._theme.palette.text_secondary,
            BackendState.UNAVAILABLE: self._theme.palette.text_tertiary,
            BackendState.ERROR: "#ff453a",
        }[status.state]
        self._status_label.setText(f'<span style="color:{dot}">●</span> {status.detail}')
        self._status_label.setToolTip(status.detail)

    # ── Devices & profiles ────────────────────────────────────────────
    def _on_device_changed(self, device: AudioDevice | None) -> None:
        """The user switched headphones — follow them.

        Only a *bound* device changes the EQ. Someone who has never made
        a profile plugs in a monitor and their curve stays exactly where
        they left it; someone who bound their Sundara gets their Harman
        curve back without touching anything. Automatic behaviour has to
        be earned by an explicit decision, or it's just surprise.
        """
        self._show_device(device)
        if device is None:
            return
        preset = self._profile_manager.preset_for(device)
        if preset is not None:
            self._model.load(preset)  # -> BackendController applies it

    def _show_device(self, device: AudioDevice | None) -> None:
        self._link_button.setEnabled(device is not None)
        if device is None:
            self._device_label.setText("No audio output")
            self._link_button.setText("Link to device")
            return

        profile = self._profile_manager.profile_for(device)
        text = f"Output: {device.name}"
        if profile is not None:
            text += f"  ·  auto: {profile.preset_name}"

        # The warning that saves a support ticket: APO is installed per
        # device, so the EQ can be "on" and still do nothing here.
        if self._apo_support_check(device.id) is False:
            text += "  ·  ⚠ Equalizer APO is not installed on this device"

        self._device_label.setText(text)
        self._device_label.setToolTip(text)
        self._link_button.setText("Unlink" if profile else "Link to device")

    def _on_link_clicked(self) -> None:
        device = self._device_controller.current_device
        if device is None:
            return
        if self._profile_manager.profile_for(device) is not None:
            self._profile_manager.unbind(device)
            self._show_device(device)
            return

        preset_name = self._preset_box.currentData()
        if preset_name is None:
            # Nothing to bind: a profile stores a preset *name*, and the
            # live curve doesn't have one until it's saved.
            QMessageBox.information(
                self,
                "Save the preset first",
                "Device profiles remember a preset by name. Save this curve with "
                "“Save as…”, then link it to this device.",
            )
            return
        try:
            self._profile_manager.bind(device, preset_name)
        except EqualizerError as error:
            QMessageBox.warning(self, "Could not link the preset", str(error))
            return
        self._show_device(device)

    # ── Power & metrics ───────────────────────────────────────────────
    def _on_power_toggled(self, checked: bool) -> None:
        self._model.set_powered(checked)
        self._power_button.setText("EQ ON" if checked else "EQ OFF")

    def _update_metrics(self) -> None:
        """The honest numbers: peak gain and the preamp the engine will
        actually apply. Text rather than folded into the curve, so the
        curve stays a readable picture of the filtering itself."""
        preset = self._model.effective_preset()
        peak = preset.peak_response_db(DEFAULT_SAMPLE_RATE_HZ)
        preamp = preset.safe_preamp_db(DEFAULT_SAMPLE_RATE_HZ)
        self._metrics_label.setText(f"peak {peak:+.1f} dB   ·   auto preamp {preamp:+.2f} dB")
