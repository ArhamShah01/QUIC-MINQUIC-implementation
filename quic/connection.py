"""QUIC connection helper.

Provides a function to build an ``aioquic`` :class:`~aioquic.quic.configuration.QuicConfiguration`
for both client and server roles. For the server, a self‑signed TLS
certificate is generated on‑the‑fly if the configured files are missing.
"""
import subprocess
from pathlib import Path
from aioquic.quic.configuration import QuicConfiguration
from common.logger import get_logger

LOGGER = get_logger("quic.connection")

def _generate_self_signed_cert(cert_path: Path, key_path: Path) -> None:
    """Generate a simple self‑signed certificate using OpenSSL.

    The command creates a RSA 2048‑bit certificate valid for 365 days with a
    subject of ``/CN=localhost``. ``openssl`` must be available in the environment.
    """
    try:
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-keyout",
                str(key_path),
                "-out",
                str(cert_path),
                "-days",
                "365",
                "-nodes",
                "-subj",
                "/CN=localhost",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        LOGGER.info("Generated self‑signed certificate at %s and key at %s", cert_path, key_path)
    except Exception as exc:
        LOGGER.error("Failed to generate self‑signed certificate: %s", exc)
        raise

def create_quic_configuration(is_client: bool, cert_path: str | None = None, key_path: str | None = None) -> QuicConfiguration:
    """Create and return a :class:`~aioquic.quic.configuration.QuicConfiguration`.

    Parameters
    ----------
    is_client:
        ``True`` for a client configuration, ``False`` for a server.
    cert_path, key_path:
        Paths to the TLS certificate and private key for the server role. They are
        ignored for the client configuration. If ``None`` and ``is_client`` is
        ``False``, the function expects the files to exist at the locations
        defined in the project's ``config.yaml``.
    """
    cfg = QuicConfiguration(is_client=is_client, alpn_protocols=["hq-29"])
    if not is_client:
        # Server mode – ensure we have a certificate and key.
        if not cert_path or not key_path:
            raise ValueError("cert_path and key_path must be provided for server configuration")
        cert_file = Path(cert_path)
        key_file = Path(key_path)
        # Generate certificate if missing.
        if not cert_file.is_file() or not key_file.is_file():
            cert_file.parent.mkdir(parents=True, exist_ok=True)
            _generate_self_signed_cert(cert_file, key_file)
        cfg.load_cert_chain(cert_file, key_file)
    else:
        # Client uses default TLS settings – no cert needed.
        pass
    return cfg
