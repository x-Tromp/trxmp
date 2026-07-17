"""The main window — composes the shell, owns the theme, wires the parts.

Everything it needs arrives through its constructor (the preset library,
the preferences store). It never constructs a repository or reaches for
a file path: that's ``app.py``'s job. This is what makes the window
testable with fakes, and it's why the architecture test can forbid
``trxmp.ui`` from importing ``trxmp.infrastructure`` at all.
"""

from __future__ import annotations

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

from trxmp.application.eq_analysis import DEFAULT_SAMPLE_RATE_HZ
from trxmp.application.preferences import AccentColor, Preferences, PreferencesStore, ThemeMode
from trxmp.application.preset_library import PresetLibrary
from trxmp.domain.errors import EqualizerError
from trxmp.ui.theme import SPACE_LG, SPACE_MD, SPACE_SM, Theme
from trxmp.ui.view_models import EqViewModel
from trxmp.ui.widgets.band_controls import BandControls
from trxmp.ui.widgets.eq_curve import EqCurveWidget

_ACCENT_SWATCH_SIZE = 14


class MainWindow(QMainWindow):
    def __init__(
        self,
        library: PresetLibrary,
        preferences_store: PreferencesStore,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._library = library
        self._preferences_store = preferences_store
        self._preferences = preferences_store.load()
        self._theme = Theme(self._preferences.theme_mode, self._preferences.accent)
        self._model = EqViewModel()
        self._accent_buttons: dict[AccentColor, QPushButton] = {}

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
