import json
import struct

HEADER = struct.Struct("!cI")


class ProtocolError(ConnectionError):
    pass


# Limites aplicados antes de qualquer alocação. O frame E contém um frame
# interno criptografado e por isso recebe a pequena margem do AEAD.
MAX_FRAME_BY_KIND = {
    b"J": 256 * 1024,
    b"H": 64 * 1024,
    b"S": 12 * 1024 * 1024,
    b"U": 1024 * 1024,
    b"D": 1024 * 1024,
    b"E": 12 * 1024 * 1024 + 64,
}

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
    kind = bytes(kind)
    limit = MAX_FRAME_BY_KIND.get(kind)
    if limit is None:
        raise ProtocolError("Tipo de frame não permitido")
    if len(payload) > limit:
        raise ProtocolError("Frame excede o limite permitido")
    secure_sender = getattr(sock, "send_secure_frame", None)
    if secure_sender:
        return secure_sender(kind, payload, lock)
    packet = HEADER.pack(kind, len(payload)) + payload
    if lock:
        with lock:
            sock.sendall(packet)
    else:
        sock.sendall(packet)

def recv_frame(sock):
    secure_receiver = getattr(sock, "recv_secure_frame", None)
    if secure_receiver:
        kind, payload = secure_receiver()
        size = len(payload)
    else:
        header = recv_exact(sock, HEADER.size)
        kind, size = HEADER.unpack(header)
        payload = None
    limit = MAX_FRAME_BY_KIND.get(kind)
    if limit is None:
        raise ProtocolError("Tipo de frame não permitido")
    if size > limit:
        raise ProtocolError("Frame excede o limite permitido")
    return kind, payload if payload is not None else recv_exact(sock, size)

def send_json(sock, obj, lock=None):
    payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    send_frame(sock, b"J", payload, lock)

def recv_json_payload(payload):
    return json.loads(payload.decode("utf-8"))
