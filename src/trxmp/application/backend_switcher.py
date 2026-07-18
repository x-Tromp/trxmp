"""Presents several :class:`AudioBackend` implementations as one.

The rest of the app — ``BackendController``, and everything upstream of
it — only ever needs to know about "the current backend", never which
Strategy is live. That's what lets this satisfy the ``AudioBackend``
Protocol itself (structurally; no inheritance needed) rather than
requiring every caller to learn a second interface. The UI layer is the
one exception that *does* need to know a switcher is a switcher — it's
the thing offering the picker — and it gets that by holding a reference
to this concrete class rather than the bare Protocol.
"""

from __future__ import annotations

from trxmp.application.audio_backend import AudioBackend, BackendStatus
from trxmp.domain.equalizer import EqPreset


class BackendSwitcher:
    def __init__(self, backends: dict[str, AudioBackend], initial: str) -> None:
        if not backends:
            raise ValueError("BackendSwitcher needs at least one backend")
        if initial not in backends:
            raise ValueError(f"unknown backend: {initial!r}")
        self._backends = backends
        self._current_name = initial

    @property
    def available_names(self) -> list[str]:
        return list(self._backends)

    @property
    def current_name(self) -> str:
        return self._current_name

    @property
    def name(self) -> str:
        return self._backends[self._current_name].name

    @property
    def status(self) -> BackendStatus:
        return self._backends[self._current_name].status

    def apply(self, preset: EqPreset) -> None:
        self._backends[self._current_name].apply(preset)

    def disable(self) -> None:
        self._backends[self._current_name].disable()

    def select(self, name: str) -> None:
        """Make ``name`` the current backend.

        Disables the outgoing one first — never leaves two backends
        live at once, which for a pair like Equalizer APO + Lab mode
        would mean two independent EQ curves both touching the same
        audio. This does *not* re-apply the current preset to the new
        backend; that's the caller's job (typically forcing the
        BackendController that owns the model to resync), since this
        class knows nothing about the model or any preset.
        """
        if name == self._current_name:
            return
        if name not in self._backends:
            raise ValueError(f"unknown backend: {name!r}")
        self._backends[self._current_name].disable()
        self._current_name = name
