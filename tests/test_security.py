import json
import socket
import struct
import tempfile
import threading
import unittest
from pathlib import Path

from protocol import HEADER, ProtocolError, recv_frame, recv_json_payload, send_json
from security import load_known_peers, load_or_create_identity, open_secure_controller, open_secure_host
from server.security_store import SecurityStore, totp_code


class BufferSocket:
    def __init__(self, data):
        self.data = bytearray(data)

    def recv(self, size):
        if not self.data:
            return b""
        chunk = bytes(self.data[:size])
        del self.data[:size]
        return chunk


class RecordingSocket:
    def __init__(self, sock, recording):
        self.sock = sock
        self.recording = recording

    def sendall(self, data):
        self.recording.extend(data)
        return self.sock.sendall(data)

    def __getattr__(self, name):
        return getattr(self.sock, name)


class ProtocolTests(unittest.TestCase):
    def test_oversized_frame_is_rejected_before_payload_read(self):
        sock = BufferSocket(HEADER.pack(b"J", 256 * 1024 + 1))
        with self.assertRaises(ProtocolError):
            recv_frame(sock)


class EndToEndTests(unittest.TestCase):
    def test_identity_is_persistent_and_secure_channel_round_trips(self):
        with tempfile.TemporaryDirectory() as root:
            controller_identity = load_or_create_identity(Path(root) / "controller")
            host_identity = load_or_create_identity(Path(root) / "host")
            self.assertEqual(
                controller_identity.public_key,
                load_or_create_identity(Path(root) / "controller").public_key,
            )
            controller_raw, host_raw = socket.socketpair()
            wire = bytearray()
            controller_sock = RecordingSocket(controller_raw, wire)
            host_sock = RecordingSocket(host_raw, wire)
            received = {}

            def host_side():
                secure = open_secure_host(
                    host_sock, host_identity, controller_identity.public_key
                )
                kind, payload = recv_frame(secure)
                received["message"] = recv_json_payload(payload)
                send_json(secure, {"ok": True})
                secure.close()

            thread = threading.Thread(target=host_side)
            thread.start()
            secure_controller = open_secure_controller(
                controller_sock, controller_identity, host_identity.public_key
            )
            send_json(secure_controller, {"secret": "não aparece no relay"})
            kind, payload = recv_frame(secure_controller)
            self.assertEqual(kind, b"J")
            self.assertEqual(recv_json_payload(payload), {"ok": True})
            secure_controller.close()
            thread.join(5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(received["message"]["secret"], "não aparece no relay")
            self.assertNotIn("não aparece no relay".encode("utf-8"), wire)

    def test_known_identity_change_is_blocked(self):
        with tempfile.TemporaryDirectory() as root:
            first = load_or_create_identity(Path(root) / "first")
            second = load_or_create_identity(Path(root) / "second")
            known = load_known_peers(Path(root) / "console")
            known.remember("target:123456789", first.public_key, "PC")
            self.assertTrue(known.matches("target:123456789", first.public_key))
            self.assertFalse(known.matches("target:123456789", second.public_key))


class SecurityStoreTests(unittest.TestCase):
    def test_enrollment_mfa_access_and_audit(self):
        with tempfile.TemporaryDirectory() as root:
            store = SecurityStore(Path(root) / "relay.db")
            secret = store.add_technician("tecnico", "Técnico Teste", "uma-senha-forte-123")
            enrollment = store.create_enrollment("PC Cliente")
            device_token = store.enroll_device(
                enrollment, "123456789", "A" * 43, "PC Cliente"
            )
            self.assertTrue(device_token)
            self.assertTrue(store.authenticate_device("123456789", "A" * 43, device_token))
            login = store.authenticate_technician(
                "tecnico", "uma-senha-forte-123", totp_code(secret),
                "123456789", "A" * 43,
            )
            self.assertTrue(login)
            access_token, display_name = login
            self.assertEqual(display_name, "Técnico Teste")
            self.assertEqual(
                store.validate_access(access_token, "123456789", "A" * 43)["username"],
                "tecnico",
            )
            store.audit("test_event", actor="tecnico", target="123456789", source="127.0.0.1")
            row = store.db.execute("SELECT * FROM audit_events WHERE event='test_event'").fetchone()
            self.assertTrue(row["source_hash"])
            self.assertNotIn("127.0.0.1", row["source_hash"])
            store.close()


if __name__ == "__main__":
    unittest.main()
