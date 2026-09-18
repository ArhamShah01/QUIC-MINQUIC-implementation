"""Test that the QUIC client module loads correctly.

These lightweight tests verify that the configuration can be parsed and that
the ``run_client`` coroutine can be imported without raising exceptions.
"""
import pytest
from quic import client as quic_client

@pytest.mark.asyncio
async def test_client_import(config):
    # Ensure the client module can be imported and the coroutine exists.
    assert hasattr(quic_client, "run_client")
    # We won't actually execute the client here because it requires a server.
    # A simple sanity check – call the coroutine to obtain a coroutine object.
    coro = quic_client.run_client()
    assert hasattr(coro, "cr_await")  # indicates it's an awaitable coroutine
