"""The audio backend abstraction — how a preset reaches your speakers.

This is the Strategy interface promised at the start of the project.
Windows only allows zero-latency system-wide processing inside its own
audio engine (APO drivers, written in C/C++), so Trxmp ships two very
different implementations behind this one door:

- ``EqualizerApoBackend`` (M4): writes config files that Equalizer APO
  executes inside the Windows audio engine. Zero added latency, applies
  to every app on the system.
- The Lab-mode pipeline (M8): captures, filters in NumPy, and renders
  back. ~50 ms of latency, but it's *our* DSP running end to end.

Everything above this line — the UI, the view model, the preset library
— talks only to this Protocol and cannot tell the two apart. That's the
whole point: swapping the engine under a running app is a constructor
argument, not a rewrite.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from trxmp.domain.equalizer import EqPreset


class BackendError(Exception):
    """The backend could not do what was asked (missing install, no
    permission, disk full). Never a reason to crash the app — the UI is
    expected to catch this and show the message."""


class BackendState(StrEnum):
    UNAVAILABLE = "unavailable"  # not installed / not usable on this machine
    READY = "ready"  # usable, but not currently driving the audio
    ACTIVE = "active"  # our EQ is live
    ERROR = "error"  # tried and failed; `detail` says why


@dataclass(frozen=True, slots=True)
class BackendStatus:
    """What the backend is doing, and a sentence a human can act on.

    ``detail`` is deliberately user-facing prose rather than an error
    code: "Equalizer APO is not installed" tells someone what to do,
    ``ERR_NO_APO`` does not.
    """

    state: BackendState
    detail: str

    @property
    def is_usable(self) -> bool:
        return self.state in (BackendState.READY, BackendState.ACTIVE)


class AudioBackend(Protocol):
    """What the app needs from an audio engine — nothing more."""

    @property
    def name(self) -> str: ...

    @property
    def status(self) -> BackendStatus: ...

    def apply(self, preset: EqPreset) -> None:
        """Make ``preset`` the live EQ. Raises :class:`BackendError`."""
        ...

    def disable(self) -> None:
        """Pass audio through untouched, leaving the backend wired up."""
        ...
