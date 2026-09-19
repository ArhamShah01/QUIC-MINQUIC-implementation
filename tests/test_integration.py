import csv
import subprocess
import sys
import pathlib
import pytest
import asyncio
import importlib

@pytest.mark.asyncio
@pytest.mark.parametrize("package", ["quic", "minquic"])
async def test_quic_integration(config, package):
    """Start the server, run the client, and verify metrics CSV output."""
    client = importlib.import_module(f"{package}.client")
    results_dir = pathlib.Path(config["metrics"]["output_dir"])
    existing = set(results_dir.glob("client_*.csv"))
    # Start the server as a subprocess.
    server_proc = subprocess.Popen([sys.executable, "-m", f"{package}.server"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        # Give the server a moment to start.
        await asyncio.sleep(0.5)
        # Run the client with a small payload and two streams.
        await client.run_client()
        # Allow a brief moment for the metrics file to be flushed.
        await asyncio.sleep(0.2)
        # Verify that a new CSV file was created in the results directory.
        new_csvs = sorted(set(results_dir.glob("client_*.csv")) - existing)
        assert new_csvs, "No client metric CSV file was generated"
        with new_csvs[-1].open(newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        # The first row is ``client_start``; byte counts are on ``client_complete``.
        complete = [r for r in rows if r["event"] == "client_complete"]
        assert complete, "No client_complete event recorded"
        assert int(complete[-1]["bytes_sent"]) > 0
        assert int(complete[-1]["bytes_received"]) > 0
        # Stats must come from the live connection, not placeholder defaults.
        assert int(complete[-1]["congestion_window"]) > 0
        assert float(complete[-1]["rtt"]) > 0
        assert int(complete[-1]["max_data"]) > 0
        assert int(complete[-1]["max_stream_data"]) > 0
        if package == "minquic":
            assert complete[-1]["minbbr_state"] in {"STARTUP", "PROBE_BW", "PROBE_RTT", "DRAIN"}
    finally:
        # Terminate the server process.
        server_proc.terminate()
        try:
            server_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server_proc.kill()
        # Don't leave test output behind in the results directory.
        for path in set(results_dir.glob("client_*.csv")) - existing:
            path.unlink()
