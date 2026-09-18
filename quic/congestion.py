"""Congestion‑control helpers.

Expose congestion‑window and related metrics from an ``aioquic`` connection.
"""
from aioquic.quic.connection import QuicConnection

def get_congestion_stats(conn: QuicConnection) -> dict:
    """Return congestion‑control information.
    """
    # aioquic provides ``congestion_window`` and ``bytes_in_flight`` attributes.
    return {
        "congestion_window": getattr(conn, "congestion_window", None),
        "bytes_in_flight": getattr(conn, "bytes_in_flight", None),
        "rtt": getattr(conn, "rtt", None),
    }
