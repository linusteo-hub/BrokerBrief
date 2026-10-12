"""
tests/test_eia_redaction.py

EIA request errors quote the request URL, which carries the API key, and the
Live Data page displays those errors. The key must never appear in them.
Run with: python -m pytest tests/test_eia_redaction.py
"""

import unittest
from unittest import mock

import requests

from modules import eia


class RedactionTests(unittest.TestCase):
    def test_redact_removes_key_from_url(self):
        message = "404 Client Error for url: https://api.eia.gov/v2/x?api_key=SECRET123&frequency=daily"
        self.assertNotIn("SECRET123", eia._redact(message))
        self.assertIn("api_key=<redacted>", eia._redact(message))

    def test_fetch_errors_do_not_contain_key(self):
        error = requests.HTTPError("429 Too Many Requests for url: https://api.eia.gov/v2/x?api_key=SECRET123")
        with mock.patch.object(eia.requests, "get", side_effect=error):
            for result in (eia.fetch_brent_spot("SECRET123"), eia.fetch_brent_forecast("SECRET123")):
                self.assertFalse(result["success"])
                self.assertNotIn("SECRET123", result["error"])


if __name__ == "__main__":
    unittest.main()
