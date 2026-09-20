"""QUIC server implementation using aioquic.

Set ``MINQUIC_TRACE=1`` to write MINBBR's per-round trace for each connection
to ``<output_dir>/minquic_server_trace_<timestamp>.csv``: the server sends the
echo, so its congestion control is what limits the reverse direction.

The server reads configuration from ``config/config.yaml`` and starts a
QUIC listener on the specified host and port. It uses a simple echo
behaviour: data received on a stream is sent back unchanged. The server
records basic metrics (connection timestamps) via the shared metrics
collector.
"""
import asyncio
import os
from datetime import datetime
import subprocess
import yaml
from aioquic.asyncio import serve
from aioquic.quic.events import StreamDataReceived, ConnectionTerminated
from aioquic.asyncio import QuicConnectionProtocol

from .connection import create_quic_configuration
from .metrics import dump_trace, metrics
from .congestion import get_congestion_stats
from .flow_control import get_flow_control_limits
from common.logger import get_logger

LOGGER = get_logger("minquic.server")

def _kill_existing_udp_port(port: int) -> None:
    """Kill any process(es) bound to the given UDP port.
    Uses ``lsof -ti udp:<port>`` to locate PIDs and sends SIGKILL.
    If no process is found, does nothing.
    """
    try:
        output = subprocess.check_output(["lsof", "-ti", f"udp:{port}"], text=True)
        pids = [pid.strip() for pid in output.splitlines() if pid.strip()]
        for pid in pids:
            try:
                os.kill(int(pid), 9)
                LOGGER.info("Killed existing process PID %s using UDP port %s", pid, port)
            except Exception as exc:
                LOGGER.warning("Failed to kill PID %s: %s", pid, exc)
    except subprocess.CalledProcessError:
        # No process listening on the port.
        pass

class EchoQuicProtocol(QuicConnectionProtocol):
    """Protocol that echoes received data back to the client.

    The protocol is intentionally minimal – it demonstrates raw QUIC
    stream handling without any application‑level framing.
    """

    def quic_event_received(self, event):
        if isinstance(event, StreamDataReceived):
            # Echo the payload back on the same stream.
            self._quic.send_stream_data(
                event.stream_id, event.data, end_stream=event.end_stream
            )
            LOGGER.debug(
                "Echoed %d bytes on stream %d (end_stream=%s)",
                len(event.data),
                event.stream_id,
                event.end_stream,
            )
            print(f"[INFO] Echoed {len(event.data)} bytes on stream {event.stream_id} (end_stream={event.end_stream})")
        elif isinstance(event, ConnectionTerminated):
            # Record final congestion and flow control stats
            cong_stats = get_congestion_stats(self._quic)
            flow_stats = get_flow_control_limits(self._quic)
            metrics.record(
                event="connection_terminated",
                error_code=event.error_code,
                congestion_window=cong_stats.get("congestion_window"),
                bytes_in_flight=cong_stats.get("bytes_in_flight"),
                rtt=cong_stats.get("rtt"),
                max_data=flow_stats.get("max_data"),
                max_stream_data=flow_stats.get("max_stream_data"),
            )
            LOGGER.info("Connection terminated: error_code=%s", event.error_code)
            print(f"[INFO] Connection terminated: error_code={event.error_code}")
            print("[INFO] Final stats:")
            print(f"  congestion_window={cong_stats.get('congestion_window')}")
            print(f"  bytes_in_flight={cong_stats.get('bytes_in_flight')}")
            print(f"  rtt={cong_stats.get('rtt')}")
            print(f"  max_data={flow_stats.get('max_data')}")
            print(f"  max_stream_data={flow_stats.get('max_stream_data')}")
            if os.environ.get("MINQUIC_TRACE"):
                _dump_server_trace(self._quic)
                                                
def _dump_server_trace(connection) -> None:
    """Write this connection's MINBBR trace, for debugging the echo direction."""
    config_path = os.path.join(os.path.dirname(__file__), "..", "config", "config.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    path = os.path.join(cfg["metrics"]["output_dir"], f"minquic_server_trace_{timestamp}.csv")
    dump_trace(connection._loss._cc.trace, path)
    print(f"[INFO] MINBBR server trace dumped to CSV: {path}")

async def _run_server(cfg):
    server_cfg = cfg["server"]
    quic_cfg = create_quic_configuration(
        is_client=False,
        cert_path=server_cfg["cert_path"],
        key_path=server_cfg["key_path"],
    )
    host = server_cfg["host"]
    port = server_cfg["port"]
    print(f"[INFO] Using configuration: host={host}, port={port}")
    server = await serve(
        host=host,
        port=port,
        configuration=quic_cfg,
        create_protocol=EchoQuicProtocol,
    )
    print("[INFO] Server bound and listening")
    await asyncio.Future()


def main():
    # Load configuration file.
    config_path = os.path.join(os.path.dirname(__file__), "..", "config", "config.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
        print(f"[DEBUG] Loaded configuration from {config_path}")

    # Record start time metric.
    metrics.record(event="server_start", host=cfg["server"]["host"], port=cfg["server"]["port"])
    try:
        asyncio.run(_run_server(cfg))
    except KeyboardInterrupt:
        LOGGER.info("Server stopped by user")

if __name__ == "__main__":
    main()
