# QUIC Baseline Implementation

The **QUIC** package implements a minimal yet functional QUIC stack using the
pure‑Python **aioquic** library. The focus is on raw stream handling rather than
higher‑level HTTP/3 semantics, which aligns with the project goal of exposing
core QUIC concepts (connection establishment, stream multiplexing, reliability,
congestion control, etc.).

## Key Components

- **connection.py** – Constructs an ``aioquic.quic.configuration.QuicConfiguration``.
  For the server role it generates a self‑signed X.509 certificate (via OpenSSL)
  if the configured files are missing.

- **server.py** – Starts a QUIC listener using ``aioquic.asyncio.serve``.
  It employs ``EchoQuicProtocol`` (a subclass of ``QuicConnectionProtocol``) that
  simply echoes any received data back on the same stream. This demonstrates the
  raw stream API without additional framing.

- **client.py** – Connects to the server using ``aioquic.asyncio.connect``.
  ``EchoClientProtocol`` opens a configurable number of streams, sends a
  random payload on each, and records the echoed response. Performance metrics
  (elapsed time, bytes sent/received, etc.) are stored via the shared
  ``MetricsCollector``.

- **metrics.py** – Singleton that aggregates metric dictionaries and can
  dump them to CSV or JSON files for later analysis.

- **congestion.py**, **flow_control.py** – Thin wrappers that
  expose internal ``QuicConnection`` state (congestion window, bytes in
  flight, RTT, flow‑control limits). These are useful for experiment reporting
  and will be extended in the MINQUIC phase.

## How It Works

1. The server reads ``config/config.yaml`` to obtain host/port and TLS file paths.
   If the certificate files are absent, ``connection._generate_self_signed_cert``
   creates them using ``openssl``.
2. The server launches an ``aioquic`` listener. Whenever a client opens a stream,
   the ``EchoQuicProtocol`` receives ``StreamDataReceived`` events and writes the
   same payload back, preserving the ``end_stream`` flag.
3. The client loads the same configuration, builds a client ``QuicConfiguration``
   (no certificate required), and connects to the server.
4. Upon connection, the client creates the requested number of streams, sends the
   payload, and awaits the echo. All timestamps are recorded with ``MetricsCollector``.
5. After the client finishes, metrics are written to ``experiments/results`` as a
   CSV file named ``client_<timestamp>.csv``.

## Extensibility

The modular layout makes it straightforward to replace or augment any component:
- Swap ``EchoQuicProtocol`` for a more complex application protocol.
- Add per‑packet logging.
- Replace the congestion‑control wrapper with a custom algorithm for MINQUIC.
- Insert additional experiment parameters (e.g., packet reordering) by extending
  ``network_conditions`` and the configuration file.

The baseline serves both as a functional demo and as a solid foundation for the subsequent MINQUIC enhancements.

## Running the Demo

The QUIC demo can be started from the command line.  First launch the server in a terminal:

```bash
python -m quic.server
```

In a separate terminal start the client.  The following arguments are supported:

```bash
python -m quic.client \
    --payload-size 1024   # size of each payload in bytes (default 1024)
    --streams 3           # number of concurrent streams (default 1)
```

The client will:
1. Open the requested number of streams.
2. Send a random payload on each stream.
3. Wait for the echo response.
4. Record performance metrics (elapsed time, bytes sent/received, congestion window, flow‑control limits, etc.).
5. Dump a CSV file to ``experiments/results`` named ``client_<timestamp>.csv``.

You can capture the traffic with Wireshark while the demo runs:

```bash
sudo tcpdump -i lo -w wireshark/captures/quic_demo_$(date +%s).pcap udp port 4433
```

Open the resulting ``.pcap`` file in Wireshark to inspect the QUIC handshake, stream frames, and any retransmissions.

## Metrics Reference

The CSV files produced by the ``MetricsCollector`` contain the following columns (additional columns may be added by future extensions):

| Column | Description |
|--------|-------------|
| ``event`` | Identifier of the recorded event (e.g., ``client_start``, ``client_complete``, ``connection_terminated``). |
| ``timestamp`` | UTC ISO‑8601 timestamp when the metric was recorded. |
| ``elapsed_ms`` | Total elapsed time for the client run (in milliseconds). |
| ``bytes_sent`` | Total payload bytes transmitted by the client. |
| ``bytes_received`` | Total payload bytes echoed back to the client. |
| ``congestion_window`` | Current congestion window size reported by ``aioquic`` at the end of the run. |
| ``bytes_in_flight`` | Number of bytes currently in flight (not yet acknowledged). |
| ``rtt`` | Measured round‑trip time (in seconds) from the QUIC connection object. |
| ``max_data`` | Connection‑level flow‑control limit. |
| ``max_stream_data`` | Stream‑level flow‑control limit. |

These metrics enable direct comparison between the baseline QUIC implementation and the future MINQUIC variant.

## Extensibility

The modular layout makes it straightforward to replace or augment any component:
- Swap ``EchoQuicProtocol`` for a more complex application protocol.
- Add per‑packet logging.
- Replace the congestion‑control wrapper with a custom algorithm for MINQUIC.
- Insert additional experiment parameters (e.g., packet reordering) by extending
  ``network_conditions`` and the configuration file.

The baseline serves both as a functional demo and as a solid foundation for the subsequent MINQUIC enhancements.
