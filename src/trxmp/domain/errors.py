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
