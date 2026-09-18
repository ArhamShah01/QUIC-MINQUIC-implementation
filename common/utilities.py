"""Utility functions used across the QUIC project.

The module includes small helpers for byte conversion, timestamps and
human‑readable size formatting.
"""
import time
from datetime import datetime

def now_timestamp() -> str:
    """Return the current UTC timestamp in ISO‑8601 format."""
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

def bytes_to_human(num: int) -> str:
    """Convert a byte count into a human‑readable string.

    Examples
    --------
    >>> bytes_to_human(1024)
    '1.0 KiB'
    """
    step_unit = 1024
    units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"]
    for unit in units:
        if num < step_unit:
            return f"{num:.1f} {unit}" if unit != "B" else f"{num} {unit}"
        num /= step_unit
    return f"{num:.1f} PiB"

def human_to_bytes(text: str) -> int:
    """Parse a human‑readable size string back into an integer number of bytes.

    Supports the same unit suffixes as :func:`bytes_to_human`.
    """
    text = text.strip().lower()
    if text.endswith("b"):
        text = text[:-1]
    units = {
        "": 1,
        "k": 1024,
        "kb": 1024,
        "ki": 1024,
        "kib": 1024,
        "m": 1024 ** 2,
        "mb": 1024 ** 2,
        "mi": 1024 ** 2,
        "mib": 1024 ** 2,
        "g": 1024 ** 3,
        "gb": 1024 ** 3,
        "gi": 1024 ** 3,
        "gib": 1024 ** 3,
    }
    for suffix, factor in units.items():
        if text.endswith(suffix):
            number = float(text[: -len(suffix)]) if suffix else float(text)
            return int(number * factor)
    raise ValueError(f"Unable to parse size: {text}")
