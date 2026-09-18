import pytest
from experiments.network_conditions import netem_conditions

def test_netem_conditions(monkeypatch):
    """Ensure the netem context manager can be entered without requiring sudo.

    The actual ``apply_netem`` and ``clear_netem`` functions are monkey‑patched
    to no‑ops so the test can run in environments without privileged access.
    """
    # Patch the underlying helpers to avoid needing sudo.
    monkeypatch.setattr('common.network.apply_netem', lambda *args, **kwargs: None)
    monkeypatch.setattr('common.network.clear_netem', lambda *args, **kwargs: None)
    # Use a small loss percentage; the context manager should not raise.
    with netem_conditions("lo", loss_percent=5, latency_ms=10, jitter_ms=0, bandwidth_mbps=0):
        pass
