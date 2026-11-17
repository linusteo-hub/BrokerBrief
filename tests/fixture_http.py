"""
tests/fixture_http.py

A stand-in for requests.get that serves recorded responses from
tests/fixtures/, so fetchers run their real parsing code with no network.
"""

from pathlib import Path

import requests

FIXTURES = Path(__file__).parent / "fixtures"


class FixtureResponse:
    def __init__(self, path: str, status: int = 200):
        self.status_code = status
        self.content = (FIXTURES / path).read_bytes()
        self.text = self.content.decode("utf-8")

    def json(self):
        import json
        return json.loads(self.text)  # raises ValueError on malformed bodies, like requests

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error (fixture)")


def serve(path: str, status: int = 200):
    """A fake `get` that returns the same fixture whatever URL it's given."""
    return lambda url, params=None, timeout=None, **kw: FixtureResponse(path, status)


def serve_by(choose):
    """A fake `get` that picks the fixture from (url, params)."""
    return lambda url, params=None, timeout=None, **kw: FixtureResponse(*choose(url, params or {}))
