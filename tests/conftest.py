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


@pytest.fixture(autouse=True)
def _clear_streamlit_cache():
    """app.py caches live fetches with st.cache_data, which lives for the whole
    process. Clear it around every test so one test's patched PortWatch result
    can never be served to another."""
    import streamlit as st
    st.cache_data.clear()
    st.cache_resource.clear()
    yield
    st.cache_data.clear()
    st.cache_resource.clear()
