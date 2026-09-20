"""Central metrics collector.

The :class:`MetricsCollector` singleton records key performance indicators for a
single client run. Metrics are stored in memory and can be flushed to CSV or
JSON files for later analysis.
"""
import csv
import json
import os
import threading
from datetime import datetime, timezone
from typing import Any

class MetricsCollector:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls) -> "MetricsCollector":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._records = []  # type: List[Dict[str, Any]]
            return cls._instance

    def record(self, **kwargs: Any) -> None:
        """Record a metric dictionary.

        Typical keys include:
        ``event``, ``timestamp``, ``value`` and any custom fields.
        """
        entry = {"timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")}
        entry.update(kwargs)
        self._records.append(entry)

    def dump_csv(self, filepath: str) -> None:
        """Write all recorded metrics to a CSV file.
        """
        if not self._records:
            return
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", newline="", encoding="utf-8") as csvfile:
            # Columns in first-seen order, so every run has the same layout.
            fieldnames = []
            for rec in self._records:
                fieldnames.extend(k for k in rec if k not in fieldnames)
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            for rec in self._records:
                writer.writerow(rec)

    def dump_json(self, filepath: str) -> None:
        """Write all recorded metrics to a JSON file.
        """
        if not self._records:
            return
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self._records, f, indent=2)

    def clear(self) -> None:
        """Empty the collector for a fresh run.
        """
        self._records.clear()

def dump_trace(rows: list, filepath: str) -> None:
    """Write a MINBBR per-round trace (one row per round trip) to CSV."""
    if not rows:
        return
    os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

# Export a singleton instance for convenience.
metrics = MetricsCollector()
