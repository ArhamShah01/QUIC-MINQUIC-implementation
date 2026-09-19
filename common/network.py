"""Network experiment helpers.

Provides thin wrappers around Linux ``tc netem`` to inject packet loss,
latency, jitter and bandwidth limits for reproducible experiments.
These helpers are used by the ``experiments`` module. The implementation
relies on the ``tc`` command being available and the process having the
necessary privileges (typically via ``sudo``). Errors are logged but do
not stop the main application.
"""
import subprocess
import shlex
from .logger import get_logger

LOGGER = get_logger("common.network")

def _run_tc(command: str) -> None:
    """Execute a ``tc`` command, logging any errors.

    Parameters
    ----------
    command:
        The full ``tc`` command string (without ``sudo`` – the caller
        should include it if required).
    """
    try:
        subprocess.run(shlex.split(command), check=True, capture_output=True)
        LOGGER.debug("Executed tc command: %s", command)
    except subprocess.CalledProcessError as exc:
        LOGGER.error(
            "tc command failed: %s (stdout=%s stderr=%s)",
            command,
            exc.stdout.decode(errors="ignore"),
            exc.stderr.decode(errors="ignore"),
        )

def build_netem_command(
    interface: str,
    loss_percent: float = 0.0,
    latency_ms: int = 0,
    jitter_ms: int = 0,
    bandwidth_mbps: int = 0,
    queue_packets: int = 0,
) -> str:
    """Return the ``tc`` command that installs a single netem qdisc.

    Only the non‑zero parameters are added. Bandwidth uses netem's own
    ``rate`` option, so it combines with loss, delay and jitter instead of
    replacing them. ``queue_packets`` sets the netem queue ``limit``.
    """
    parts = ["sudo tc qdisc add dev", shlex.quote(interface), "root netem"]
    if latency_ms:
        delay = f"delay {latency_ms}ms"
        if jitter_ms:
            delay += f" {jitter_ms}ms distribution normal"
        parts.append(delay)
    if loss_percent:
        parts.append(f"loss {loss_percent}%")
    if bandwidth_mbps:
        parts.append(f"rate {bandwidth_mbps}mbit")
    if queue_packets:
        parts.append(f"limit {queue_packets}")
    return " ".join(parts)

def apply_netem(
    interface: str,
    loss_percent: float = 0.0,
    latency_ms: int = 0,
    jitter_ms: int = 0,
    bandwidth_mbps: int = 0,
    queue_packets: int = 0,
) -> None:
    """Apply netem rules to *interface* (see :func:`build_netem_command`).

    On the loopback interface every packet passes the qdisc once per
    direction, so the round-trip time is twice ``latency_ms``.
    """
    _run_tc(build_netem_command(
        interface,
        loss_percent=loss_percent,
        latency_ms=latency_ms,
        jitter_ms=jitter_ms,
        bandwidth_mbps=bandwidth_mbps,
        queue_packets=queue_packets,
    ))

def clear_netem(interface: str) -> None:
    """Remove any netem rules from *interface*.
    """
    _run_tc(f"sudo tc qdisc del dev {shlex.quote(interface)} root")
