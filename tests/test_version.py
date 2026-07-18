"""Version-string comparison — forgiving by design, never raising."""

from __future__ import annotations

import pytest

from trxmp.domain.version import is_newer, parse_version


class TestParseVersion:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("0.6.0", (0, 6, 0)),
            ("v0.6.0", (0, 6, 0)),
            ("1.20.3", (1, 20, 3)),
            ("  v2.0.0  ", (2, 0, 0)),
        ],
    )
    def test_parses_the_shapes_this_project_actually_uses(
        self, text: str, expected: tuple[int, int, int]
    ) -> None:
        assert parse_version(text) == expected

    @pytest.mark.parametrize("text", ["latest", "v1.2", "1.2.3-rc1", "1.2.3.4", "", "vX.Y.Z"])
    def test_anything_else_is_none_not_an_exception(self, text: str) -> None:
        assert parse_version(text) is None


class TestIsNewer:
    def test_a_higher_patch_is_newer(self) -> None:
        assert is_newer("0.6.0", "0.6.1") is True

    def test_a_higher_minor_is_newer(self) -> None:
        assert is_newer("0.6.9", "0.7.0") is True

    def test_a_higher_major_is_newer(self) -> None:
        assert is_newer("0.9.9", "1.0.0") is True

    def test_the_same_version_is_not_newer(self) -> None:
        assert is_newer("0.6.0", "0.6.0") is False

    def test_an_older_version_is_not_newer(self) -> None:
        assert is_newer("0.7.0", "0.6.0") is False

    def test_an_unparseable_candidate_is_never_newer(self) -> None:
        """The whole point: a hand-pushed 'latest' tag or a scheme this
        app has never used must not be mistaken for an update."""
        assert is_newer("0.6.0", "latest") is False

    def test_an_unparseable_current_version_is_never_newer(self) -> None:
        assert is_newer("not-a-version", "0.7.0") is False
