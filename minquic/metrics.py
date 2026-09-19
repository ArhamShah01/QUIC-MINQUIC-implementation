"""Central metrics collector.

The :class:`MetricsCollector` singleton records key performance indicators for a
single client run. Metrics are stored in memory and can be flushed to CSV or
JSON files for later analysis.
"""
import csv
import json
import os
import threading
from datetime import datetime
from typing import Dict, List, Any

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
        entry = {"timestamp": datetime.utcnow().isoformat() + "Z"}
        entry.update(kwargs)
        self._records.append(entry)

    def dump_csv(self, filepath: str) -> None:
        """Write all recorded metrics to a CSV file.
        """
        if not self._records:
            return
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", newline="", encoding="utf-8") as csvfile:
            fieldnames = set()
            for rec in self._records:
                fieldnames.update(rec.keys())
            fieldnames = list(fieldnames)
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

# Export a singleton instance for convenience.
metrics = MetricsCollector()
