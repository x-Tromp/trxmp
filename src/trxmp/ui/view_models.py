"""The EQ view model — one source of truth for what's on screen.

Both the curve and the sliders bind to this object: each reads state
from it and writes user intent back into it, and the model announces
changes via Qt signals. Neither widget knows the other exists, yet drag
a handle on the curve and the matching slider moves. That's the whole
point of MVVM — the alternative (widgets calling each other's setters)
is how UIs rot into unmaintainable webs.

It lives in ``ui`` because ``QObject``/``Signal`` are Qt. It holds
*domain* objects (``EqBand``), not dicts — the UI speaks the same
language as the rest of the app, so there's no translation layer to
drift out of sync.

Design rule enforced here: **clamp at the UI, reject in the domain.**
The domain raises on an out-of-range band because that's a programming
error at that level. But a user dragging a handle past +9 dB isn't
making an error — they're expressing intent the UI should limit
gracefully. So every setter clamps to the domain's own published
constants, which means the domain's guardrails can never actually fire
from user input. Two layers, two jobs.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from trxmp.domain.equalizer import (
    MAX_BOOST_DB,
    MAX_CUT_DB,
    MAX_FREQUENCY_HZ,
    MAX_PREAMP_DB,
    MAX_Q,
    MIN_FREQUENCY_HZ,
    MIN_PREAMP_DB,
    MIN_Q,
    EqBand,
    EqPreset,
    default_graphic_preset,
)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


class EqViewModel(QObject):
    """Mutable EQ state for the session, built from immutable domain parts."""

    bands_changed = Signal()
    preamp_changed = Signal(float)
    powered_changed = Signal(bool)
    preset_loaded = Signal()

    def __init__(self, preset: EqPreset | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        preset = preset if preset is not None else default_graphic_preset()
        self._bands: list[EqBand] = list(preset.bands)
        self._preamp_db = preset.requested_preamp_db
        self._powered = True

    # ── Reading ───────────────────────────────────────────────────────
    @property
    def bands(self) -> tuple[EqBand, ...]:
        """A tuple, not the internal list: callers get a snapshot they
        cannot mutate behind the model's back."""
        return tuple(self._bands)

    @property
    def preamp_db(self) -> float:
        return self._preamp_db

    @property
    def powered(self) -> bool:
        return self._powered

    def to_preset(self) -> EqPreset:
        """The current state as a domain preset, ready to save or apply."""
        return EqPreset(bands=self.bands, requested_preamp_db=self._preamp_db)

    def effective_preset(self) -> EqPreset:
        """What the audio engine should actually run: bypass when off."""
        return self.to_preset() if self._powered else EqPreset.flat()

    # ── Writing ───────────────────────────────────────────────────────
    def set_powered(self, powered: bool) -> None:
        if powered != self._powered:
            self._powered = powered
            self.powered_changed.emit(powered)

    def set_band_gain(self, index: int, gain_db: float) -> None:
        self._replace_band(index, gain_db=_clamp(gain_db, MAX_CUT_DB, MAX_BOOST_DB))

    def set_band_frequency(self, index: int, frequency_hz: float) -> None:
        self._replace_band(
            index, frequency_hz=_clamp(frequency_hz, MIN_FREQUENCY_HZ, MAX_FREQUENCY_HZ)
        )

    def set_band_q(self, index: int, q: float) -> None:
        self._replace_band(index, q=_clamp(q, MIN_Q, MAX_Q))

    def set_preamp(self, preamp_db: float) -> None:
        preamp_db = _clamp(preamp_db, MIN_PREAMP_DB, MAX_PREAMP_DB)
        if preamp_db != self._preamp_db:
            self._preamp_db = preamp_db
            self.preamp_changed.emit(preamp_db)

    def load(self, preset: EqPreset) -> None:
        self._bands = list(preset.bands)
        self._preamp_db = preset.requested_preamp_db
        self.preset_loaded.emit()
        self.bands_changed.emit()
        self.preamp_changed.emit(self._preamp_db)

    def reset(self) -> None:
        self.load(default_graphic_preset())

    def _replace_band(self, index: int, **changes: float) -> None:
        """Bands are frozen, so 'editing' one means building a new one.

        Immutability costs an allocation here and buys the guarantee
        that nothing holding a reference to a band can be surprised by
        it changing underneath them.
        """
        current = self._bands[index]
        updated = EqBand(
            filter_type=current.filter_type,
            frequency_hz=changes.get("frequency_hz", current.frequency_hz),
            gain_db=changes.get("gain_db", current.gain_db),
            q=changes.get("q", current.q),
        )
        if updated != current:
            self._bands[index] = updated
            self.bands_changed.emit()
