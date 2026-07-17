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
