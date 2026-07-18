"""Checking whether a newer release exists — the use case, not the HTTP.

Same split as every other capability in this app: a Protocol here that
names what's needed, an adapter in ``infrastructure`` that actually
makes a network call. ``ReleaseSource.latest_tag`` mirrors
``PreferencesStore.load`` in spirit — it must never raise. A machine
that's offline, behind a proxy, or simply doesn't have GitHub reachable
right now is not an error state for an app whose entire purpose is
equalizing audio; it's just "no update to report."
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from trxmp.domain.version import is_newer


class ReleaseSource(Protocol):
    def latest_tag(self) -> str | None:
        """The newest release's tag (e.g. ``"v0.7.0"``), or None if it
        couldn't be determined — never raises."""
        ...


@dataclass(frozen=True, slots=True)
class UpdateNotice:
    """What to tell the user: a version, and where to get it."""

    version: str
    url: str


def check_for_update(
    current_version: str, source: ReleaseSource, releases_url: str
) -> UpdateNotice | None:
    tag = source.latest_tag()
    if tag is None or not is_newer(current_version, tag):
        return None
    return UpdateNotice(version=tag.removeprefix("v"), url=releases_url)
