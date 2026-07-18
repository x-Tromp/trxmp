"""GitHub's REST API as a ``ReleaseSource`` — the one outbound network
call this app makes anywhere.

stdlib ``urllib``, not a new dependency: one GET request a launch
doesn't earn pulling in ``requests`` or ``httpx`` for a project that's
otherwise kept its dependency list to what each feature genuinely needs.
"""

from __future__ import annotations

import json
import urllib.request

DEFAULT_TIMEOUT_SECONDS = 3.0


class GitHubReleaseSource:
    """No auth token: one unauthenticated GET per launch stays
    comfortably inside GitHub's 60-requests-per-hour anonymous limit for
    anything short of an unrealistic launch rate.
    """

    def __init__(
        self, owner: str, repo: str, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    ) -> None:
        self._url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
        self._timeout_seconds = timeout_seconds

    def latest_tag(self) -> str | None:
        request = urllib.request.Request(
            self._url,
            headers={
                "Accept": "application/vnd.github+json",
                # GitHub's API rejects requests with no User-Agent at all.
                "User-Agent": "trxmp-update-check",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_seconds) as response:
                payload = json.loads(response.read())
        except (OSError, ValueError):
            # Offline, DNS failure, GitHub down, rate-limited, a
            # malformed body — all of them mean the same thing to the
            # caller: no answer this time, never a crash.
            return None
        tag = payload.get("tag_name")
        return tag if isinstance(tag, str) else None
