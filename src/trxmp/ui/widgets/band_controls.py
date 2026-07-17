"""Vertical gain sliders — one per band, plus the preamp.

Bound to the same :class:`EqViewModel` as the curve, so the two stay in
sync with no code connecting them to each other.

The slider bank is rebuilt whenever a preset is *loaded*, because a
loaded preset may have any number of bands (an imported AutoEQ profile
has as many as it has). Building the sliders once at construction and
assuming they'd always match was a real bug the tests caught: load a
one-band preset into a ten-slider panel and it blows up. Hence two
distinct signals — ``preset_loaded`` means "the structure changed,
rebuild", ``bands_changed`` means "the values moved, refresh".

The one Qt wrinkle worth knowing: ``QSlider`` is integer-only. Gains are
floats in dB, so every slider works in tenths of a dB internally
(``-180..120`` means -18.0..+12.0 dB) and converts at the boundary.
Scaling like this is the standard workaround; the alternative (a custom
float slider) is a lot of code for no user-visible gain.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from trxmp.domain.equalizer import MAX_BOOST_DB, MAX_CUT_DB, MAX_PREAMP_DB, MIN_PREAMP_DB
from trxmp.ui.theme import SPACE_MD, SPACE_SM
from trxmp.ui.view_models import EqViewModel

# Sliders span exactly the domain's gain range — asymmetric (-18..+12)
# and slightly odd-looking, but truthful. A prettier symmetric range
# would silently clamp an imported -15 dB band to whatever the slider
# could show, displaying one number while the engine used another.
_SCALE = 10  # slider units per dB
_STEP_DB = 0.5


class _LabelledSlider(QWidget):
    """One vertical slider with its live value and its name underneath."""

    def __init__(
        self,
        label: str,
        minimum_db: float,
        maximum_db: float,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE_SM // 2)
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self.slider = QSlider(Qt.Orientation.Vertical, self)
        self.slider.setRange(int(minimum_db * _SCALE), int(maximum_db * _SCALE))
        self.slider.setSingleStep(int(_STEP_DB * _SCALE))
        self.slider.setPageStep(int(_STEP_DB * _SCALE * 2))
        self.slider.setMinimumHeight(120)
        self.slider.setAccessibleName(f"{label} gain")

        self.value_label = QLabel("0.0", self)
        self.value_label.setObjectName("metricValue")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.value_label.setMinimumWidth(38)

        self.name_label = QLabel(label, self)
        self.name_label.setObjectName("caption")
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        layout.addWidget(self.slider, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.value_label)
        layout.addWidget(self.name_label)

    def set_display(self, value_db: float, label: str) -> None:
        self.value_label.setText(f"{value_db:+.1f}" if value_db else "0.0")
        self.name_label.setText(label)


class BandControls(QWidget):
    """The slider bank: preamp, a separator, then one slider per band."""

    def __init__(self, model: EqViewModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model = model
        self._updating = False
        self._sliders: list[_LabelledSlider] = []

        layout = QHBoxLayout(self)
        layout.setContentsMargins(SPACE_MD, SPACE_MD, SPACE_MD, SPACE_MD)
        layout.setSpacing(SPACE_SM)

        self._preamp = _LabelledSlider("Pre", MIN_PREAMP_DB, MAX_PREAMP_DB, self)
        self._preamp.slider.valueChanged.connect(self._on_preamp_moved)
        layout.addWidget(self._preamp)

        separator = QFrame(self)
        separator.setObjectName("separator")
        separator.setFrameShape(QFrame.Shape.VLine)
        separator.setFixedWidth(1)
        layout.addWidget(separator)

        self._bands_layout = QHBoxLayout()
        self._bands_layout.setSpacing(SPACE_SM)
        # stretch=1 hands *all* the leftover width to the band group, so
        # the sliders spread evenly across it. Without it, a QHBoxLayout
        # splits the extra space equally between its two children — and
        # the preamp, being one item next to a ten-item group, would take
        # half the panel to itself.
        layout.addLayout(self._bands_layout, stretch=1)

        self._rebuild_sliders()
        model.preset_loaded.connect(self._rebuild_sliders)
        model.bands_changed.connect(self._sync_from_model)
        model.preamp_changed.connect(self._sync_preamp_from_model)
        model.powered_changed.connect(self._on_powered)
        self._sync_preamp_from_model(model.preamp_db)

    # ── Structure ─────────────────────────────────────────────────────
    def _rebuild_sliders(self) -> None:
        """Throw the slider bank away and build one that fits the preset."""
        for slider in self._sliders:
            self._bands_layout.removeWidget(slider)
            # deleteLater, not del: the widget may still be inside an
            # event being delivered. Qt frees it once that unwinds.
            slider.setParent(None)
            slider.deleteLater()
        self._sliders.clear()

        for index, band in enumerate(self._model.bands):
            slider = _LabelledSlider(_format_hz(band.frequency_hz), MAX_CUT_DB, MAX_BOOST_DB, self)
            # Late binding trap: `index` must be captured now via a
            # default argument. A bare closure over `index` would leave
            # every slider pointing at the last band.
            slider.slider.valueChanged.connect(lambda value, i=index: self._on_band_moved(i, value))
            self._bands_layout.addWidget(slider)
            self._sliders.append(slider)

        self._sync_from_model()
        self._on_powered(self._model.powered)

    # ── Model -> UI ───────────────────────────────────────────────────
    def _sync_from_model(self) -> None:
        """Push model state into the sliders without echoing back.

        The ``_updating`` guard breaks the feedback loop: setValue emits
        valueChanged, which would call back into the model, which would
        emit bands_changed, which would land here again. Every
        two-way-bound UI needs this guard somewhere; forgetting it is
        the classic infinite-loop bug.
        """
        self._updating = True
        try:
            for slider, band in zip(self._sliders, self._model.bands, strict=True):
                slider.slider.setValue(round(band.gain_db * _SCALE))
                # The label tracks the frequency live, so it stays true
                # when a band is dragged sideways on the curve.
                slider.set_display(band.gain_db, _format_hz(band.frequency_hz))
        finally:
            self._updating = False

    def _sync_preamp_from_model(self, preamp_db: float) -> None:
        self._updating = True
        try:
            self._preamp.slider.setValue(round(preamp_db * _SCALE))
            self._preamp.set_display(preamp_db, "Pre")
        finally:
            self._updating = False

    def _on_powered(self, powered: bool) -> None:
        for slider in (*self._sliders, self._preamp):
            slider.slider.setEnabled(powered)

    # ── UI -> model ───────────────────────────────────────────────────
    def _on_band_moved(self, index: int, value: int) -> None:
        if self._updating:
            return
        self._model.set_band_gain(index, value / _SCALE)

    def _on_preamp_moved(self, value: int) -> None:
        if self._updating:
            return
        self._model.set_preamp(value / _SCALE)


def _format_hz(frequency_hz: float) -> str:
    """Compact axis-style label: 250, 1k, 4.5k, 16k."""
    if frequency_hz < 1_000:
        return f"{frequency_hz:.0f}"
    khz = frequency_hz / 1000
    return f"{khz:.0f}k" if khz == int(khz) else f"{khz:.1f}k"
