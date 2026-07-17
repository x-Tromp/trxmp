"""Domain exceptions.

A small, flat hierarchy: callers that just want "the preset is bad"
catch :class:`EqualizerError`; callers that care which rule failed catch
the specific subclass. Messages carry the offending value *and* the
allowed range, because an error you can't act on is half an error.
"""


class EqualizerError(Exception):
    """Base class for all EQ domain rule violations."""


class InvalidBandError(EqualizerError):
    """A band parameter is outside the professional guardrails."""


class InvalidPresetError(EqualizerError):
    """A preset-level rule (band count, preamp range) was violated."""


class PresetNotFoundError(EqualizerError):
    """No preset with the requested name exists in the library."""


class DuplicatePresetError(EqualizerError):
    """A preset with this name already exists and overwrite wasn't requested."""


class InvalidDeviceError(EqualizerError):
    """An audio device or device profile is malformed."""


class DeviceNotFoundError(EqualizerError):
    """No audio device matched what was asked for."""


class PresetImportError(EqualizerError):
    """A preset file from another tool could not be imported faithfully.

    Raised only when importing anyway would produce audio that differs
    from what the file describes — an unrepresentable filter, or a value
    we would have to guess at. "We imported less than you asked for" is a
    warning, not this.
    """


class InvalidReferenceDataError(EqualizerError):
    """A frequency band or headphone entry in the knowledge base is
    malformed — should only ever fire against Trxmp's own bundled data,
    which is exactly why it's worth checking rather than assuming."""


class HeadphoneNotFoundError(EqualizerError):
    """No headphone in the catalog matched what was asked for."""
