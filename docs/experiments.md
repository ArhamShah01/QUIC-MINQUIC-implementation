# Experiment Methodology

This document describes how to run reproducible experiments that compare the
QUIC baseline (aioquic's default Reno congestion control) with MINQUIC
(MINBBR congestion control, see ``docs/minquic.md``).

## Requirements

- Linux with the ``tc`` utility (``iproute2``) and ``sudo`` rights, since netem
  changes the network interface.
- Run ``sudo -v`` right before an experiment so ``sudo tc`` does not ask for a
  password in the middle of a sweep.

## Running an Experiment

``experiments/run_experiment.py`` applies a netem condition, then for each run
starts the matching server (``python -m quic.server`` or
``python -m minquic.server``) and runs its client in a fresh process. Runs of
the two protocols alternate, so both see the same conditions over time.

**One condition:**
```bash
python -m experiments.run_experiment --protocol both --runs 5 \
    --latency 25 --jitter 5 --loss 1 --bandwidth 20 --queue 1000
```

**The predefined grid:**
```bash
python -m experiments.run_experiment --protocol both --grid
```
The grid is a baseline condition (25 ms one-way delay, no loss, no jitter,
20 Mbit/s, 1000-packet queue) with one factor varied at a time:

| Factor | Values |
| ------ | ------ |
| Loss (%) | 0, 1, 2, 5 |
| One-way delay (ms) | 10, 25, 50, 100 |
| Jitter (ms) | 0, 5, 10, 20 |
| Queue (packets) | 50, 1000 |

That gives 11 conditions; with 2 protocols and 5 runs each it is 110 runs.
Edit ``BASELINE`` and ``GRID_FACTORS`` at the top of the script to change it.

**Other options:**

| Option | Default | Meaning |
| ------ | ------- | ------- |
| ``--protocol`` | ``both`` | ``quic``, ``minquic`` or ``both`` |
| ``--runs`` | 5 | Runs per protocol and condition |
| ``--payload-size`` | 5,000,000 | Bytes sent (and echoed) per stream |
| ``--streams`` | 3 | Parallel streams per run |
| ``--timeout`` | 300 | Seconds before a run is recorded as ``timeout`` |
| ``--interface`` | ``lo`` | Interface netem is applied to |
| ``--dry-run`` | off | Print the ``tc`` command, run without netem |

### Notes on netem

- All conditions are one ``netem`` qdisc, e.g.
  ``tc qdisc add dev lo root netem delay 25ms 5ms distribution normal loss 1% rate 20mbit limit 1000``,
  so rate limiting combines with loss, delay and jitter.
- On the loopback interface each packet passes netem once per direction, so
  **RTT = 2 × delay** and loss applies in both directions.
- Large netem jitter reorders packets, which QUIC's loss detection can treat
  as loss. Keep this in mind when reading the jitter results.

## Output

- ``experiments/results/sweep_<timestamp>.csv``: one row per run, with the
  condition (``loss_percent``, ``latency_ms``, ``jitter_ms``,
  ``bandwidth_mbps``, ``queue_packets``), ``protocol``, ``run``, ``status``
  (``ok``, ``timeout``, ``error N``) and the client's metrics below.
- ``experiments/results/<protocol>_client_<timestamp>.csv``: the raw metrics of
  each client run.
- ``experiments/results/minquic_trace_<timestamp>.csv``: MINBBR's state once
  per round trip, written when the MINQUIC client runs with ``--trace``
  (``python -m minquic.client --payload-size 5000000 --streams 3 --trace``).
  ``time`` is the event-loop clock in seconds; subtract the first value.

## Metrics Collected

| Metric | Description |
| ------ | ----------- |
| ``handshake_ms`` | QUIC + TLS 1.3 handshake time (``connect()`` until connected) |
| ``transfer_ms`` | From sending the first payload until every echo has arrived |
| ``total_ms`` | Handshake plus transfer |
| ``goodput_mbps`` | Echoed bytes × 8 / ``transfer_ms`` |
| ``bytes_sent`` / ``bytes_received`` | Payload bytes sent and echoed back |
| ``congestion_window`` / ``bytes_in_flight`` | Client congestion state at the end of the run |
| ``rtt`` | Smoothed RTT in seconds at the end of the run |
| ``max_data`` / ``max_stream_data`` | Flow-control limits granted by the peer |
| ``minbbr_*`` | MINQUIC only: BtlBW, bw_lo, RTprop, BDP, state, ProbeBW mode and phase, pacing rate |

## Comparison Procedure

1. Run the grid with ``--protocol both`` so both protocols see identical
   conditions.
2. For each condition and protocol, compute the mean and standard deviation of
   ``goodput_mbps`` and ``transfer_ms`` over the runs with ``status == ok``,
   and report how many runs timed out.
3. Plot goodput against each grid factor (one line per protocol), and use a
   ``--trace`` run to show how MINBBR's window and mode change over time.

## Reproducibility Notes

- Close other traffic on the interface while a sweep runs; netem on ``lo``
  affects every local connection.
- If a sweep is interrupted, remove the leftover qdisc with
  ``sudo tc qdisc del dev lo root``.
- Result CSVs are ignored by git; keep them in a separate results archive.
- Wireshark captures (``wireshark/captures/``) are optional, for packet-level
  debugging:
  ```bash
  sudo tcpdump -i lo -w wireshark/captures/exp_$(date +%s).pcap udp port 4433
  ```
