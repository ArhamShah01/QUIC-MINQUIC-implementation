"""QUIC client implementation using aioquic.

The client reads the configuration from ``config/config.yaml`` and opens a
configurable number of raw QUIC streams. Each stream sends a payload of the
specified size and waits for the echo response. Basic performance metrics are
recorded via the shared ``MetricsCollector``.
"""
import argparse

import asyncio
import os
import yaml
import time
from datetime import datetime
from aioquic.quic.events import StreamDataReceived, ConnectionTerminated
from aioquic.asyncio import connect, QuicConnectionProtocol

from .connection import create_quic_configuration
from .metrics import metrics
from .congestion import get_congestion_stats
from .flow_control import get_flow_control_limits
from common.logger import get_logger

LOGGER = get_logger("minquic.client")

class EchoClientProtocol(QuicConnectionProtocol):
    """Client protocol that sends a payload on each stream and records the echo.

    Parameters
    ----------
    payload: bytes
        Data to send on each stream.
    total_streams: int
        Number of parallel streams to open.
    """

    def __init__(self, *args, payload: bytes, total_streams: int, **kwargs):
        super().__init__(*args, **kwargs)
        self.payload = payload
        self.total_streams = total_streams
        self.responses = {}
        self._streams_completed = 0
        self._done = asyncio.Event()
        self._start_ts = None

    async def start(self) -> None:
        """Create streams, send payloads, and note start time.
        """
        self._start_ts = time.perf_counter()
        for _ in range(self.total_streams):
            stream_id = self._quic.get_next_available_stream_id()
            # Send the payload and close the stream for writing.
            self._quic.send_stream_data(stream_id, self.payload, end_stream=True)
            LOGGER.debug("Sent %d bytes on stream %d", len(self.payload), stream_id)
            print(f"[INFO] Sent {len(self.payload)} bytes on stream {stream_id}")

    def quic_event_received(self, event):
        if isinstance(event, StreamDataReceived):
            # Accumulate data for the given stream.
            buf = self.responses.setdefault(event.stream_id, bytearray())
            buf.extend(event.data)
            if event.end_stream:
                self._streams_completed += 1
                LOGGER.debug(
                    "Received complete echo on stream %d (%d bytes)",
                    event.stream_id,
                    len(buf)
                )
                print(f"[INFO] Received echo of {len(buf)} bytes on stream {event.stream_id}")
                if self._streams_completed == self.total_streams:
                    self._done.set()
        elif isinstance(event, ConnectionTerminated):
            # Ensure we unblock even on early termination.
            self._done.set()

    async def wait_done(self) -> None:
        """Wait until all streams have echoed back or the connection is closed."""
        await self._done.wait()

async def run_client(cli_args=None):
    # Load configuration.
    config_path = os.path.join(os.path.dirname(__file__), "..", "config", "config.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    print(f"[DEBUG] Loaded configuration from {config_path}")

    client_cfg = cfg["client"]
    # Apply CLI overrides if provided.
    payload_size = cli_args.payload_size if cli_args and cli_args.payload_size is not None else client_cfg.get("payload_size", 1024)
    streams = cli_args.streams if cli_args and cli_args.streams is not None else client_cfg.get("streams", 1)
    payload = os.urandom(payload_size)

    # Build QUIC client configuration.
    quic_cfg = create_quic_configuration(is_client=True)
    # Disable certificate verification for self‑signed certs in this demo.
    import ssl
    quic_cfg.verify_mode = ssl.CERT_NONE

    host = client_cfg["host"]
    port = client_cfg["port"]

    # Record start metric.
    metrics.record(event="client_start", host=host, port=port, payload_size=payload_size, streams=streams)

    print(f"[DEBUG] Connecting to {host}:{port} as QUIC client")
    print(f"[INFO] Using configuration: host={host}, port={port}, payload_size={payload_size}, streams={streams}")

    connect_ts = time.perf_counter()
    async with connect(
        host=host,
        port=port,
        configuration=quic_cfg,
        create_protocol=lambda *args, **kwargs: EchoClientProtocol(*args, payload=payload, total_streams=streams, **kwargs),
    ) as client:
        # ``connect`` returns once the QUIC/TLS handshake has completed.
        handshake_s = time.perf_counter() - connect_ts
        await client.start()
        await client.wait_done()
        # After client is done, gather stats.
        done_ts = time.perf_counter()
        elapsed = done_ts - client._start_ts
        total_s = done_ts - connect_ts
        total_received = sum(len(buf) for buf in client.responses.values())
        goodput_mbps = total_received * 8 / elapsed / 1e6 if elapsed > 0 else None
        # Gather congestion and flow control stats from the underlying QUIC connection.
        cong_stats = get_congestion_stats(client._quic)
        flow_stats = get_flow_control_limits(client._quic)
        # Record metrics.
        metrics.record(
            event="client_complete",
            protocol="minquic",
            handshake_ms=round(handshake_s * 1000, 3),
            transfer_ms=round(elapsed * 1000, 3),
            total_ms=round(total_s * 1000, 3),
            # Alias of transfer_ms, kept for older result files.
            elapsed_ms=round(elapsed * 1000, 3),
            goodput_mbps=goodput_mbps,
            bytes_sent=payload_size * streams,
            bytes_received=total_received,
            congestion_window=cong_stats.get("congestion_window"),
            bytes_in_flight=cong_stats.get("bytes_in_flight"),
            rtt=cong_stats.get("rtt"),
            max_data=flow_stats.get("max_data"),
            max_stream_data=flow_stats.get("max_stream_data"),
            **{k: v for k, v in cong_stats.items() if k.startswith("minbbr_")},
        )
        print("[INFO] Metrics recorded:")
        print("___________________________________________")
        print(f"  handshake_ms={handshake_s * 1000:.3f}")
        print(f"  transfer_ms={elapsed * 1000:.3f}")
        print(f"  goodput_mbps={goodput_mbps:.3f}")
        print(f"  bytes_sent={payload_size * streams}")
        print(f"  bytes_received={total_received}")
        print(f"  congestion_window={cong_stats.get('congestion_window')}")
        print(f"  bytes_in_flight={cong_stats.get('bytes_in_flight')}")
        print(f"  rtt={cong_stats.get('rtt')}")
        print(f"  max_data={flow_stats.get('max_data')}")
        print(f"  max_stream_data={flow_stats.get('max_stream_data')}")
        for key, value in cong_stats.items():
            if key.startswith("minbbr_"):
                print(f"  {key}={value}")
        print("___________________________________________\n")
        LOGGER.info("Client finished: %d streams, %d bytes sent, %d bytes received, %.2f s elapsed", streams, payload_size * streams, total_received, elapsed)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        out_path = os.path.join(cfg["metrics"]["output_dir"], f"minquic_client_{timestamp}.csv")
        metrics.dump_csv(out_path)
        print(f"[INFO] Metrics dumped to CSV: {out_path}")

def main():
    parser = argparse.ArgumentParser(description="QUIC client")
    parser.add_argument("--payload-size", type=int, help="Payload size in bytes")
    parser.add_argument("--streams", type=int, help="Number of streams")
    args = parser.parse_args()
    asyncio.run(run_client(args))


if __name__ == "__main__":
    main()
