from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import os
import secrets
import struct
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from protocol import ProtocolError, recv_frame, send_frame


HANDSHAKE_VERSION = 1
HANDSHAKE_CONTEXT = b"ConectaPC-E2E-v1"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    value = str(value or "")
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _raw_public(key) -> bytes:
    if hasattr(key, "public_key"):
        key = key.public_key()
    return key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def fingerprint(public_key: str | bytes) -> str:
    raw = _unb64(public_key) if isinstance(public_key, str) else public_key
    digest = hashlib.sha256(raw).hexdigest().upper()[:20]
    return "-".join(digest[i:i + 4] for i in range(0, len(digest), 4))


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _dpapi_protect(data: bytes) -> str:
    if os.name != "nt":
        return "plain:" + _b64(data)
    buffer = ctypes.create_string_buffer(data)
    in_blob = _DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    out_blob = _DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    if not crypt32.CryptProtectData(ctypes.byref(in_blob), "ConectaPC", None, None, None, 0, ctypes.byref(out_blob)):
        raise OSError("Não foi possível proteger a identidade com o Windows DPAPI")
    try:
        protected = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        return "dpapi:" + _b64(protected)
    finally:
        kernel32.LocalFree(out_blob.pbData)


def _dpapi_unprotect(value: str) -> bytes:
    scheme, encoded = value.split(":", 1)
    protected = _unb64(encoded)
    if scheme == "plain" and os.name != "nt":
        return protected
    if scheme != "dpapi" or os.name != "nt":
        raise ValueError("Formato de segredo incompatível")
    buffer = ctypes.create_string_buffer(protected)
    in_blob = _DATA_BLOB(len(protected), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    out_blob = _DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    if not crypt32.CryptUnprotectData(ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)):
        raise OSError("Não foi possível abrir a identidade protegida")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


