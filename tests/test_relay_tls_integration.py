import datetime
import ipaddress
import os
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from server.TESTAR_RELAY_LOCAL import run


def create_test_certificate(root):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_path = root / "relay.crt"
    key_path = root / "relay.key"
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return cert_path, key_path


def reserve_port():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


class RelayTlsIntegrationTests(unittest.TestCase):
    def test_authenticated_tunnel_works_over_verified_tls(self):
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            cert_path, key_path = create_test_certificate(root)
            db_path = root / "relay.db"
            port = reserve_port()
            command = [
                sys.executable,
                "server/relay_server.py",
                "--host", "127.0.0.1",
                "--port", str(port),
                "--cert", str(cert_path),
                "--key", str(key_path),
                "--db", str(db_path),
            ]
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            process = subprocess.Popen(
                command,
                cwd=Path(__file__).resolve().parents[1],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                creationflags=creationflags,
            )
            try:
                context = ssl.create_default_context(cafile=str(cert_path))
                deadline = time.monotonic() + 8
                while True:
                    if process.poll() is not None:
                        self.fail(f"relay encerrou antes do teste: {process.stdout.read()}")
                    try:
                        with socket.create_connection(("127.0.0.1", port), timeout=.5) as raw:
                            with context.wrap_socket(raw, server_hostname="localhost"):
                                break
                    except (ConnectionError, OSError, ssl.SSLError):
                        if time.monotonic() >= deadline:
                            self.fail("relay TLS não ficou pronto em 8 segundos")
                        time.sleep(.1)

                run(
                    "127.0.0.1",
                    port,
                    db_path,
                    use_tls=True,
                    server_name="localhost",
                    ca_file=str(cert_path),
                )
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                if process.stdout:
                    process.stdout.close()
                # O Windows pode manter o handle do SQLite por um instante após
                # TerminateProcess; aguarde antes de o TemporaryDirectory limpar.
                time.sleep(.2)


if __name__ == "__main__":
    unittest.main()
