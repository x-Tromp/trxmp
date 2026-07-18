"""GitHubReleaseSource tests — HTTP mocked out entirely.

This is the one place in the app that touches the network, which makes
it the one place that most needs proving it degrades instead of
crashing: offline, rate-limited, a malformed body, GitHub itself being
down — none of them may raise past this class.
"""

from __future__ import annotations

import json

import pytest

from trxmp.infrastructure.github_releases import GitHubReleaseSource


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def _patch_urlopen(monkeypatch: pytest.MonkeyPatch, result: bytes | Exception) -> None:
    def fake_urlopen(request: object, timeout: float) -> _FakeResponse:
        if isinstance(result, Exception):
            raise result
        return _FakeResponse(result)

    monkeypatch.setattr("trxmp.infrastructure.github_releases.urllib.request.urlopen", fake_urlopen)


def test_returns_the_tag_from_a_successful_response(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_urlopen(monkeypatch, json.dumps({"tag_name": "v0.7.0"}).encode())
    assert GitHubReleaseSource("Equix", "trxmp").latest_tag() == "v0.7.0"


def test_a_network_error_returns_none_not_an_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_urlopen(monkeypatch, OSError("no network"))
    assert GitHubReleaseSource("Equix", "trxmp").latest_tag() is None


def test_malformed_json_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_urlopen(monkeypatch, b"not json")
    assert GitHubReleaseSource("Equix", "trxmp").latest_tag() is None


def test_a_response_missing_tag_name_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_urlopen(monkeypatch, json.dumps({"no_tag_here": True}).encode())
    assert GitHubReleaseSource("Equix", "trxmp").latest_tag() is None


def test_a_non_string_tag_name_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_urlopen(monkeypatch, json.dumps({"tag_name": 42}).encode())
    assert GitHubReleaseSource("Equix", "trxmp").latest_tag() is None


def test_the_request_targets_the_right_repo_and_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[object] = []

    def fake_urlopen(request: object, timeout: float) -> _FakeResponse:
        captured.append(request)
        return _FakeResponse(json.dumps({"tag_name": "v1.0.0"}).encode())

    monkeypatch.setattr("trxmp.infrastructure.github_releases.urllib.request.urlopen", fake_urlopen)
    GitHubReleaseSource("Equix", "trxmp").latest_tag()

    assert captured[0].full_url == "https://api.github.com/repos/Equix/trxmp/releases/latest"  # type: ignore[attr-defined]
