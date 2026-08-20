import json
import struct

HEADER = struct.Struct("!cI")

def recv_exact(sock, n):
    data = bytearray()
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise ConnectionError("Conexão encerrada")
        data.extend(chunk)
    return bytes(data)

def send_frame(sock, kind, payload, lock=None):
    if not isinstance(kind, (bytes, bytearray)) or len(kind) != 1:
        raise ValueError("kind deve ter exatamente 1 byte")
    packet = HEADER.pack(bytes(kind), len(payload)) + payload
    if lock:
        with lock:
            sock.sendall(packet)
    else:
        sock.sendall(packet)

def recv_frame(sock):
    header = recv_exact(sock, HEADER.size)
    kind, size = HEADER.unpack(header)
    return kind, recv_exact(sock, size)

def send_json(sock, obj, lock=None):
    payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    send_frame(sock, b"J", payload, lock)

def recv_json_payload(payload):
    return json.loads(payload.decode("utf-8"))
