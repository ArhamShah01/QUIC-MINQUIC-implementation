"""Run QUIC and MINQUIC clients under simulated network conditions.

Typical usage::

    # One condition, both protocols, 5 runs each
    python -m experiments.run_experiment --protocol both --runs 5 \\
        --loss 1 --latency 25 --jitter 5 --bandwidth 20 --queue 1000

    # The predefined condition grid (see BASELINE and GRID_FACTORS below)
    python -m experiments.run_experiment --protocol both --grid

For every run the matching server is started as a subprocess and the client
runs in a fresh process (the metrics collector is a process-wide singleton).
Each run's ``client_complete`` record is appended, together with the network
condition, to ``<output_dir>/sweep_<timestamp>.csv``.

netem needs root: run ``sudo -v`` first so ``sudo tc`` does not prompt
mid-sweep. ``--dry-run`` prints the tc commands and runs without netem.
On the loopback interface netem delays each direction, so RTT = 2 x latency.
"""
import argparse
import contextlib
import csv
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml

from common.network import NetemError, build_netem_command
from .network_conditions import netem_conditions

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Baseline condition; the grid varies one factor at a time around it, which
# gives one line plot per factor (goodput vs loss, delay, jitter, queue).
BASELINE = {"loss_percent": 0, "latency_ms": 25, "jitter_ms": 0,
            "bandwidth_mbps": 20, "queue_packets": 1000}
GRID_FACTORS = {
    "loss_percent": [0, 1, 2, 5],
    "latency_ms": [10, 25, 50, 100],
    "jitter_ms": [0, 5, 10, 20],
    "queue_packets": [50, 1000],
}
CONDITION_FIELDS = list(BASELINE)


def build_grid() -> list:
    """Return the conditions: the baseline, then each factor varied alone."""
    grid = [dict(BASELINE)]
    for factor, values in GRID_FACTORS.items():
        for value in values:
            condition = dict(BASELINE, **{factor: value})
            if condition not in grid:
                grid.append(condition)
    return grid


def parse_args() -> argparse.Namespace:
    config_path = PROJECT_ROOT / "config" / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    exp = cfg.get("experiment", {})

    parser = argparse.ArgumentParser(description="Compare QUIC and MINQUIC under netem conditions")
    parser.add_argument("--protocol", choices=["quic", "minquic", "both"], default="both")
    parser.add_argument("--runs", type=int, default=5, help="Runs per protocol and condition")
    parser.add_argument("--payload-size", type=int, default=5_000_000, help="Bytes per stream")
    parser.add_argument("--streams", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=300, help="Seconds before a run is abandoned")
    parser.add_argument("--interface", default="lo", help="Network interface to apply netem (default: lo)")
    parser.add_argument("--loss", type=float, default=exp.get("loss_percent", 0), help="Packet loss percentage")
    parser.add_argument("--latency", type=int, default=exp.get("latency_ms", 0), help="One‑way latency in ms")
    parser.add_argument("--jitter", type=int, default=exp.get("jitter_ms", 0), help="Latency jitter in ms")
    parser.add_argument("--bandwidth", type=int, default=exp.get("bandwidth_mbps", 0), help="Rate limit in Mbit/s (0 = unlimited)")
    parser.add_argument("--queue", type=int, default=0, help="netem queue limit in packets (0 = default)")
    parser.add_argument("--grid", action="store_true", help="Run the predefined condition grid")
    parser.add_argument("--dry-run", action="store_true", help="Print tc commands instead of applying netem")
    args = parser.parse_args()
    args.output_dir = PROJECT_ROOT / cfg["metrics"]["output_dir"]
    return args


def run_once(protocol: str, args: argparse.Namespace) -> dict:
    """Start the server, run one client, and return its client_complete record."""
    pattern = f"{protocol}_client_*.csv"
    existing = set(args.output_dir.glob(pattern))
    server = subprocess.Popen(
        [sys.executable, "-m", f"{protocol}.server"],
        cwd=PROJECT_ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(1.0)  # let the server bind
        try:
            subprocess.run(
                [sys.executable, "-m", f"{protocol}.client",
                 "--payload-size", str(args.payload_size), "--streams", str(args.streams)],
                cwd=PROJECT_ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=args.timeout, check=True,
            )
        except subprocess.TimeoutExpired:
            return {"status": "timeout"}
        except subprocess.CalledProcessError as exc:
            return {"status": f"error {exc.returncode}"}
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()

    new_csvs = sorted(set(args.output_dir.glob(pattern)) - existing)
    if not new_csvs:
        return {"status": "no output"}
    with new_csvs[-1].open(newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["event"] == "client_complete"]
    if not rows:
        return {"status": "incomplete"}
    record = {k: v for k, v in rows[-1].items()
              if v != "" and k not in ("timestamp", "event", "protocol")}
    record["status"] = "ok"
    record["client_csv"] = new_csvs[-1].name
    return record


def main() -> None:
    args = parse_args()
    protocols = ["quic", "minquic"] if args.protocol == "both" else [args.protocol]
    if args.grid:
        conditions = build_grid()
    else:
        conditions = [{
            "loss_percent": args.loss, "latency_ms": args.latency, "jitter_ms": args.jitter,
            "bandwidth_mbps": args.bandwidth, "queue_packets": args.queue,
        }]

    if not args.dry_run:
        _require_sudo()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    sweep_path = args.output_dir / f"sweep_{datetime.now().strftime('%Y%m%d-%H%M%S')}.csv"
    rows = []
    total = len(conditions) * len(protocols) * args.runs
    done = 0
    for condition in conditions:
        print(f"[INFO] Condition: {condition}")
        if args.dry_run:
            print(f"[DRY-RUN] {build_netem_command(args.interface, **condition)}")
            netem = contextlib.nullcontext()
        else:
            # Refresh the sudo timestamp, so a long sweep cannot stall (or
            # silently keep the previous condition) when it expires.
            _require_sudo()
            netem = netem_conditions(args.interface, **condition)
        with netem:
            for run in range(1, args.runs + 1):
                # Alternate protocols within a run so both see the same drift.
                for protocol in protocols:
                    done += 1
                    record = run_once(protocol, args)
                    row = dict(condition, protocol=protocol, run=run, **record)
                    rows.append(row)
                    print(f"[{done}/{total}] {protocol} run {run}: {record['status']}"
                          + (f", goodput {float(record['goodput_mbps']):.2f} Mbit/s"
                             if record["status"] == "ok" else ""))
                    _write_sweep(sweep_path, rows)
    print(f"[INFO] Sweep results: {sweep_path}")


def _require_sudo() -> None:
    """Make sure ``sudo`` works without a password prompt, and refresh it."""
    if subprocess.run(["sudo", "-n", "-v"], capture_output=True).returncode != 0:
        sys.exit("[ERROR] sudo needs a password. Run 'sudo -v' in this terminal "
                 "first, then start the sweep again (netem needs root).")


def _write_sweep(path: Path, rows: list) -> None:
    """Rewrite the sweep CSV with every row so far (columns in first-seen order)."""
    fieldnames = CONDITION_FIELDS + ["protocol", "run", "status"]
    for row in rows:
        fieldnames.extend(k for k in row if k not in fieldnames)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
    except NetemError as exc:
        sys.exit(f"[ERROR] Network conditions could not be applied: {exc}\n"
                 "        Stopping: results would not match the labelled condition.\n"
                 "        Check for a leftover rule with 'tc qdisc show dev lo'.")