@dataclass
class DeviceIdentity:
    path: Path
    device_id: str
    private_key: Ed25519PrivateKey
    device_token: str = ""

    @property
    def public_key(self) -> str:
        return _b64(_raw_public(self.private_key))

    @property
    def display_fingerprint(self) -> str:
        return fingerprint(self.public_key)

    def save(self):
        raw_private = self.private_key.private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        )
        payload = {
            "version": 1,
            "device_id": self.device_id,
            "private_key": _dpapi_protect(raw_private),
            "public_key": self.public_key,
            "device_token": _dpapi_protect(self.device_token.encode("utf-8")) if self.device_token else "",
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(temp, self.path)

    def set_device_token(self, token: str):
        self.device_token = str(token or "")
        self.save()


def load_or_create_identity(folder: Path) -> DeviceIdentity:
    path = Path(folder) / "identity.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        device_id = str(data["device_id"])
        if len(device_id) != 9 or not device_id.isdigit():
            raise ValueError("Identidade local possui ID inválido")
        private = Ed25519PrivateKey.from_private_bytes(_dpapi_unprotect(data["private_key"]))
        token = _dpapi_unprotect(data["device_token"]).decode("utf-8") if data.get("device_token") else ""
        identity = DeviceIdentity(path, device_id, private, token)
        if data.get("public_key") != identity.public_key:
            raise ValueError("Identidade local foi alterada ou corrompida")
        return identity

    identity = DeviceIdentity(
        path=path,
        device_id=f"{secrets.randbelow(900_000_000) + 100_000_000:09d}",
        private_key=Ed25519PrivateKey.generate(),
    )
    identity.save()
    return identity


class KnownPeers:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()
        if not path.exists():
            self.items = {}
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ValueError("O arquivo de identidades conhecidas está corrompido") from exc
        if not isinstance(data, dict):
            raise ValueError("O arquivo de identidades conhecidas é inválido")
        self.items = data

    def expected(self, peer_id: str) -> str | None:
        with self.lock:
            item = self.items.get(str(peer_id))
            return str(item.get("public_key")) if isinstance(item, dict) and item.get("public_key") else None

    def matches(self, peer_id: str, public_key: str) -> bool:
        expected = self.expected(peer_id)
        return expected is None or secrets.compare_digest(expected, str(public_key))

    def remember(self, peer_id: str, public_key: str, label: str = ""):
        if len(_unb64(public_key)) != 32:
            raise ValueError("Chave pública inválida")
        with self.lock:
            existing = self.items.get(str(peer_id))
            if existing and not secrets.compare_digest(str(existing.get("public_key")), public_key):
                raise ProtocolError("A identidade conhecida deste computador mudou")
            self.items[str(peer_id)] = {
                "public_key": public_key,
                "fingerprint": fingerprint(public_key),
                "label": str(label or "")[:120],
                "first_seen": existing.get("first_seen") if isinstance(existing, dict) else int(time.time()),
                "last_seen": int(time.time()),
            }
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix(".tmp")
            temp.write_text(json.dumps(self.items, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temp, self.path)


def load_known_peers(folder: Path) -> KnownPeers:
    return KnownPeers(Path(folder) / "known_peers.json")


def _canonical_handshake(role: str, static_key: str, ephemeral_key: str, nonce: str) -> bytes:
    return b"|".join([
        HANDSHAKE_CONTEXT,
        role.encode("ascii"),
        static_key.encode("ascii"),
        ephemeral_key.encode("ascii"),
        nonce.encode("ascii"),
    ])


def _make_hello(identity: DeviceIdentity, ephemeral: X25519PrivateKey, role: str) -> dict:
    static_key = identity.public_key
    ephemeral_key = _b64(_raw_public(ephemeral))
    nonce = _b64(secrets.token_bytes(24))
    signed = _canonical_handshake(role, static_key, ephemeral_key, nonce)
    return {
        "version": HANDSHAKE_VERSION,
        "role": role,
        "static_key": static_key,
        "ephemeral_key": ephemeral_key,
        "nonce": nonce,
        "signature": _b64(identity.private_key.sign(signed)),
    }


def _validate_hello(message: dict, expected_role: str, expected_key: str | None) -> tuple[str, X25519PublicKey]:
    if message.get("version") != HANDSHAKE_VERSION or message.get("role") != expected_role:
        raise ProtocolError("Handshake E2E incompatível")
    static_key = str(message.get("static_key") or "")
    ephemeral_key = str(message.get("ephemeral_key") or "")
    nonce = str(message.get("nonce") or "")
    if expected_key and not secrets.compare_digest(static_key, expected_key):
        raise ProtocolError("A identidade do computador remoto não corresponde ao relay")
    try:
        static_raw = _unb64(static_key)
        ephemeral_raw = _unb64(ephemeral_key)
        signature = _unb64(message.get("signature") or "")
        if len(static_raw) != 32 or len(ephemeral_raw) != 32 or len(_unb64(nonce)) != 24:
            raise ValueError
        Ed25519PublicKey.from_public_bytes(static_raw).verify(
            signature,
            _canonical_handshake(expected_role, static_key, ephemeral_key, nonce),
        )
        return static_key, X25519PublicKey.from_public_bytes(ephemeral_raw)
    except Exception as exc:
        raise ProtocolError("Assinatura do handshake E2E inválida") from exc


class SecureChannel:
    def __init__(self, sock, send_key: bytes, recv_key: bytes, peer_public_key: str):
        self._sock = sock
        self._send_aead = ChaCha20Poly1305(send_key)
        self._recv_aead = ChaCha20Poly1305(recv_key)
        self._send_counter = 0
        self._recv_counter = 0
        self._counter_lock = threading.Lock()
        self.peer_public_key = peer_public_key
        self.peer_fingerprint = fingerprint(peer_public_key)

    def __getattr__(self, name):
        return getattr(self._sock, name)

    @staticmethod
    def _nonce(counter: int) -> bytes:
        return b"\x00\x00\x00\x00" + struct.pack("!Q", counter)

    def send_secure_frame(self, kind: bytes, payload: bytes, lock=None):
        if kind == b"E":
            raise ProtocolError("Frame E não pode ser encapsulado novamente")

        def send_once():
            with self._counter_lock:
                counter = self._send_counter
                self._send_counter += 1
            counter_bytes = struct.pack("!Q", counter)
            ciphertext = self._send_aead.encrypt(
                self._nonce(counter),
                bytes(kind) + payload,
                HANDSHAKE_CONTEXT + counter_bytes,
            )
            send_frame(self._sock, b"E", counter_bytes + ciphertext)

        if lock:
            with lock:
                send_once()
        else:
            send_once()

    def recv_secure_frame(self):
        kind, payload = recv_frame(self._sock)
        if kind != b"E" or len(payload) < 8 + 16 + 1:
            raise ProtocolError("Frame E2E inválido")
        counter = struct.unpack("!Q", payload[:8])[0]
        if counter != self._recv_counter:
            raise ProtocolError("Sequência E2E inválida ou repetida")
        counter_bytes = payload[:8]
        try:
            plaintext = self._recv_aead.decrypt(
                self._nonce(counter),
                payload[8:],
                HANDSHAKE_CONTEXT + counter_bytes,
            )
        except Exception as exc:
            raise ProtocolError("Autenticação E2E do frame falhou") from exc
        self._recv_counter += 1
        return plaintext[:1], plaintext[1:]


def _derive_keys(ephemeral, peer_ephemeral, controller_hello: dict, host_hello: dict) -> tuple[bytes, bytes]:
    shared = ephemeral.exchange(peer_ephemeral)
    transcript = json.dumps(
        {"controller": controller_hello, "host": host_hello},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    material = HKDF(
        algorithm=hashes.SHA256(),
        length=64,
        salt=hashlib.sha256(transcript).digest(),
        info=HANDSHAKE_CONTEXT,
    ).derive(shared)
    return material[:32], material[32:]


def open_secure_controller(sock, identity: DeviceIdentity, expected_peer_key: str | None = None) -> SecureChannel:
    ephemeral = X25519PrivateKey.generate()
    controller_hello = _make_hello(identity, ephemeral, "controller")
    send_frame(sock, b"H", json.dumps(controller_hello, separators=(",", ":")).encode("utf-8"))
    kind, payload = recv_frame(sock)
    if kind != b"H":
        raise ProtocolError("Resposta de handshake E2E ausente")
    host_hello = json.loads(payload.decode("utf-8"))
    peer_key, peer_ephemeral = _validate_hello(host_hello, "host", expected_peer_key)
    c2h, h2c = _derive_keys(ephemeral, peer_ephemeral, controller_hello, host_hello)
    return SecureChannel(sock, c2h, h2c, peer_key)


def open_secure_host(sock, identity: DeviceIdentity, expected_peer_key: str | None = None) -> SecureChannel:
    kind, payload = recv_frame(sock)
    if kind != b"H":
        raise ProtocolError("Handshake E2E ausente")
    controller_hello = json.loads(payload.decode("utf-8"))
    peer_key, peer_ephemeral = _validate_hello(controller_hello, "controller", expected_peer_key)
    ephemeral = X25519PrivateKey.generate()
    host_hello = _make_hello(identity, ephemeral, "host")
    send_frame(sock, b"H", json.dumps(host_hello, separators=(",", ":")).encode("utf-8"))
    c2h, h2c = _derive_keys(ephemeral, peer_ephemeral, controller_hello, host_hello)
    return SecureChannel(sock, h2c, c2h, peer_key)
