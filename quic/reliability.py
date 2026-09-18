"""Reliability utilities.

Provides a thin wrapper to expose ACK and retransmission statistics from an
``aioquic.quic.connection.QuicConnection`` instance.
"""
from aioquic.quic.connection import QuicConnection

def get_retransmission_stats(conn: QuicConnection) -> dict:
    """Return a dictionary with retransmission‑related counters.

    The aioquic connection tracks ``total_packets_sent`` and ``total_packets_lost``
    internally. Expose the fields that are relevant for our metrics.
    """
    return {
        "packets_sent": conn._sent_packets_counter if hasattr(conn, "_sent_packets_counter") else None,
        "packets_lost": conn._lost_packets_counter if hasattr(conn, "_lost_packets_counter") else None,
        "retransmissions": conn._retransmission_counter if hasattr(conn, "_retransmission_counter") else None,
    }
