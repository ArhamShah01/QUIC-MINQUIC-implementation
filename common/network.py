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
import logging
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

def apply_netem(
    interface: str,
    loss_percent: float = 0.0,
    latency_ms: int = 0,
    jitter_ms: int = 0,
    bandwidth_mbps: int = 0,
) -> None:
    """Apply netem rules to *interface*.

    Only the non‑zero parameters are added to the ``tc`` rule.
    """
    parts = ["sudo tc qdisc add dev", shlex.quote(interface), "root netem"]
    if loss_percent:
        parts.append(f"loss {loss_percent}%")
    if latency_ms:
        delay = f"delay {latency_ms}ms"
        if jitter_ms:
            delay += f" {jitter_ms}ms distribution normal"
        parts.append(delay)
    if bandwidth_mbps:
        # Use tbf to limit bandwidth
        burst = max(10_000, bandwidth_mbps * 1000)  # simple heuristic
        parts = [
            "sudo tc qdisc add dev",
            shlex.quote(interface),
            "root tbf rate",
            f"{bandwidth_mbps}mbit burst {burst} limit 1000000",
        ]
    _run_tc(" ".join(parts))

def clear_netem(interface: str) -> None:
    """Remove any netem rules from *interface*.
    """
    _run_tc(f"sudo tc qdisc del dev {shlex.quote(interface)} root")
