from common.network import build_netem_command
from experiments.network_conditions import netem_conditions

def test_netem_conditions(monkeypatch):
    """Ensure the netem context manager can be entered without requiring sudo.

    The actual ``apply_netem`` and ``clear_netem`` functions are monkey‑patched
    to no‑ops so the test can run in environments without privileged access.
    """
    # Patch the underlying helpers to avoid needing sudo.
    monkeypatch.setattr('experiments.network_conditions.apply_netem', lambda *args, **kwargs: None)
    monkeypatch.setattr('experiments.network_conditions.clear_netem', lambda *args, **kwargs: None)
    # Use a small loss percentage; the context manager should not raise.
    with netem_conditions("lo", loss_percent=5, latency_ms=10, jitter_ms=0, bandwidth_mbps=0):
        pass


def test_netem_command_combines_all_conditions():
    cmd = build_netem_command("lo", loss_percent=1, latency_ms=20, jitter_ms=5,
                              bandwidth_mbps=20, queue_packets=50)
    assert cmd == ("sudo tc qdisc add dev lo root netem "
                   "delay 20ms 5ms distribution normal loss 1% rate 20mbit limit 50")


def test_netem_command_omits_unset_conditions():
    assert build_netem_command("lo", latency_ms=10) == "sudo tc qdisc add dev lo root netem delay 10ms"
