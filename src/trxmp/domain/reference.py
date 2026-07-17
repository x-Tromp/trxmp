"""The music/audio knowledge base's domain models.

Two value objects, each earning its place the same way the equalizer's
own guardrails eventually had to (see the note atop ``equalizer.py``):
by being something a real tool can stand behind, not "seemed reasonable
at the time".

**FrequencyBand** — the classic sub-bass/bass/mids/presence/air
vocabulary every mixing engineer already uses. This isn't invented; it's
textbook terminology (the edges vary a little between sources, but not
by much), which is exactly why it's trustworthy content to ship: nobody
is relying on Trxmp's *opinion* about where "presence" starts.

**HeadphoneModel** — correction curves ported *verbatim* from the
original Tauri/Rust prototype's ``apply_headphone_correction`` function.
They are not measurements Trxmp has taken; they're a small, honestly
labelled starting point (see ``is_measured`` and ``source``), continuing
a feature the original app already had rather than inventing a new one
from nothing. A ``HeadphoneModel``'s bands are ordinary
:class:`~trxmp.domain.equalizer.EqBand` objects — reused, not
reinvented, so a correction curve is exactly as valid (and exactly as
safe) as any preset a user builds by hand.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from trxmp.domain.equalizer import EqBand
from trxmp.domain.errors import InvalidReferenceDataError

MAX_NAME_LENGTH = 100


@dataclass(frozen=True, slots=True)
class FrequencyBand:
    """A named region of the audible spectrum and what it's known for."""

    name: str
    low_hz: float
    high_hz: float
    description: str

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise InvalidReferenceDataError("frequency band name cannot be empty")
        if not (0.0 < self.low_hz < self.high_hz):
            raise InvalidReferenceDataError(
                f"frequency band {self.name!r} has a nonsensical range "
                f"[{self.low_hz}, {self.high_hz}] Hz"
            )

    def contains(self, frequency_hz: float) -> bool:
        return self.low_hz <= frequency_hz < self.high_hz


class HeadphoneCategory(StrEnum):
    DYNAMIC = "dynamic"
    PLANAR = "planar"
    ELECTROSTATIC = "electrostatic"
    WIRELESS = "wireless"
    IEM = "iem"


@dataclass(frozen=True, slots=True)
class HeadphoneModel:
    """A headphone and a suggested correction curve for it.

    ``correction`` is deliberately a *suggestion*, not a preset the app
    applies on its own initiative — see
    ``application.reference.ReferenceCatalog`` and the UI's headphone
    picker, which only loads it when the user explicitly asks.
    """

    id: str
    name: str
    manufacturer: str
    category: HeadphoneCategory
    correction: tuple[EqBand, ...]
    notes: str = ""
    is_measured: bool = False
    source: str = ""

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise InvalidReferenceDataError("headphone id cannot be empty")
        if not self.name.strip():
            raise InvalidReferenceDataError("headphone name cannot be empty")
        if len(self.name) > MAX_NAME_LENGTH:
            raise InvalidReferenceDataError(
                f"headphone name is {len(self.name)} characters; max is {MAX_NAME_LENGTH}"
            )
