"""Async helpers for reading from and writing to aioquic streams.

The functions operate on ``aioquic.asyncio.QuicStream`` objects. They are thin
wrappers that ensure the entire payload is transferred before returning.
"""
import asyncio
from typing import Any

async def read_all(stream: Any) -> bytes:
    """Read all data from *stream* until EOF.
    """
    data = bytearray()
    while True:
        chunk = await stream.read(4096)
        if not chunk:
            break
        data.extend(chunk)
    return bytes(data)

async def write_all(stream: Any, data: bytes) -> None:
    """Write *data* to *stream* and close the write side.
    """
    # aioquic streams have ``write`` which returns a awaitable when the buffer is flushed.
    offset = 0
    while offset < len(data):
        # Send up to 4096 bytes at a time – aioquic will handle flow control.
        chunk = data[offset : offset + 4096]
        await stream.write(chunk)
        offset += len(chunk)
    await stream.write_eof()
