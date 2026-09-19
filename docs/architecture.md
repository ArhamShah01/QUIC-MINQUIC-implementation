# Architecture Overview

The project is organized around a clear separation of concerns:

- **common/** – generic utilities that are independent of the QUIC implementation (logging, network‑condition helpers).
- **quic/** – the baseline QUIC implementation. It contains thin wrappers around the **aioquic** library and provides a modular API:
  - ``connection.py`` – builds the ``QuicConfiguration`` (TLS handling).
  - ``server.py`` – launches a QUIC echo server.
  - ``client.py`` – launches a QUIC client that can open multiple streams.
  - ``metrics.py`` – central collector for experiment results.
  - ``congestion.py`` / ``flow_control.py`` – expose internal QUIC state (congestion window, RTT, flow‑control limits) for analysis.
- **experiments/** – utilities for reproducible network experiments, including a ``run_experiment`` script that applies ``tc netem`` settings before invoking the client.
- **tests/** – pytest suite that currently performs basic sanity checks; integration tests can be expanded to spin up the server and verify multi‑stream behaviour.
- **docs/** – documentation describing the architecture, the baseline QUIC implementation, the MINQUIC extension plan, and experiment methodology.

The **MINQUIC** phase will reuse the ``quic`` package where possible and replace/extend only the components that are modified by the research paper (e.g., congestion control, packet header layout). This layered approach enables side‑by‑side performance comparison without code duplication.
