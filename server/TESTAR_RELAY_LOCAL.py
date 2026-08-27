#!/usr/bin/env python3
"""Teste autenticado do relay usando tráfego artificial HELLO/WORLD.

O modo padrão continua atendendo o laboratório local sem TLS. Para validar a
implantação real, execute este script na VPS com ``--tls``, usando o mesmo banco
do serviço e o domínio público como host/server-name.
"""
from __future__ import annotations

import argparse
import base64
import json
import secrets
import socket
import ssl
import threading
import time
from pathlib import Path

try:
    from .security_store import SecurityStore, totp_code
except ImportError:
    from security_store import SecurityStore, totp_code


def sendj(sock, obj):
    sock.sendall((json.dumps(obj) + "\n").encode("utf-8"))


def recvj(sock):
    data = bytearray()
    while True:
        ch = sock.recv(1)
        if not ch:
            raise ConnectionError("conexão encerrada")
        if ch == b"\n":
            return json.loads(data.decode("utf-8"))
        data.extend(ch)


def random_id():
    return f"{secrets.randbelow(900_000_000) + 100_000_000:09d}"


def public_key():
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii").rstrip("=")


class RelayConnector:
    def __init__(self, host, port, *, use_tls=False, server_name="", ca_file=""):
        self.host = host
        self.port = port
        self.use_tls = use_tls
        self.server_name = server_name or host
        self.ca_file = ca_file
        self.context = ssl.create_default_context(cafile=ca_file or None) if use_tls else None

    def connect(self):
        raw = socket.create_connection((self.host, self.port), timeout=5)
        if not self.context:
            return raw
        try:
            return self.context.wrap_socket(raw, server_hostname=self.server_name)
        except Exception:
            raw.close()
            raise


def provision(db_path):
    store = SecurityStore(db_path)
    host_id, controller_id = random_id(), random_id()
    host_key, controller_key = public_key(), public_key()
    host_token = store.enroll_device(
        store.create_enrollment("Host de teste"), host_id, host_key, "Host de teste"
    )
    controller_token = store.enroll_device(
        store.create_enrollment("Console de teste"), controller_id,
        controller_key, "Console de teste",
    )
    username = "teste-" + secrets.token_hex(4)
    password = "senha-local-forte-" + secrets.token_hex(8)
    totp_secret = store.add_technician(username, "Técnico de Teste", password)
    store.close()
    return {
        "host_id": host_id, "host_key": host_key, "host_token": host_token,
        "controller_id": controller_id, "controller_key": controller_key,
        "controller_token": controller_token, "username": username,
        "password": password, "otp": totp_code(totp_secret),
    }


def register(connector, device_id, key, token, name):
    control = connector.connect()
    sendj(control, {
        "mode": "control", "id": device_id, "name": name,
        "public_key": key, "device_token": token,
    })
    reply = recvj(control)
    assert reply.get("ok") is True, reply
    return control


def run(host, port, db_path, *, use_tls=False, server_name="", ca_file=""):
    connector = RelayConnector(
        host, port, use_tls=use_tls, server_name=server_name, ca_file=ca_file
    )
    c = provision(db_path)
    host_control = register(
        connector, c["host_id"], c["host_key"], c["host_token"], "PC-Teste"
    )
    controller_control = register(
        connector, c["controller_id"], c["controller_key"],
        c["controller_token"], "Console-Teste"
    )

    login = connector.connect()
    sendj(login, {
        "mode": "login", "controller_id": c["controller_id"], "username": c["username"],
        "password": c["password"], "otp": c["otp"],
    })
    login_reply = recvj(login)
    login.close()
    assert login_reply.get("ok") is True, login_reply
    result = {}

    def host_side():
        incoming = recvj(host_control)
        assert incoming.get("type") == "incoming"
        assert incoming.get("controller_key") == c["controller_key"]
        tunnel = connector.connect()
        sendj(tunnel, {
            "mode": "host_tunnel", "session": incoming["session"], "id": c["host_id"],
            "public_key": c["host_key"], "device_token": c["host_token"],
        })
        assert recvj(tunnel).get("ok") is True
        result["received"] = tunnel.recv(5)
        tunnel.sendall(b"WORLD")
        time.sleep(.1)
        tunnel.close()

    thread = threading.Thread(target=host_side, daemon=True)
    thread.start()
    controller = connector.connect()
    sendj(controller, {
        "mode": "request", "target": c["host_id"], "controller_id": c["controller_id"],
        "access_token": login_reply["access_token"],
    })
    reply = recvj(controller)
    assert reply.get("ok") is True, reply
    assert reply.get("target_key") == c["host_key"]
    controller.sendall(b"HELLO")
    assert controller.recv(5) == b"WORLD"
    thread.join(3)
    assert result.get("received") == b"HELLO"
    controller.close()
    host_control.close()
    controller_control.close()
    transport = "TLS verificado" if use_tls else "TCP sem TLS (laboratório)"
    print(
        "RELAY_OK: dispositivos, MFA, autorização, identidades e túnel funcionando. "
        f"Transporte: {transport}."
    )


def main():
    parser = argparse.ArgumentParser(description="Valida autenticação e túnel do ConectaPC Relay")
    parser.add_argument("host", nargs="?", default="127.0.0.1")
    parser.add_argument("port", nargs="?", type=int, default=45443)
    parser.add_argument("db_path", nargs="?", type=Path, default=Path("relay-test.db"))
    parser.add_argument("--tls", action="store_true", help="exige TLS e valida o certificado")
    parser.add_argument("--server-name", default="", help="nome DNS esperado no certificado")
    parser.add_argument("--ca-file", default="", help="CA adicional para laboratório TLS")
    args = parser.parse_args()
    if (args.server_name and not args.tls):
        parser.error("--server-name exige --tls")
    if args.ca_file and not args.tls:
        parser.error("--ca-file exige --tls")
    if args.ca_file and not Path(args.ca_file).is_file():
        parser.error("arquivo informado em --ca-file não existe")
    run(
        args.host,
        args.port,
        args.db_path,
        use_tls=args.tls,
        server_name=args.server_name,
        ca_file=args.ca_file,
    )


if __name__ == "__main__":
    main()
