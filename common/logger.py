"""Structured logger for the QUIC project.

Provides a `get_logger(name)` function that returns a `logging.Logger`
instance configured with a JSON formatter. The logger reads the log level
from the optional environment variable `QUIC_LOG_LEVEL` (defaults to
`INFO`).
"""

import logging
import json
import os
from datetime import datetime

class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_record = {
            "timestamp": datetime.utcfromtimestamp(record.created).isoformat() + "Z",
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            log_record["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(log_record)

def get_logger(name: str) -> logging.Logger:
    """Return a configured logger.

    The logger writes JSON‑encoded lines to `logs/<name>.log`. The log
    directory is created on first use. The log level can be overridden
    with the `QUIC_LOG_LEVEL` environment variable.
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        # Already configured
        return logger

    logger.setLevel(os.getenv("QUIC_LOG_LEVEL", "INFO"))
    logger.propagate = False

    # Ensure the logs directory exists
    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, f"{name}.log")

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(JsonFormatter())
    logger.addHandler(file_handler)

    # Also output to stdout for interactive use
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(JsonFormatter())
    logger.addHandler(stream_handler)

    return logger
