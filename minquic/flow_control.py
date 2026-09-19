"""Flow‑control helpers.

Expose per‑connection and per‑stream flow‑control limits from an ``aioquic``
connection.
"""
from aioquic.quic.connection import QuicConnection

def get_flow_control_limits(conn: QuicConnection) -> dict:
    """Return flow‑control window sizes.
    """
    return {
        "max_data": getattr(conn, "max_data", None),
        "max_stream_data": getattr(conn, "max_stream_data", None),
    }
