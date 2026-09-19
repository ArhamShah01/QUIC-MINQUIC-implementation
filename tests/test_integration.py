import csv
import subprocess
import sys
import pathlib
import pytest
import asyncio
from quic import client as quic_client

@pytest.mark.asyncio
async def test_quic_integration(config):
    """Start the QUIC server, run the client, and verify metrics CSV output."""
    results_dir = pathlib.Path(config["metrics"]["output_dir"])
    existing = set(results_dir.glob("client_*.csv"))
    # Start the server as a subprocess.
    server_proc = subprocess.Popen([sys.executable, "-m", "quic.server"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        # Give the server a moment to start.
        await asyncio.sleep(0.5)
        # Run the client with a small payload and two streams.
        await quic_client.run_client()
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
