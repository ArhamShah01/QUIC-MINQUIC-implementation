import subprocess
import sys
import time
import pathlib
import pytest
import asyncio
from quic import client as quic_client

@pytest.mark.asyncio
async def test_quic_integration(tmp_path, config):
    """Start the QUIC server, run the client, and verify metrics CSV output."""
    # Start the server as a subprocess.
    server_proc = subprocess.Popen([sys.executable, "-m", "quic.server"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        # Give the server a moment to start.
        await asyncio.sleep(0.5)
        # Run the client with a small payload and two streams.
        await quic_client.run_client()
        # Allow a brief moment for the metrics file to be flushed.
        await asyncio.sleep(0.2)
        # Verify that a CSV file was created in the results directory.
        results_dir = pathlib.Path(config["metrics"]["output_dir"])
        csv_files = sorted(results_dir.glob("client_*.csv"))
        assert csv_files, "No client metric CSV file was generated"
        latest_csv = csv_files[-1]
        # Check that the CSV contains non‑zero bytes sent/received.
        content = latest_csv.read_text()
        assert "bytes_sent" in content
        assert "bytes_received" in content
        # Simple sanity check: those fields should have values > 0.
        # Parse CSV lines to verify.
        lines = content.strip().splitlines()
        header = lines[0].split(',')
        row = lines[1].split(',')
        data = dict(zip(header, row))
        assert int(data.get('bytes_sent', 0)) > 0
        assert int(data.get('bytes_received', 0)) > 0
    finally:
        # Terminate the server process.
        server_proc.terminate()
        try:
            server_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server_proc.kill()
