"""Congestion‑control helpers.

Expose congestion‑window and related metrics from an ``aioquic`` connection.
"""
from aioquic.quic.connection import QuicConnection

def get_congestion_stats(conn: QuicConnection) -> dict:
    """Return congestion‑control information.
    """
    # aioquic keeps loss recovery (RTT, controller) on the private ``_loss``.
    recovery = conn._loss
    return {
        "congestion_window": recovery.congestion_window,
        "bytes_in_flight": recovery.bytes_in_flight,
        # Smoothed RTT in seconds; None until the first RTT sample arrives.
        "rtt": recovery._rtt_smoothed if recovery._rtt_initialized else None,
    }
