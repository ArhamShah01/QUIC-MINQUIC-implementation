# Experiment Methodology

This document describes how to run reproducible networking experiments that
compare the QUIC baseline with the forthcoming MINQUIC implementation.

## Running an Experiment

1. **Configure experiment parameters** in ``config/config.yaml`` under the
   ``experiment`` section (loss, latency, jitter, bandwidth). These values are
   read by the ``run_experiment`` script.

2. **Execute the script**:
   ```bash
   python -m experiments.run_experiment \
       --interface lo \
       --loss 10 \
       --latency 50 \
       --jitter 5
   ```
   The script:
   - Applies the specified netem rules to the chosen interface (default
     ``lo`` for localhost) using ``tc``.
   - Starts the QUIC client (which in turn connects to the server that must be
     running separately).
   - Records metrics (connection time, throughput, packet counts, etc.) via the
     shared metrics collector.
   - Dumps a CSV file into ``experiments/results`` named
     ``client_<timestamp>.csv``.

3. **Capture traffic** (optional) with Wireshark for visual analysis:
   ```bash
   sudo tcpdump -i lo -w wireshark/captures/exp_$(date +%s).pcap udp port 4433
   ```
   Open the resulting ``.pcap`` file in Wireshark to examine packet numbers,
   retransmissions, and RTT.

## Metrics Collected

| Metric | Description |
| ------ | ----------- |
| ``connection_establishment_ms`` | Time from client start to QUIC handshake completion |
| ``transfer_time_ms`` | Duration of payload transmission and echo reception |
| ``throughput_bytes_per_sec`` | Calculated from total bytes transferred over ``transfer_time_ms`` |
| ``rtt_ms`` | Approximate round‑trip time derived from timestamps |
| ``packets_sent`` / ``packets_received`` | Counts of QUIC packets observed (from Wireshark captures) |
| ``retransmissions`` | Number of packets retransmitted (if any) |
| ``congestion_window`` | Current congestion window size during the experiment |

## Comparison Procedure

After the MINQUIC implementation is ready, repeat the same experiment steps
with the MINQUIC client (e.g., ``python -m minquic.client``). Ensure that the
``config.yaml`` values are identical for a fair comparison. Consolidate the CSV
files and compute aggregate statistics (mean, standard deviation) to populate
the comparison table described in the project specification.

## Reproducibility Notes

- The experiments assume a Linux environment with the ``tc`` utility and
  sufficient privileges (``sudo``) to modify network interfaces.
- All metric files are version‑controlled by timestamp; keep them in the
  repository or a separate results archive for later analysis.
- Wireshark captures are optional but recommended for deep packet‑level
  debugging.
