#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import base64
from collections import defaultdict, deque
import hashlib
import json
import secrets
import signal
import ssl
import time
from dataclasses import dataclass, field

from security_store import SecurityStore


MAX_LINE = 64 * 1024
TUNNEL_TIMEOUT = 20
BUFFER_SIZE = 128 * 1024
MAX_ACTIVE_SESSIONS_PER_DEVICE = 8


async def read_json_line(reader: asyncio.StreamReader):
    data = await reader.readline()
    if not data:
        raise ConnectionError("connection closed")
    if len(data) > MAX_LINE:
        raise ValueError("control line too large")
    msg = json.loads(data.decode("utf-8"))
    if not isinstance(msg, dict):
        raise ValueError("control message must be an object")
    return msg


async def send_json(writer: asyncio.StreamWriter, obj, lock=None):
    data = (json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    if lock:
        async with lock:
            writer.write(data)
            await writer.drain()
    else:
        writer.write(data)
        await writer.drain()


def valid_id(value):
    value = str(value or "")
    return len(value) == 9 and value.isdigit()


def valid_public_key(value):
    try:
        value = str(value or "")
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        return len(raw) == 32
    except Exception:
        return False


class RateLimiter:
    def __init__(self):
        self.events = defaultdict(deque)

    def allow(self, key, limit, window):
        now = time.monotonic()
        bucket = self.events[key]
        while bucket and bucket[0] <= now - window:
            bucket.popleft()
        if len(bucket) >= limit:
            return False
        bucket.append(now)
        return True


@dataclass
class Peer:
    sid: str
    name: str
    public_key: str
    writer: asyncio.StreamWriter
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    connected_at: float = field(default_factory=time.time)


@dataclass
class RelaySession:
    token: str
    target_id: str
    controller_name: str
    controller_id: str
    controller_public_key: str
    technician_username: str
    controller_reader: asyncio.StreamReader
    controller_writer: asyncio.StreamWriter
    target_name: str
    host_reader: asyncio.StreamReader | None = None
    host_writer: asyncio.StreamWriter | None = None
    host_ready: asyncio.Event = field(default_factory=asyncio.Event)
    done: asyncio.Event = field(default_factory=asyncio.Event)


class RelayServer:
    def __init__(self, security_db, audit_retention_days=90):
        self.peers: dict[str, Peer] = {}
        self.sessions: dict[str, RelaySession] = {}
        self.lock = asyncio.Lock()
        self.limiter = RateLimiter()
        self.security = SecurityStore(security_db)
        self.security.purge_audit(audit_retention_days)

    async def handle(self, reader, writer):
        addr = writer.get_extra_info("peername")
        source = str(addr[0]) if addr else "unknown"
        try:
            if not self.limiter.allow(("connection", source), 120, 60):
                await send_json(writer, {"ok": False, "error": "limite temporário de conexões excedido"})
                return
            hello = await asyncio.wait_for(read_json_line(reader), timeout=10)
            mode = hello.get("mode")

            if mode == "control":
                await self.handle_control(reader, writer, hello, source)
            elif mode == "request":
                await self.handle_request(reader, writer, hello, source)
            elif mode == "host_tunnel":
                await self.handle_host_tunnel(reader, writer, hello, source)
            elif mode == "login":
                await self.handle_login(writer, hello, source)
            elif mode == "audit":
                await self.handle_audit(writer, hello, source)
            else:
                await send_json(writer, {"ok": False, "error": "modo inválido"})
        except asyncio.TimeoutError:
            pass
        except Exception as exc:
            print(f"[WARN] {addr}: {exc}")
            try:
                await send_json(writer, {"ok": False, "error": "erro de protocolo"})
            except Exception:
                pass
        finally:
            # Cada handler que assume a conexão cuida do fechamento.
            if not writer.is_closing():
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass

    async def handle_control(self, reader, writer, hello, source):
        sid = str(hello.get("id") or "")
        name = str(hello.get("name") or "Computador")[:120]
        public_key = str(hello.get("public_key") or "")

        if not valid_id(sid) or not valid_public_key(public_key):
            await send_json(writer, {"ok": False, "error": "identidade de dispositivo inválida"})
            return

        device_token = str(hello.get("device_token") or "")
        issued_token = ""
        if not device_token:
            enrollment = str(hello.get("enrollment_token") or "")
            if enrollment and self.limiter.allow(("enrollment", source), 8, 3600):
                issued_token = self.security.enroll_device(enrollment, sid, public_key, name) or ""
                device_token = issued_token
        if not device_token or not self.security.authenticate_device(sid, public_key, device_token):
            self.security.audit("device_auth_failed", target=sid, source=source)
            await send_json(writer, {"ok": False, "error": "dispositivo não cadastrado ou credencial inválida"})
            return

        peer = Peer(sid=sid, name=name, public_key=public_key, writer=writer)

        async with self.lock:
            existing = self.peers.get(sid)
            if existing and not existing.writer.is_closing():
                await send_json(writer, {"ok": False, "error": "ID já está online"})
                return
            self.peers[sid] = peer

        self.security.audit("device_online", actor=sid, source=source)
        print(f"[ONLINE] dispositivo autenticado | total={len(self.peers)}")
        reply = {"ok": True, "type": "registered"}
        if issued_token:
            reply["device_token"] = issued_token
        await send_json(writer, reply)

        try:
            while True:
                msg = await read_json_line(reader)
                if msg.get("type") == "ping":
                    await send_json(writer, {"type": "pong"}, peer.lock)
        finally:
            async with self.lock:
                if self.peers.get(sid) is peer:
                    self.peers.pop(sid, None)
            print(f"[OFFLINE] dispositivo desconectado | total={len(self.peers)}")
            self.security.audit("device_offline", actor=sid, source=source)

    async def handle_login(self, writer, hello, source):
        if not self.limiter.allow(("login", source), 5, 300):
            await send_json(writer, {"ok": False, "error": "muitas tentativas; aguarde cinco minutos"})
            return
        username = str(hello.get("username") or "").strip().lower()
        if not self.limiter.allow(("login_user", username), 5, 300):
            await send_json(writer, {"ok": False, "error": "muitas tentativas; aguarde cinco minutos"})
            return
        controller_id = str(hello.get("controller_id") or "")
        async with self.lock:
            controller_peer = self.peers.get(controller_id)
        if not controller_peer or controller_peer.writer.is_closing():
            await send_json(writer, {"ok": False, "error": "console técnico não está registrado"})
            return
        result = self.security.authenticate_technician(
            username,
            str(hello.get("password") or ""),
            str(hello.get("otp") or ""),
            controller_id,
            controller_peer.public_key,
        )
        if not result:
            self.security.audit("technician_login_failed", actor=username, source=source)
            await send_json(writer, {"ok": False, "error": "usuário, senha ou MFA inválido"})
            return
        access_token, display_name = result
        self.security.audit("technician_login", actor=username, source=source)
        await send_json(writer, {
            "ok": True,
            "access_token": access_token,
            "display_name": display_name,
            "expires_in": 900,
        })

    async def handle_request(self, reader, writer, hello, source):
        target_id = str(hello.get("target") or "")
        controller_id = str(hello.get("controller_id") or "")

        if not valid_id(target_id):
            await send_json(writer, {"ok": False, "error": "ID de destino inválido"})
            return

        async with self.lock:
            target = self.peers.get(target_id)
            controller_peer = self.peers.get(controller_id)

        if not target or target.writer.is_closing():
            await send_json(writer, {"ok": False, "error": "ID offline ou inexistente"})
            return
        if not controller_peer or controller_peer.writer.is_closing():
            await send_json(writer, {"ok": False, "error": "console técnico offline"})
            return
        access = self.security.validate_access(
            str(hello.get("access_token") or ""), controller_id, controller_peer.public_key
        )
        if not access:
            await send_json(writer, {"ok": False, "error": "sessão do técnico expirada; entre novamente"})
            return
        if not self.limiter.allow(("request", controller_id), 20, 60):
            await send_json(writer, {"ok": False, "error": "limite temporário de solicitações excedido"})
            return
        active_count = sum(
            1 for item in self.sessions.values()
            if item.controller_id == controller_id or item.target_id == target_id
        )
        if active_count >= MAX_ACTIVE_SESSIONS_PER_DEVICE:
            await send_json(writer, {"ok": False, "error": "limite de sessões simultâneas atingido"})
            return

        controller = str(access["display_name"])[:120]

        token = secrets.token_urlsafe(32)
        session = RelaySession(
            token=token,
            target_id=target_id,
            controller_name=controller,
            controller_id=controller_id,
            controller_public_key=controller_peer.public_key,
            technician_username=access["username"],
            controller_reader=reader,
            controller_writer=writer,
            target_name=target.name,
        )

        async with self.lock:
            self.sessions[token] = session

        try:
            try:
                await send_json(
                    target.writer,
                    {
                        "type": "incoming",
                        "session": token,
                        "controller": controller,
                        "controller_id": controller_id,
                        "controller_key": controller_peer.public_key,
                    },
                    target.lock,
                )
            except Exception:
                await send_json(writer, {"ok": False, "error": "ID ficou offline"})
                return

            try:
                await asyncio.wait_for(session.host_ready.wait(), timeout=TUNNEL_TIMEOUT)
            except asyncio.TimeoutError:
                await send_json(writer, {"ok": False, "error": "computador remoto não respondeu ao relay"})
                return

            if not session.host_reader or not session.host_writer:
                await send_json(writer, {"ok": False, "error": "falha ao preparar túnel"})
                return

            await send_json(
                writer,
                {
                    "ok": True,
                    "type": "tunnel_ready",
                    "target_name": session.target_name,
                    "target_key": target.public_key,
                    "session": token,
                },
            )

            print("[SESSION] sessão autenticada iniciada")
            self.security.audit(
                "session_started", actor=session.technician_username, target=target_id,
                source=source, detail={"controller_id": controller_id},
            )

            await self.relay_bidirectional(
                reader,
                writer,
                session.host_reader,
                session.host_writer,
            )

        finally:
            self.security.audit(
                "session_ended", actor=session.technician_username, target=target_id,
                source=source, detail={"controller_id": controller_id},
            )
            session.done.set()
            async with self.lock:
                self.sessions.pop(token, None)
            if session.host_writer and not session.host_writer.is_closing():
                session.host_writer.close()
                try:
                    await session.host_writer.wait_closed()
                except Exception:
                    pass

    async def handle_host_tunnel(self, reader, writer, hello, source):
        token = str(hello.get("session") or "")
        sid = str(hello.get("id") or "")
        public_key = str(hello.get("public_key") or "")
        device_token = str(hello.get("device_token") or "")

        async with self.lock:
            session = self.sessions.get(token)

        if not session:
            await send_json(writer, {"ok": False, "error": "sessão expirada"})
            return

        if sid != session.target_id:
            await send_json(writer, {"ok": False, "error": "ID não corresponde à sessão"})
            return
        if not self.security.authenticate_device(sid, public_key, device_token):
            await send_json(writer, {"ok": False, "error": "credencial do dispositivo inválida"})
            return

        if session.host_writer is not None:
            await send_json(writer, {"ok": False, "error": "túnel já conectado"})
            return

        session.host_reader = reader
        session.host_writer = writer

        await send_json(writer, {"ok": True, "type": "host_tunnel_ready"})
        session.host_ready.set()

        # Quem faz o relay é handle_request. Este handler mantém a conexão viva.
        await session.done.wait()

    async def handle_audit(self, writer, hello, source):
        sid = str(hello.get("id") or "")
        public_key = str(hello.get("public_key") or "")
        token = str(hello.get("device_token") or "")
        if not self.security.authenticate_device(sid, public_key, token):
            await send_json(writer, {"ok": False, "error": "credencial inválida"})
            return
        event = str(hello.get("event") or "")
        if event not in {
            "consent_allowed", "consent_denied", "file_sent", "file_received",
            "lan_session_started", "lan_session_ended",
        }:
            await send_json(writer, {"ok": False, "error": "evento inválido"})
            return
        detail = hello.get("detail") if isinstance(hello.get("detail"), dict) else {}
        safe_detail = {
            "direction": str(detail.get("direction") or "")[:40],
            "size": max(0, min(int(detail.get("size") or 0), 10 * 1024 * 1024 * 1024)),
        }
        session_hash = "session:" + hashlib.sha256(
            str(hello.get("session") or "").encode("utf-8")
        ).hexdigest()[:16]
        self.security.audit(
            event, actor=sid, target=session_hash,
            source=source, detail=safe_detail,
        )
        await send_json(writer, {"ok": True})

    async def relay_bidirectional(self, a_reader, a_writer, b_reader, b_writer):
        async def pipe(reader, writer):
            try:
                while True:
                    data = await reader.read(BUFFER_SIZE)
                    if not data:
                        break
                    writer.write(data)
                    await writer.drain()
            except Exception:
                pass
            finally:
                try:
                    writer.close()
                except Exception:
                    pass

        t1 = asyncio.create_task(pipe(a_reader, b_writer))
        t2 = asyncio.create_task(pipe(b_reader, a_writer))

        done, pending = await asyncio.wait(
            {t1, t2},
            return_when=asyncio.FIRST_COMPLETED,
        )

        for task in pending:
            task.cancel()

        await asyncio.gather(t1, t2, return_exceptions=True)


async def amain(args):
    relay = RelayServer(args.db, args.audit_retention_days)

    ssl_ctx = None
    if args.cert and args.key:
        ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ssl_ctx.load_cert_chain(args.cert, args.key)
        print("[TLS] habilitado")
    else:
        if not args.allow_plain:
            raise SystemExit(
                "TLS é obrigatório por padrão. Informe --cert e --key. "
                "Use --allow-plain apenas em laboratório privado."
            )
        print("[ATENÇÃO] servidor SEM TLS - somente laboratório privado")

    server = await asyncio.start_server(
        relay.handle,
        args.host,
        args.port,
        ssl=ssl_ctx,
        limit=256 * 1024,
    )

    sockets = ", ".join(str(s.getsockname()) for s in server.sockets or [])
    print(f"ConectaPC Relay escutando em {sockets}")

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass

    async with server:
        try:
            await stop.wait()
        finally:
            relay.security.close()


def main():
    parser = argparse.ArgumentParser(description="ConectaPC rendezvous/relay server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=443)
    parser.add_argument("--cert", default="")
    parser.add_argument("--key", default="")
    parser.add_argument("--allow-plain", action="store_true")
    parser.add_argument("--db", default="/var/lib/conectapc/relay.db")
    parser.add_argument("--audit-retention-days", type=int, default=90)
    args = parser.parse_args()

    try:
        asyncio.run(amain(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
