"""The main window — composes the shell, owns the theme, wires the parts.

Everything it needs arrives through its constructor (the preset library,
the preferences store). It never constructs a repository or reaches for
a file path: that's ``app.py``'s job. This is what makes the window
testable with fakes, and it's why the architecture test can forbid
``trxmp.ui`` from importing ``trxmp.infrastructure`` at all.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from trxmp import __version__
from trxmp.application.audio_backend import AudioBackend, BackendState, BackendStatus
from trxmp.application.backend_switcher import BackendSwitcher
from trxmp.application.capture import AudioCaptureSource
from trxmp.application.devices import AudioDeviceService, ProfileManager
from trxmp.application.eq_analysis import DEFAULT_SAMPLE_RATE_HZ
from trxmp.application.preferences import AccentColor, Preferences, PreferencesStore, ThemeMode
from trxmp.application.preset_library import PresetLibrary
from trxmp.application.reference import ReferenceCatalog
from trxmp.application.update_check import ReleaseSource, UpdateNotice
from trxmp.domain.devices import AudioDevice
from trxmp.domain.equalizer import EqPreset
from trxmp.domain.errors import EqualizerError
from trxmp.ui.backend_controller import BackendController
from trxmp.ui.device_controller import DeviceController
from trxmp.ui.spectrum_controller import SpectrumController
from trxmp.ui.theme import SPACE_LG, SPACE_MD, SPACE_SM, SPACE_XL, SPACE_XS, Theme
from trxmp.ui.update_controller import UpdateController
from trxmp.ui.view_models import EqViewModel
from trxmp.ui.widgets.band_controls import BandControls
from trxmp.ui.widgets.eliding_label import ElidingLabel
from trxmp.ui.widgets.eq_curve import EqCurveWidget
from trxmp.ui.widgets.status_dot import StatusDot

_ACCENT_SWATCH_SIZE = 16

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
        capture_source: AudioCaptureSource | None = None,
        reference_catalog: ReferenceCatalog | None = None,
        update_source: ReleaseSource | None = None,
        releases_url: str | None = None,
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
        # Optional, like the capture source: a knowledge base is a real
        # feature, not a requirement for the EQ underneath it to work.
        self._reference_catalog = reference_catalog
        self._accent_buttons: dict[AccentColor, QPushButton] = {}
        # Kept so a theme change can re-render the status line in the new
        # palette without asking the backend again (which touches disk).
        self._backend_status = BackendStatus(BackendState.READY, "")
        # A plain AudioBackend (tests, or a future single-backend build)
        # has no notion of "which one" — the picker only appears when
        # there's actually something to pick between. Detected by type
        # rather than a separate constructor flag: a switcher already
        # satisfies AudioBackend structurally, so the same `backend`
        # argument serves both cases.
        self._backend_switcher = backend if isinstance(backend, BackendSwitcher) else None
        if self._backend_switcher is not None:
            wanted = self._preferences.backend_name
            if wanted is not None and wanted in self._backend_switcher.available_names:
                self._backend_switcher.select(wanted)
        # Populated by _wrap_in_card; refreshed on every theme change
        # since light and dark need very different shadow strengths.
        self._card_shadows: list[QGraphicsDropShadowEffect] = []

        self.setWindowTitle("Trxmp")
        self.resize(1000, 700)
        self.setMinimumSize(820, 560)

        self._build_ui()
        self._apply_theme()
        self._reload_preset_list()
        self._restore_last_preset()
        if self._reference_catalog is not None:
            self._reload_headphone_list()
        if self._backend_switcher is not None:
            self._reload_backend_list()

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

        # The analyzer is optional equipment: no capture source (tests,
        # unsupported platforms) simply means no spectrum button.
        self._spectrum_controller: SpectrumController | None = None
        if capture_source is not None:
            self._spectrum_controller = SpectrumController(capture_source, parent=self)
            self._spectrum_controller.spectrum_changed.connect(self._curve.set_spectrum)
            self._spectrum_button.setVisible(True)
            if self._preferences.show_spectrum:
                self._set_spectrum_enabled(True)

        # Same optionality once more: no source (tests, no network-check
        # wired up yet) means the button simply never appears.
        self._update_notice: UpdateNotice | None = None
        if update_source is not None and releases_url is not None:
            update_controller = UpdateController(
                __version__, update_source, releases_url, parent=self
            )
            update_controller.update_available.connect(self._on_update_available)
            update_controller.start()

    # ── Construction ──────────────────────────────────────────────────
    def _build_ui(self) -> None:
        central = QWidget(self)
        root = QVBoxLayout(central)
        # Generous outer margins are most of what makes a window feel
        # designed rather than filled to the edges — the single biggest
        # lever for an "airy" look, and the cheapest to pull.
        root.setContentsMargins(SPACE_XL, SPACE_XL, SPACE_XL, SPACE_XL)
        root.setSpacing(SPACE_LG)

        root.addLayout(self._build_header())
        root.addWidget(self._wrap_in_card(self._build_curve_section()), stretch=1)
        root.addWidget(self._wrap_in_card(BandControls(self._model, self)))
        self.setCentralWidget(central)

    def _build_header(self) -> QVBoxLayout:
        """Two rows, not one.

        The original single-row header was the source of a real bug: nine
        interactive elements and a status line competed for one strip of
        window width, and on a normal-sized window the device line simply
        ran out of room and got clipped mid-word. Splitting brand+status
        from preset+appearance controls isn't just prettier — it's what
        gives the status column enough width that eliding becomes the
        rare fallback instead of the everyday reality.
        """
        header = QVBoxLayout()
        header.setSpacing(SPACE_SM)
        header.addLayout(self._build_header_status_row())
        header.addLayout(self._build_header_controls_row())
        return header

    def _build_header_status_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(SPACE_MD)

        brand = QLabel("Trxmp", self)
        brand.setObjectName("brand")
        row.addWidget(brand)

        # A layout added with a stretch factor grows its *box*, but
        # left-aligned content inside that box stays put at the box's
        # left edge — it does not migrate toward the box's right edge.
        # To pin the status column against the window's right margin,
        # the stretch has to be the empty space *before* it, not a
        # stretch factor on the column itself. (First attempt at this
        # got it backwards and the status dot ended up floating in the
        # middle of the header — this comment is here so that mistake
        # doesn't get quietly reintroduced.)
        row.addStretch(1)

        status_column = QVBoxLayout()
        status_column.setSpacing(3)

        # The dot needs to sit immediately next to the status text, not
        # merely somewhere on the same row — and a bare QHBoxLayout added
        # to status_column would stretch to the column's full width
        # (which the longer device line below dictates), leaving the dot
        # stranded at the far left of that width with the right-aligned
        # text nowhere near it. Wrapping the pair in its own QWidget and
        # adding *that* with an alignment lets it keep its natural,
        # compact size and sit as one right-aligned unit instead.
        status_line_widget = QWidget(self)
        status_line = QHBoxLayout(status_line_widget)
        status_line.setContentsMargins(0, 0, 0, 0)
        status_line.setSpacing(SPACE_XS)
        self._status_dot = StatusDot(self)
        self._status_label = ElidingLabel(self)
        self._status_label.setObjectName("caption")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        status_line.addWidget(self._status_dot, alignment=Qt.AlignmentFlag.AlignVCenter)
        status_line.addWidget(self._status_label)
        status_column.addWidget(status_line_widget, alignment=Qt.AlignmentFlag.AlignRight)

        self._device_label = ElidingLabel(self)
        self._device_label.setObjectName("caption")
        self._device_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        status_column.addWidget(self._device_label)

        # This column used to share a row with every button in the
        # header; on its own row, flush against the margin, it gets
        # most of the window's width — which is what actually fixes the
        # truncation. ElidingLabel is only the safety net for whatever
        # is left over on a genuinely narrow window.
        row.addLayout(status_column)
        return row

    def _build_header_controls_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(SPACE_SM)

        self._preset_box = QComboBox(self)
        self._preset_box.setAccessibleName("Preset")
        self._preset_box.activated.connect(self._on_preset_selected)
        row.addWidget(self._preset_box)

        # Only shown when a catalog was actually supplied — a knowledge
        # base is a real feature, not a requirement for the EQ to work,
        # the same optionality pattern as the spectrum button.
        self._headphone_box = QComboBox(self)
        self._headphone_box.setAccessibleName("Headphone")
        self._headphone_box.setPlaceholderText("Headphone…")
        self._headphone_box.setVisible(False)
        self._headphone_box.activated.connect(self._on_headphone_selected)
        row.addWidget(self._headphone_box)

        save_button = QPushButton("Save as…", self)
        save_button.clicked.connect(self._on_save_preset)
        row.addWidget(save_button)

        reset_button = QPushButton("Reset", self)
        reset_button.setObjectName("ghost")
        reset_button.clicked.connect(self._model.reset)
        row.addWidget(reset_button)

        self._link_button = QPushButton("Link to device", self)
        self._link_button.clicked.connect(self._on_link_clicked)
        row.addWidget(self._link_button)

        row.addStretch(1)

        # Tight spacing within the swatch group, loose spacing around
        # it: that contrast is what reads as "these six belong together"
        # without drawing a box around them.
        swatches = QHBoxLayout()
        swatches.setSpacing(SPACE_XS)
        for accent in AccentColor:
            swatches.addWidget(self._build_accent_swatch(accent))
        row.addLayout(swatches)
        row.addSpacing(SPACE_MD)

        self._spectrum_button = QPushButton("Spectrum", self)
        self._spectrum_button.setObjectName("ghost")
        self._spectrum_button.setCheckable(True)
        self._spectrum_button.setVisible(False)  # shown when a capture source exists
        self._spectrum_button.toggled.connect(self._on_spectrum_toggled)
        row.addWidget(self._spectrum_button)

        # Same optionality pattern as the spectrum button and headphone
        # picker: only shown when the composition root actually handed
        # us something to switch between.
        self._backend_box = QComboBox(self)
        self._backend_box.setAccessibleName("Audio backend")
        self._backend_box.setVisible(False)
        self._backend_box.activated.connect(self._on_backend_selected)
        row.addWidget(self._backend_box)

        # Invisible until (if ever) the background check actually finds
        # something — most launches, most of the time, this never
        # appears at all.
        self._update_button = QPushButton(self)
        self._update_button.setObjectName("ghost")
        self._update_button.setVisible(False)
        self._update_button.clicked.connect(self._on_update_clicked)
        row.addWidget(self._update_button)

        self._theme_button = QPushButton(self)
        self._theme_button.setObjectName("ghost")
        self._theme_button.setFixedWidth(64)
        self._theme_button.clicked.connect(self._on_toggle_theme)
        row.addWidget(self._theme_button)

        row.addSpacing(SPACE_SM)

        self._power_button = QPushButton("EQ ON", self)
        self._power_button.setObjectName("primary")
        self._power_button.setCheckable(True)
        self._power_button.setChecked(True)
        self._power_button.setFixedWidth(92)
        self._power_button.toggled.connect(self._on_power_toggled)
        row.addWidget(self._power_button)
        return row

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

        # A soft, low drop shadow instead of a harder border is most of
        # what makes a flat-coloured panel read as a card "resting" on
        # the window rather than a rectangle painted onto it — the same
        # trick macOS uses for its own panels. QSS has no box-shadow
        # property, so this is a real QGraphicsEffect, not a stylesheet
        # rule; _refresh_card_shadows keeps its strength correct across
        # theme changes.
        effect = QGraphicsDropShadowEffect(card)
        effect.setBlurRadius(28)
        effect.setOffset(0, 8)
        card.setGraphicsEffect(effect)
        self._card_shadows.append(effect)
        return card

    def _refresh_card_shadows(self) -> None:
        color_hex, alpha = self._theme.shadow
        color = QColor(color_hex)
        color.setAlpha(alpha)
        for effect in self._card_shadows:
            effect.setColor(color)

    # ── Theme ─────────────────────────────────────────────────────────
    def _apply_theme(self) -> None:
        self.setStyleSheet(self._theme.stylesheet())
        self._curve.set_palette(self._theme.palette)
        self._theme_button.setText("Light" if self._theme.mode is ThemeMode.DARK else "Dark")
        self._show_backend_status(self._backend_status)  # its dot is palette-coloured
        self._refresh_card_shadows()
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

    # ── Headphone knowledge base ─────────────────────────────────────
    def _reload_headphone_list(self) -> None:
        """Populate the headphone picker and reveal it.

        Called once at startup, guarded by the catalog actually being
        present — the same "optional equipment" shape as the spectrum
        button, so a test or a future non-Windows build that has no
        catalog wired up simply doesn't show this control at all.
        """
        assert self._reference_catalog is not None
        self._headphone_box.clear()
        self._headphone_box.setCurrentIndex(-1)  # show the placeholder, not headphone 0
        for headphone in self._reference_catalog.list_headphones():
            self._headphone_box.addItem(headphone.name, userData=headphone.id)
        self._headphone_box.setVisible(True)

    def _on_headphone_selected(self, index: int) -> None:
        """Load a headphone's correction curve as the current preset.

        A deliberate replace, not a merge onto whatever's already on the
        curve: repeatedly picking headphones (or picking one, tweaking
        it, then picking another) must not silently accumulate bands
        from every previous choice. The same one-shot "load a starting
        point" behaviour the preset picker already has.
        """
        if self._reference_catalog is None:
            return
        headphone_id = self._headphone_box.itemData(index)
        headphone = self._reference_catalog.get_headphone(headphone_id)
        if headphone is None:
            return
        self._model.load(EqPreset(bands=headphone.correction))

    # ── Audio backend ─────────────────────────────────────────────────
    def _reload_backend_list(self) -> None:
        assert self._backend_switcher is not None
        self._backend_box.clear()
        for name in self._backend_switcher.available_names:
            self._backend_box.addItem(name, userData=name)
        index = self._backend_box.findData(self._backend_switcher.current_name)
        if index >= 0:
            self._backend_box.setCurrentIndex(index)
        self._backend_box.setVisible(True)

    def _on_backend_selected(self, index: int) -> None:
        """Switch which Strategy is live.

        ``resync`` rather than waiting for the next edit: whatever curve
        is already on screen must reach the newly active backend right
        away, even if the user hasn't touched a slider since opening the
        app — otherwise picking Lab mode would silently do nothing until
        the next drag.
        """
        if self._backend_switcher is None:
            return
        name = self._backend_box.itemData(index)
        if name == self._backend_switcher.current_name:
            return
        self._backend_switcher.select(name)
        self._backend_controller.resync()
        self._update_preferences(self._preferences.with_backend_name(name))

    # ── Update check ──────────────────────────────────────────────────
    def _on_update_available(self, notice: UpdateNotice) -> None:
        self._update_notice = notice
        self._update_button.setText(f"Update to {notice.version}")
        self._update_button.setToolTip(notice.url)
        self._update_button.setVisible(True)

    def _on_update_clicked(self) -> None:
        if self._update_notice is not None:
            QDesktopServices.openUrl(QUrl(self._update_notice.url))

    # ── Backend status ────────────────────────────────────────────────
    def _show_backend_status(self, status: BackendStatus) -> None:
        """One line telling the truth about where the audio actually is.

        A system-wide EQ that silently isn't running is worse than no EQ
        at all: the user turns knobs, hears nothing change, and blames
        their ears. The dot's colour carries the state at a glance and
        the text carries what to do about it.
        """
        self._backend_status = status
        dot_color = {
            BackendState.ACTIVE: self._theme.palette.accent,
            BackendState.READY: self._theme.palette.text_secondary,
            BackendState.UNAVAILABLE: self._theme.palette.text_tertiary,
            BackendState.ERROR: "#ff453a",
        }[status.state]
        self._status_dot.set_color(dot_color)
        self._status_label.setText(status.detail)
        self._status_label.setToolTip(status.detail)

    # ── Spectrum analyzer ─────────────────────────────────────────────
    def _set_spectrum_enabled(self, enabled: bool) -> None:
        """One path for both the button and startup restore. The guard
        against re-entry matters: setChecked fires toggled, which lands
        back here — the same feedback shape as the sliders' _updating."""
        if self._spectrum_controller is None:
            return
        if self._spectrum_button.isChecked() != enabled:
            self._spectrum_button.setChecked(enabled)  # re-enters; state settles below
            return
        if enabled:
            if not self._spectrum_controller.start():
                # The OS refused the loopback (no driver, exotic device).
                # Un-check quietly; the tooltip explains on hover.
                self._spectrum_button.setChecked(False)
                self._spectrum_button.setToolTip("Could not open loopback capture")
                return
        else:
            self._spectrum_controller.stop()
        if self._preferences.show_spectrum != enabled:
            self._update_preferences(self._preferences.with_show_spectrum(enabled))

    def _on_spectrum_toggled(self, checked: bool) -> None:
        self._set_spectrum_enabled(checked)

    def closeEvent(self, event: object) -> None:
        """The capture owns an OS audio stream and a callback thread;
        Qt's parent-child teardown knows nothing about either."""
        if self._spectrum_controller is not None:
            self._spectrum_controller.stop()
        super().closeEvent(event)  # type: ignore[arg-type]

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
        if self._spectrum_controller is not None:
            # The loopback stream we hold belongs to the *old* device.
            self._spectrum_controller.restart_capture()
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
