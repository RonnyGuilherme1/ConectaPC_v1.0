#!/usr/bin/env python3
"""Teste autenticado do relay usando tráfego artificial HELLO/WORLD.

Inicie o relay com --allow-plain e --db apontando para um banco temporário;
depois passe host, porta e o mesmo caminho do banco a este script.
"""
from __future__ import annotations

import base64
import json
import secrets
import socket
import sys
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


def register(host, port, device_id, key, token, name):
    control = socket.create_connection((host, port), timeout=5)
    sendj(control, {
        "mode": "control", "id": device_id, "name": name,
        "public_key": key, "device_token": token,
    })
    reply = recvj(control)
    assert reply.get("ok") is True, reply
    return control


def run(host, port, db_path):
    c = provision(db_path)
    host_control = register(host, port, c["host_id"], c["host_key"], c["host_token"], "PC-Teste")
    controller_control = register(
        host, port, c["controller_id"], c["controller_key"], c["controller_token"], "Console-Teste"
    )

    login = socket.create_connection((host, port), timeout=5)
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
        tunnel = socket.create_connection((host, port), timeout=5)
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
    controller = socket.create_connection((host, port), timeout=5)
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
    print("RELAY_OK: dispositivos, MFA, autorização, identidades e túnel funcionando.")


def main():
    host = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 45443
    db_path = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("relay-test.db")
    run(host, port, db_path)


if __name__ == "__main__":
    main()
