"""Summarise a sweep CSV: per condition, per protocol, mean and spread.

Usage::

    python -m experiments.analyse_sweep experiments/results/sweep_<ts>.csv
    python -m experiments.analyse_sweep <csv> --metric transfer_ms --csv summary.csv

Prints one row per network condition with the mean and standard deviation of
the metric for each protocol, and MINQUIC's result as a ratio of QUIC's
(above 1.0 means MINQUIC is better for goodput, worse for times).
"""
import argparse
import csv
import statistics
from pathlib import Path

CONDITION_FIELDS = ["loss_percent", "latency_ms", "jitter_ms", "bandwidth_mbps", "queue_packets"]
HIGHER_IS_BETTER = {"goodput_mbps", "bytes_received", "congestion_window"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarise a QUIC vs MINQUIC sweep")
    parser.add_argument("sweep_csv", type=Path)
    parser.add_argument("--metric", default="goodput_mbps",
                        help="Column to summarise (default: goodput_mbps)")
    parser.add_argument("--csv", type=Path, help="Also write the summary to this CSV")
    return parser.parse_args()


def summarise(rows: list, metric: str) -> list:
    """Return one summary row per condition, in the order the conditions appear."""
    conditions = []
    for row in rows:
        key = tuple(row[f] for f in CONDITION_FIELDS)
        if key not in conditions:
            conditions.append(key)

    summary = []
    for key in conditions:
        entry = dict(zip(CONDITION_FIELDS, key))
        for protocol in ("quic", "minquic"):
            values = [
                float(r[metric]) for r in rows
                if tuple(r[f] for f in CONDITION_FIELDS) == key
                and r["protocol"] == protocol and r["status"] == "ok" and r[metric]
            ]
            entry[f"{protocol}_n"] = len(values)
            entry[f"{protocol}_mean"] = statistics.mean(values) if values else None
            entry[f"{protocol}_sd"] = statistics.stdev(values) if len(values) > 1 else 0.0
            failed = [r for r in rows
                      if tuple(r[f] for f in CONDITION_FIELDS) == key
                      and r["protocol"] == protocol and r["status"] != "ok"]
            entry[f"{protocol}_failed"] = len(failed)
        if entry["quic_mean"] and entry["minquic_mean"]:
            ratio = entry["minquic_mean"] / entry["quic_mean"]
            entry["ratio"] = ratio if metric in HIGHER_IS_BETTER else 1 / ratio
        else:
            entry["ratio"] = None
        summary.append(entry)
    return summary


def main() -> None:
    args = parse_args()
    with args.sweep_csv.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    summary = summarise(rows, args.metric)

    print(f"{args.metric} by condition (mean +/- sd over runs)\n")
    header = f"{'loss%':>6} {'delay':>6} {'jitter':>7} {'rate':>5} {'queue':>6} | {'QUIC':>16} {'MINQUIC':>16} | {'MINQUIC/QUIC':>12}"
    print(header)
    print("-" * len(header))
    for e in summary:
        quic = f"{e['quic_mean']:.2f}+/-{e['quic_sd']:.2f}" if e["quic_mean"] else "-"
        minquic = f"{e['minquic_mean']:.2f}+/-{e['minquic_sd']:.2f}" if e["minquic_mean"] else "-"
        ratio = f"{e['ratio']:.2f}x" if e["ratio"] else "-"
        failed = e["quic_failed"] + e["minquic_failed"]
        note = f"  ({failed} run(s) not ok)" if failed else ""
        print(f"{e['loss_percent']:>6} {e['latency_ms']:>6} {e['jitter_ms']:>7} "
              f"{e['bandwidth_mbps']:>5} {e['queue_packets']:>6} | {quic:>16} {minquic:>16} | {ratio:>12}{note}")

    if args.csv:
        with args.csv.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(summary[0]))
            writer.writeheader()
            writer.writerows(summary)
        print(f"\nSummary written to {args.csv}")


if __name__ == "__main__":
    main()
