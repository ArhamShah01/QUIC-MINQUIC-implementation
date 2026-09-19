"""Run a QUIC client experiment under simulated network conditions.

Typical usage::

    python -m experiments.run_experiment --interface lo \
        --loss 10 --latency 50 --jitter 5

The script applies the requested netem rules, invokes the QUIC client, and
stores the resulting metrics CSV file.
"""
import argparse
import asyncio
import sys

from .network_conditions import netem_conditions
from quic.client import run_client

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run QUIC client with netem conditions")
    parser.add_argument("--interface", default="lo", help="Network interface to apply netem (default: lo)")
    parser.add_argument("--loss", type=float, default=0.0, help="Packet loss percentage")
    parser.add_argument("--latency", type=int, default=0, help="One‑way latency in ms")
    parser.add_argument("--jitter", type=int, default=0, help="Latency jitter in ms")
    parser.add_argument("--bandwidth", type=int, default=0, help="Bandwidth limit in Mbps (0 = unlimited)")
    return parser.parse_args()

async def main():
    args = parse_args()
    # Apply netem for the duration of the client run.
    with netem_conditions(
        interface=args.interface,
        loss_percent=args.loss,
        latency_ms=args.latency,
        jitter_ms=args.jitter,
        bandwidth_mbps=args.bandwidth,
    ):
        # Run the client – it will record its own metrics.
        await run_client()

if __name__ == "__main__":
    # Ensure the event loop is properly closed on KeyboardInterrupt.
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
