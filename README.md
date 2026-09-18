# QUIC Baseline Project

This repository implements a functional QUIC baseline in Python using the **aioquic** library. The implementation focuses on raw QUIC stream operations, structured logging, and metric collection to enable reproducible networking experiments.

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

The client will connect, send data over the requested number of streams, and print a summary of performance metrics.

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
│   ├─ network.py                # Netem helpers for experiment emulation
│   └─ utilities.py              # Misc helper functions
│
├─ quic/
│   ├─ __init__.py
│   ├─ client.py                # QUIC client entry‑point
│   ├─ server.py                # QUIC server entry‑point
│   ├─ connection.py            # Helper to build aioquic configuration
│   ├─ packet.py                # Placeholder for future packet metadata
│   ├─ stream.py                # Async read/write helpers for raw streams
│   ├─ reliability.py            # Reliability‑related stats (thin wrapper)
│   ├─ congestion.py            # Congestion‑control exposure
│   ├─ flow_control.py          # Flow‑control exposure
│   └─ metrics.py               # Central metrics collector
│
├─ minquic/                     # Will be populated after QUIC baseline
│   └─ (mirrored structure, initially empty)
│
├─ tests/
│   ├─ conftest.py              # Pytest fixtures for server lifecycle
│   ├─ test_connection.py       # Handshake & basic stream tests
│   └─ test_multi_stream.py    # Multi‑stream correctness tests
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
