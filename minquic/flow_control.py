"""Flow‑control helpers.

Expose per‑connection and per‑stream flow‑control limits from an ``aioquic``
connection.
"""
from aioquic.quic.connection import QuicConnection

def get_flow_control_limits(conn: QuicConnection) -> dict:
    """Return the flow‑control limits the peer granted for sending.

    ``max_data`` is the connection-wide limit. ``max_stream_data`` is the
    per-stream limit for bidirectional streams opened by the client, which is
    where all echo traffic in this project flows.
    """
    if conn._is_client:
        max_stream_data = conn._remote_max_stream_data_bidi_remote
    else:
        max_stream_data = conn._remote_max_stream_data_bidi_local
    return {
        "max_data": conn._remote_max_data,
        "max_stream_data": max_stream_data,
    }
