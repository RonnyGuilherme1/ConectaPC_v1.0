from __future__ import annotations

import json
import os
import socket
import ssl
import threading
import time
from pathlib import Path


MAX_CONTROL_LINE = 64 * 1024


class RelayError(RuntimeError):
    pass


def _json_line(obj):
    return (json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def send_control(sock, obj, lock=None):
    data = _json_line(obj)
    if lock:
        with lock:
            sock.sendall(data)
    else:
        sock.sendall(data)


def recv_control(sock):
    data = bytearray()
    while len(data) < MAX_CONTROL_LINE:
        ch = sock.recv(1)
        if not ch:
            raise ConnectionError("Conexão com o servidor encerrada.")
        if ch == b"\n":
            try:
                msg = json.loads(data.decode("utf-8"))
            except Exception as exc:
                raise RelayError("Resposta inválida do servidor.") from exc
            if not isinstance(msg, dict):
                raise RelayError("Resposta inválida do servidor.")
            return msg
        data.extend(ch)
    raise RelayError("Mensagem de controle muito grande.")


def load_relay_config(default_path):
    default_path = Path(default_path)
    local_root = os.environ.get("LOCALAPPDATA")
    override = Path(local_root) / "ConectaPC" / "relay_config.json" if local_root else None

    chosen = override if override and override.exists() else default_path
    try:
        cfg = json.loads(chosen.read_text(encoding="utf-8"))
    except Exception:
        cfg = {}

    cfg.setdefault("enabled", False)
    cfg.setdefault("host", "")
    cfg.setdefault("port", 443)
    cfg.setdefault("tls", True)
    cfg.setdefault("server_name", "")
    cfg.setdefault("ca_file", "")
    cfg.setdefault("allow_insecure_dev", False)
    cfg["_config_dir"] = str(chosen.parent)
    return cfg


class RelayClient:
    """Mantém o ID deste ConectaPC registrado no servidor e abre túneis sob demanda.

    O servidor não conhece PIN nem precisa de banco de dados. O PIN continua sendo
    validado pelo computador remoto dentro do túnel.
    """

    def __init__(self, session_id, host_service, bridge, config_path, app_version):
        self.session_id = session_id
        self.host_service = host_service
        self.bridge = bridge
        self.config_path = config_path
        self.app_version = app_version

        self.config = load_relay_config(config_path)
        self.stop_event = threading.Event()
        self.ready_event = threading.Event()
        self.control_sock = None
        self.control_lock = threading.Lock()
        self.last_error = ""

    @property
    def enabled(self):
        return bool(self.config.get("enabled"))

    def start(self):
        if not self.enabled:
            self.bridge.internet_status.emit("Internet não configurada", False)
            return
        threading.Thread(target=self._control_loop, daemon=True).start()

    def stop(self):
        self.stop_event.set()
        self.ready_event.clear()
        sock = self.control_sock
        self.control_sock = None
        if sock:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                sock.close()
            except Exception:
                pass

    def is_ready(self):
        return self.enabled and self.ready_event.is_set()

    def status_detail(self):
        if not self.enabled:
            return "Servidor relay não configurado."
        if self.ready_event.is_set():
            return "Servidor relay conectado."
        return self.last_error or "Servidor relay indisponível."

    def _resolve_ca_file(self):
        value = str(self.config.get("ca_file") or "").strip()
        if not value:
            return None
        p = Path(value)
        if not p.is_absolute():
            p = Path(self.config.get("_config_dir", ".")) / p
        return str(p)

    def _open_server_socket(self, timeout=12):
        host = str(self.config.get("host") or "").strip()
        port = int(self.config.get("port") or 443)
        use_tls = bool(self.config.get("tls", True))

        if not host or host.upper().startswith("SEU_"):
            raise RelayError("Configure host/porta em relay_config.json.")

        raw = socket.create_connection((host, port), timeout=timeout)
        raw.settimeout(timeout)

        try:
            raw.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass

        if not use_tls:
            if not bool(self.config.get("allow_insecure_dev", False)):
                raw.close()
                raise RelayError(
                    "Conexão relay sem TLS bloqueada. Use TLS ou habilite "
                    "allow_insecure_dev somente para laboratório."
                )
            return raw

        ca_file = self._resolve_ca_file()
        if ca_file:
            ctx = ssl.create_default_context(cafile=ca_file)
        else:
            ctx = ssl.create_default_context()

        server_name = str(self.config.get("server_name") or "").strip() or host
        try:
            wrapped = ctx.wrap_socket(raw, server_hostname=server_name)
        except Exception:
            raw.close()
            raise
        wrapped.settimeout(timeout)
        return wrapped

    def _control_loop(self):
        delay = 1.0

        while not self.stop_event.is_set():
            sock = None
            try:
                self.bridge.internet_status.emit("Conectando ao servidor…", False)
                sock = self._open_server_socket(timeout=12)
                self.control_sock = sock

                send_control(sock, {
                    "mode": "control",
                    "id": self.session_id,
                    "name": socket.gethostname(),
                    "version": self.app_version,
                }, self.control_lock)

                reply = recv_control(sock)
                if not reply.get("ok"):
                    raise RelayError(reply.get("error") or "Registro recusado pelo servidor.")

                sock.settimeout(15)
                self.ready_event.set()
                self.last_error = ""
                self.bridge.internet_status.emit("Internet pronta", True)
                delay = 1.0

                while not self.stop_event.is_set():
                    try:
                        msg = recv_control(sock)
                    except socket.timeout:
                        send_control(sock, {"type": "ping"}, self.control_lock)
                        continue

                    msg_type = msg.get("type")

                    if msg_type == "incoming":
                        token = str(msg.get("session") or "")
                        controller = str(msg.get("controller") or "Técnico")
                        if token:
                            threading.Thread(
                                target=self._accept_internet_session,
                                args=(token, controller),
                                daemon=True,
                            ).start()

                    elif msg_type == "pong":
                        pass

            except Exception as exc:
                self.last_error = str(exc)
                self.bridge.internet_status.emit("Internet offline", False)
            finally:
                self.ready_event.clear()
                if sock:
                    try:
                        sock.close()
                    except Exception:
                        pass
                if self.control_sock is sock:
                    self.control_sock = None

            if not self.stop_event.is_set():
                time.sleep(delay)
                delay = min(15.0, delay * 1.7)

    def _accept_internet_session(self, token, controller):
        sock = None
        try:
            sock = self._open_server_socket(timeout=15)
            send_control(sock, {
                "mode": "host_tunnel",
                "session": token,
                "id": self.session_id,
            })
            reply = recv_control(sock)
            if not reply.get("ok"):
                raise RelayError(reply.get("error") or "Túnel recusado.")

            # A partir deste ponto a conexão deixa de ser JSON-line e passa a ser
            # um fluxo binário transparente do protocolo normal do ConectaPC.
            sock.settimeout(None)
            self.host_service.handle_tunneled_client(
                sock,
                f"Internet • {controller}",
            )
            sock = None

        except Exception as exc:
            self.bridge.notify.emit(
                "Conexão pela internet",
                f"Não foi possível preparar a sessão de {controller}:\n{exc}",
            )
        finally:
            if sock:
                try:
                    sock.close()
                except Exception:
                    pass

    def open_controller_tunnel(self, target_id, timeout=22):
        if not self.enabled:
            raise RelayError("Servidor de internet não configurado.")

        sock = self._open_server_socket(timeout=timeout)
        try:
            send_control(sock, {
                "mode": "request",
                "target": target_id,
                "controller": socket.gethostname(),
                "version": self.app_version,
            })
            reply = recv_control(sock)
            if not reply.get("ok"):
                raise RelayError(reply.get("error") or "Não foi possível abrir a sessão.")

            sock.settimeout(None)
            return sock, {
                "name": reply.get("target_name") or f"PC {target_id}",
                "transport": "relay",
            }
        except Exception:
            try:
                sock.close()
            except Exception:
                pass
            raise
