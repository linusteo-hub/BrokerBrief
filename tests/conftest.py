"""
tests/conftest.py

No test may touch the network: fetchers are tested on recorded responses in
tests/fixtures/. Any attempt to open a socket fails the test immediately.
"""

import socket

import pytest


class NetworkBlocked(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def _block_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise NetworkBlocked("tests must not use the network; use a recorded fixture")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
