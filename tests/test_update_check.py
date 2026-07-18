"""check_for_update — the orchestration, against a fake ReleaseSource."""

from __future__ import annotations

from trxmp.application.update_check import UpdateNotice, check_for_update

RELEASES_URL = "https://github.com/Equix/trxmp/releases"


class _FakeSource:
    def __init__(self, tag: str | None) -> None:
        self._tag = tag

    def latest_tag(self) -> str | None:
        return self._tag


def test_a_newer_release_produces_a_notice() -> None:
    notice = check_for_update("0.6.0", _FakeSource("v0.7.0"), RELEASES_URL)
    assert notice == UpdateNotice(version="0.7.0", url=RELEASES_URL)


def test_the_same_version_produces_no_notice() -> None:
    assert check_for_update("0.6.0", _FakeSource("v0.6.0"), RELEASES_URL) is None


def test_an_older_tag_produces_no_notice() -> None:
    """Can happen if someone re-runs an old tag's release workflow —
    must not tell a user on 0.7.0 to 'update' to 0.6.0."""
    assert check_for_update("0.7.0", _FakeSource("v0.6.0"), RELEASES_URL) is None


def test_a_source_that_cannot_answer_produces_no_notice() -> None:
    """Offline, rate-limited, GitHub down — the source reports None,
    never raises, and this must degrade the same way."""
    assert check_for_update("0.6.0", _FakeSource(None), RELEASES_URL) is None


def test_the_reported_version_strips_the_v_prefix() -> None:
    notice = check_for_update("0.6.0", _FakeSource("v1.0.0"), RELEASES_URL)
    assert notice is not None
    assert notice.version == "1.0.0"
