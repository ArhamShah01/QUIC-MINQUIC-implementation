# QUIC and MINQUIC

This repository implements a QUIC baseline in Python using the **aioquic** library, and **MINQUIC**, which replaces the congestion control with **MINBBR** (Sun, BDICN 2023). Both share the same echo server, multi-stream client, structured logging and metric collection, so they can be compared under identical network conditions.

## Quick Start
```bash
# Install dependencies
pip install -r requirements.txt

# Generate TLS certificates (if not present)
# The server will automatically generate a self‑signed certificate on first run.

# Start the server
python -m quic.server

# In a separate terminal, run the client
python -m quic.client --payload-size 1024 --streams 3
```

The client will connect, send data over the requested number of streams, and print a summary of performance metrics. Use ``minquic.server`` / ``minquic.client`` the same way to run MINQUIC.

## Comparing QUIC and MINQUIC
```bash
sudo -v   # netem needs root
python -m experiments.run_experiment --protocol both --grid
```
This runs both protocols under a grid of netem conditions and writes ``experiments/results/sweep_<timestamp>.csv``. See ``docs/experiments.md`` for the options and output, and ``docs/minquic.md`` for how MINBBR is implemented.

## Tests
```bash
python -m pytest
```

## Project Layout
```
comp_networks/
│   README.md
│   requirements.txt
│
├─ config/
│   └─ config.yaml               # Runtime configuration
│
├─ common/
│   ├─ logger.py                 # Structured logger
│   └─ network.py                # Netem helpers for experiment emulation
│
├─ quic/
│   ├─ __init__.py
│   ├─ client.py                # QUIC client entry‑point
│   ├─ server.py                # QUIC server entry‑point
│   ├─ connection.py            # Helper to build aioquic configuration
│   ├─ congestion.py            # Congestion‑control exposure
│   ├─ flow_control.py          # Flow‑control exposure
│   └─ metrics.py               # Central metrics collector
│
├─ minquic/                     # MINQUIC: same layout, MINBBR congestion control
│   └─ congestion.py            # MINBBR implementation (registered as "minbbr")
│
├─ tests/
│   ├─ conftest.py              # Pytest fixtures for server lifecycle
│   ├─ test_connection.py       # Handshake & basic stream tests
│   ├─ test_integration.py      # End-to-end QUIC and MINQUIC runs
│   ├─ test_minbbr.py           # MINBBR congestion-control unit tests
│   ├─ test_multi_stream.py     # Multi‑stream correctness tests
│   └─ test_netem.py            # Netem helper tests
│
├─ experiments/
│   ├─ run_experiment.py        # Run client under netem conditions
│   ├─ network_conditions.py    # Netem wrapper utilities
│   └─ results/                 # CSV files from experiments (auto‑generated)
│
├─ wireshark/
│   └─ captures/                # Capture files for manual analysis
│
└─ docs/
    ├─ architecture.md
    ├─ quic.md
    ├─ minquic.md
    └─ experiments.md
```

## License
This project is provided for educational purposes. The code is MIT‑licensed.
