#!/usr/bin/env python3
"""Teste do protocolo relay sem iniciar o ConectaPC.

Uso:
  1. Inicie relay_server.py em uma porta de laboratório com --allow-plain.
  2. Rode:
       python3 TESTAR_RELAY_LOCAL.py 127.0.0.1 45443

Este teste usa apenas tráfego artificial "HELLO/WORLD".
"""
import json
import socket
import sys
import threading
import time

HOST = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 45443


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


host_control = socket.create_connection((HOST, PORT), timeout=5)
sendj(host_control, {"mode": "control", "id": "123456789", "name": "PC-Teste"})
assert recvj(host_control).get("ok") is True

result = {}


def host_side():
    incoming = recvj(host_control)
    assert incoming.get("type") == "incoming"

    tunnel = socket.create_connection((HOST, PORT), timeout=5)
    sendj(tunnel, {
        "mode": "host_tunnel",
        "session": incoming["session"],
        "id": "123456789",
    })
    assert recvj(tunnel).get("ok") is True

    result["received"] = tunnel.recv(5)
    tunnel.sendall(b"WORLD")
    time.sleep(.1)
    tunnel.close()


threading.Thread(target=host_side, daemon=True).start()

controller = socket.create_connection((HOST, PORT), timeout=5)
sendj(controller, {
    "mode": "request",
    "target": "123456789",
    "controller": "Tecnico-Teste",
})
reply = recvj(controller)
assert reply.get("ok") is True, reply

controller.sendall(b"HELLO")
assert controller.recv(5) == b"WORLD"

for _ in range(20):
    if result.get("received") == b"HELLO":
        break
    time.sleep(.05)

assert result.get("received") == b"HELLO"

print("RELAY_OK: registro, rendezvous e túnel bidirecional funcionando.")

controller.close()
host_control.close()
