#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import signal
import ssl
import time
from dataclasses import dataclass, field


MAX_LINE = 64 * 1024
TUNNEL_TIMEOUT = 20
BUFFER_SIZE = 128 * 1024


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


@dataclass
class Peer:
    sid: str
    name: str
    writer: asyncio.StreamWriter
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    connected_at: float = field(default_factory=time.time)


@dataclass
class RelaySession:
    token: str
    target_id: str
    controller_name: str
    controller_reader: asyncio.StreamReader
    controller_writer: asyncio.StreamWriter
    target_name: str
    host_reader: asyncio.StreamReader | None = None
    host_writer: asyncio.StreamWriter | None = None
    host_ready: asyncio.Event = field(default_factory=asyncio.Event)
    done: asyncio.Event = field(default_factory=asyncio.Event)


class RelayServer:
    def __init__(self):
        self.peers: dict[str, Peer] = {}
        self.sessions: dict[str, RelaySession] = {}
        self.lock = asyncio.Lock()

    async def handle(self, reader, writer):
        addr = writer.get_extra_info("peername")
        try:
            hello = await asyncio.wait_for(read_json_line(reader), timeout=10)
            mode = hello.get("mode")

            if mode == "control":
                await self.handle_control(reader, writer, hello)
            elif mode == "request":
                await self.handle_request(reader, writer, hello)
            elif mode == "host_tunnel":
                await self.handle_host_tunnel(reader, writer, hello)
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

    async def handle_control(self, reader, writer, hello):
        sid = str(hello.get("id") or "")
        name = str(hello.get("name") or "Computador")[:120]

        if not valid_id(sid):
            await send_json(writer, {"ok": False, "error": "ID inválido"})
            return

        peer = Peer(sid=sid, name=name, writer=writer)

        async with self.lock:
            existing = self.peers.get(sid)
            if existing and not existing.writer.is_closing():
                await send_json(writer, {"ok": False, "error": "ID já está online"})
                return
            self.peers[sid] = peer

        print(f"[ONLINE] {sid} {name} | total={len(self.peers)}")
        await send_json(writer, {"ok": True, "type": "registered"})

        try:
            while True:
                msg = await read_json_line(reader)
                if msg.get("type") == "ping":
                    await send_json(writer, {"type": "pong"}, peer.lock)
        finally:
            async with self.lock:
                if self.peers.get(sid) is peer:
                    self.peers.pop(sid, None)
            print(f"[OFFLINE] {sid} {name} | total={len(self.peers)}")

    async def handle_request(self, reader, writer, hello):
        target_id = str(hello.get("target") or "")
        controller = str(hello.get("controller") or "Técnico")[:120]

        if not valid_id(target_id):
            await send_json(writer, {"ok": False, "error": "ID de destino inválido"})
            return

        async with self.lock:
            target = self.peers.get(target_id)

        if not target or target.writer.is_closing():
            await send_json(writer, {"ok": False, "error": "ID offline ou inexistente"})
            return

        token = secrets.token_urlsafe(32)
        session = RelaySession(
            token=token,
            target_id=target_id,
            controller_name=controller,
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
                },
            )

            print(f"[SESSION] {controller} -> {target_id} ({session.target_name})")

            await self.relay_bidirectional(
                reader,
                writer,
                session.host_reader,
                session.host_writer,
            )

        finally:
            session.done.set()
            async with self.lock:
                self.sessions.pop(token, None)
            if session.host_writer and not session.host_writer.is_closing():
                session.host_writer.close()
                try:
                    await session.host_writer.wait_closed()
                except Exception:
                    pass

    async def handle_host_tunnel(self, reader, writer, hello):
        token = str(hello.get("session") or "")
        sid = str(hello.get("id") or "")

        async with self.lock:
            session = self.sessions.get(token)

        if not session:
            await send_json(writer, {"ok": False, "error": "sessão expirada"})
            return

        if sid != session.target_id:
            await send_json(writer, {"ok": False, "error": "ID não corresponde à sessão"})
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
    relay = RelayServer()

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
        await stop.wait()


def main():
    parser = argparse.ArgumentParser(description="ConectaPC rendezvous/relay server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=443)
    parser.add_argument("--cert", default="")
    parser.add_argument("--key", default="")
    parser.add_argument("--allow-plain", action="store_true")
    args = parser.parse_args()

    try:
        asyncio.run(amain(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
