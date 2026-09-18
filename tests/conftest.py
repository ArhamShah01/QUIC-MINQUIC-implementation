"""Pytest fixtures for the QUIC baseline.

Currently the test suite provides simple sanity checks – it ensures that the
configuration can be loaded and that the client module imports without error.
More comprehensive integration tests can be added later.
"""
import os
import pytest
import yaml

@pytest.fixture(scope="session")
def config():
    """Load the project's configuration file.
    """
    config_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "config", "config.yaml")
    )
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)
