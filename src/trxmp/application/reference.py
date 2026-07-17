"""Use cases for the bundled knowledge base.

Same shape as every other boundary in the app: a Protocol declared here,
a concrete adapter in infrastructure that parses the bundled data files,
wired at the composition root. The difference from
``PresetRepository``/``DeviceProfileRepository`` is that this data isn't
user-owned — it ships *with* Trxmp and nobody mutates it at runtime — so
there's no ``upsert``/``delete`` here, only reads.

Keeping it behind a Protocol anyway (rather than importing the YAML
loader straight into the UI) buys the same thing it always does: a test
can hand ``MainWindow`` a five-line in-memory catalog instead of parsing
real bundled files, and the UI stays ignorant of where the data actually
comes from.
"""

from __future__ import annotations

from typing import Protocol

from trxmp.domain.reference import FrequencyBand, HeadphoneModel


class ReferenceCatalog(Protocol):
    def list_headphones(self) -> list[HeadphoneModel]: ...

    def get_headphone(self, headphone_id: str) -> HeadphoneModel | None: ...

    def list_frequency_bands(self) -> list[FrequencyBand]: ...

    def describe_frequency(self, frequency_hz: float) -> FrequencyBand | None:
        """Which named region (sub-bass, presence, air, …) a frequency
        falls in, or None past the catalog's covered range."""
        ...
