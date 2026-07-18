"""Comparing release version strings — for the update check, nothing else.

Deliberately forgiving rather than strict, the opposite instinct from
the rest of the domain layer (``equalizer.py``'s guardrails exist to
protect someone's ears and speakers; a wrong answer here just skips a
notification). A malformed or unexpected tag — a hand-pushed `latest`,
a pre-release suffix this app has never used, empty JSON — must never
be the thing that breaks startup, so "can't tell" always resolves to
"nothing to report" rather than raising.

Only ``MAJOR.MINOR.PATCH`` is understood, matching every tag this
project has actually used (``0.6.0`` through the version in
``trxmp/__init__.py``). No pre-release or build-metadata suffixes
(``-rc1``, ``+build5``) — not because they're wrong, but because
nothing here has ever needed them, and guessing at an ordering for
suffixes this project doesn't use would be exactly the kind of
unverified behaviour M6 already learned not to ship.
"""

from __future__ import annotations

import re

_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def parse_version(text: str) -> tuple[int, int, int] | None:
    """``"v0.7.0"`` or ``"0.7.0"`` -> ``(0, 7, 0)``. Anything else -> None."""
    match = _VERSION_RE.match(text.strip())
    if match is None:
        return None
    major, minor, patch = match.groups()
    return (int(major), int(minor), int(patch))


def is_newer(current: str, candidate: str) -> bool:
    """Is ``candidate`` a strictly newer release than ``current``?

    False for anything unparseable on either side — silence, not a
    guess, is the correct behaviour when the comparison can't be made
    honestly.
    """
    current_version = parse_version(current)
    candidate_version = parse_version(candidate)
    if current_version is None or candidate_version is None:
        return False
    return candidate_version > current_version
