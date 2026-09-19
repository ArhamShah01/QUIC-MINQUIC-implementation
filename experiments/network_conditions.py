"""Experiment network‑condition utilities.

Provides a context manager that applies ``tc netem`` settings for the
duration of a block and automatically clears them afterwards.
"""
import contextlib
from common.network import apply_netem, clear_netem

@contextlib.contextmanager
def netem_conditions(interface: str, loss_percent: float = 0.0, latency_ms: int = 0, jitter_ms: int = 0, bandwidth_mbps: int = 0, queue_packets: int = 0):
    """Apply netem conditions for the duration of the ``with`` block.

    Parameters
    ----------
    interface:
        Network interface to which the rules should be applied (e.g. ``"lo"``).
    loss_percent, latency_ms, jitter_ms, bandwidth_mbps, queue_packets:
        Parameters passed to :func:`apply_netem`.
    """
    try:
        apply_netem(
            interface,
            loss_percent=loss_percent,
            latency_ms=latency_ms,
            jitter_ms=jitter_ms,
            bandwidth_mbps=bandwidth_mbps,
            queue_packets=queue_packets,
        )
        yield
    finally:
        clear_netem(interface)
