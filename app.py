from __future__ import annotations

import io
import hashlib
import json
import os
import secrets
import shutil
import socket
import struct
import sys
import threading
import time
from pathlib import Path

import mss
import pyautogui
from PIL import Image
from PySide6.QtCore import QObject, Qt, Signal, QEvent
from PySide6.QtGui import QIcon, QImage, QKeyEvent, QKeySequence, QMouseEvent, QPixmap, QShortcut, QWheelEvent
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QGraphicsDropShadowEffect, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QProgressBar, QPushButton, QInputDialog,
    QScrollArea, QSizePolicy, QSpacerItem, QStackedWidget, QTabBar, QTabWidget, QVBoxLayout, QWidget
)

from protocol import recv_frame, recv_json_payload, send_frame, send_json
from internet import RelayClient, RelayError
from security import (
    fingerprint, load_known_peers, load_or_create_identity,
    open_secure_controller, open_secure_host,
)
from theme import APP_QSS
from updates import (
    apply_rollback, apply_update, check_and_download, rollback_available,
)

APP_NAME = "ConectaPC"
APP_VERSION = "2.1.0"
TCP_PORT = 45888
DISCOVERY_PORT = 45889
SERVICE = "CONECTAPC_LAN_V1"
FPS = 14
JPEG_QUALITY = 48
MAX_WIDTH = 1280
MAX_FILE_SIZE = 10 * 1024 * 1024 * 1024
VIDEO_SEND_TIMEOUT = 1.5
MOUSE_MOVE_INTERVAL = 0.018


pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0


def resource_path(relative):
    base = getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)
    return str(Path(base) / relative)


def random_id():
    return f"{secrets.randbelow(900_000_000) + 100_000_000:09d}"


def random_pin():
    return f"{secrets.randbelow(1_000_000):06d}"


def local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"


def unique_path(path: Path):
    if not path.exists():
        return path
    i = 1
    while True:
        p = path.with_name(f"{path.stem} ({i}){path.suffix}")
        if not p.exists():
            return p
        i += 1


def file_sha256(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def prepare_incoming_file(name, declared_size):
    name = os.path.basename(str(name or "arquivo.bin")) or "arquivo.bin"
    size = int(declared_size)
    if size < 0 or size > MAX_FILE_SIZE:
        raise ValueError("Tamanho de arquivo não permitido")
    folder = Path.home() / "Downloads" / "ConectaPC Recebidos"
    folder.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(folder).free < size + 32 * 1024 * 1024:
        raise OSError("Espaço em disco insuficiente para receber o arquivo")
    final_path = unique_path(folder / name)
    temp_path = final_path.with_name(final_path.name + f".{secrets.token_hex(6)}.part")
    return name, size, final_path, temp_path


def pretty_id(value):
    digits = "".join(c for c in str(value) if c.isdigit())
    if len(digits) == 9:
        return f"{digits[:3]} {digits[3:6]} {digits[6:]}"
    return digits


def app_data_dir():
    root = os.environ.get("LOCALAPPDATA")
    if root:
        folder = Path(root) / APP_NAME
    else:
        folder = Path.home() / f".{APP_NAME.lower()}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


RECENTS_FILE = app_data_dir() / "recent.json"


def load_recents():
    try:
        if not RECENTS_FILE.exists():
            return []
        data = json.loads(RECENTS_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return []
        valid = []
        for item in data:
            if not isinstance(item, dict):
                continue
            sid = "".join(c for c in str(item.get("id", "")) if c.isdigit())
            if len(sid) != 9:
                continue
            valid.append({
                "id": sid,
                "name": str(item.get("name") or "Computador"),
                "last_access": str(item.get("last_access") or ""),
            })
        return valid[:8]
    except Exception:
        return []


def save_recents(items):
    try:
        RECENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        RECENTS_FILE.write_text(
            json.dumps(items[:8], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


def map_key_name(key):
    key = (key or "").lower()
    mapping = {
        "return": "enter", "escape": "esc",
        "control": "ctrl", "ctrl": "ctrl",
        "shift": "shift", "alt": "alt",
        "meta": "win", "backspace": "backspace",
        "tab": "tab", "delete": "delete",
        "insert": "insert", "home": "home", "end": "end",
        "pageup": "pageup", "pagedown": "pagedown",
        "left": "left", "right": "right", "up": "up", "down": "down",
        "space": "space",
    }
    if key in mapping:
        return mapping[key]
    if len(key) == 1:
        return key
    if key.startswith("f") and key[1:].isdigit():
        return key
    return None


def add_shadow(widget, blur=22, y=4):
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, y)
    effect.setColor(Qt.GlobalColor.lightGray)
    widget.setGraphicsEffect(effect)


class UiBridge(QObject):
    host_status = Signal(str, bool)
    internet_status = Signal(str, bool)
    host_connections = Signal(int)
    ask_accept = Signal(str, str, object)
    ask_file = Signal(object)
    notify = Signal(str, str)
    pin_changed = Signal(str)
    update_ready = Signal(str, str)
    update_status = Signal(str)


class DiscoveryService:
    def __init__(self, own_id):
        self.own_id = own_id
        self.ip = local_ip()
        self.stop_event = threading.Event()
        self.peers = {}
        self.lock = threading.Lock()

    def start(self):
        threading.Thread(target=self._broadcast_loop, daemon=True).start()
        threading.Thread(target=self._listen_loop, daemon=True).start()

    def stop(self):
        self.stop_event.set()

    def find_peer(self, sid):
        with self.lock:
            peer = self.peers.get(sid)
            if not peer:
                return None
            if time.time() - peer["seen"] > 7:
                return None
            return dict(peer)

    def _broadcast_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        while not self.stop_event.is_set():
            payload = {
                "service": SERVICE,
                "id": self.own_id,
                "ip": self.ip,
                "port": TCP_PORT,
                "name": socket.gethostname(),
            }
            try:
                sock.sendto(json.dumps(payload).encode("utf-8"), ("255.255.255.255", DISCOVERY_PORT))
            except OSError:
                pass
            time.sleep(1.2)
        try:
            sock.close()
        except Exception:
            pass

    def _listen_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("", DISCOVERY_PORT))
            sock.settimeout(1)
        except OSError:
            return

        while not self.stop_event.is_set():
            try:
                data, addr = sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                msg = json.loads(data.decode("utf-8"))
            except Exception:
                continue
            if msg.get("service") != SERVICE:
                continue
            sid = str(msg.get("id", ""))
            if not sid or sid == self.own_id:
                continue
            with self.lock:
                self.peers[sid] = {
                    "ip": msg.get("ip") or addr[0],
                    "port": int(msg.get("port", TCP_PORT)),
                    "name": msg.get("name") or addr[0],
                    "seen": time.time(),
                }


class HostService:
    def __init__(self, session_id, pin, identity, known_peers, bridge):
        self.session_id = session_id
        self.pin = pin
        self.identity = identity
        self.known_peers = known_peers
        self.bridge = bridge
        self.stop_event = threading.Event()
        self.connections = set()
        self.lock = threading.Lock()
        self.pin_lock = threading.Lock()
        self.attempts = {}
        self.connection_slots = threading.BoundedSemaphore(32)
        self.file_send_lock = threading.Lock()
        self.audit_callback = None
        self.event_callback = None

    def start(self):
        threading.Thread(target=self._server_loop, daemon=True).start()

    def stop(self):
        self.stop_event.set()
        self.disconnect_all()

    def disconnect_all(self):
        with self.lock:
            conns = list(self.connections)
        for conn in conns:
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass

    def _server_loop(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            server.bind(("0.0.0.0", TCP_PORT))
            server.listen(16)
            server.settimeout(1)
            self.bridge.host_status.emit("Pronto na rede local", True)
        except OSError as e:
            self.bridge.host_status.emit(f"Porta {TCP_PORT} indisponível", False)
            return

        while not self.stop_event.is_set():
            try:
                conn, addr = server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._handle_client, args=(conn, addr), daemon=True).start()

        try:
            server.close()
        except Exception:
            pass

    def handle_tunneled_client(
        self, conn, origin_label="Internet", expected_peer_key=None,
        verified_controller=None, verified_controller_id="", session_token="",
    ):
        """Recebe uma conexão já transportada pelo relay.

        A autenticação E2E/código temporário e o consentimento ocorrem dentro do
        protocolo normal; o relay apenas transporta os bytes.
        """
        self._handle_client(
            conn, (origin_label, 0), expected_peer_key=expected_peer_key,
            verified_controller=verified_controller,
            verified_controller_id=verified_controller_id,
            session_token=session_token,
        )

    def _consume_pin(self, candidate, peer_key, source):
        now = time.monotonic()
        with self.pin_lock:
            keys = [("peer", peer_key), ("source", str(source))]
            histories = {}
            for key in keys:
                history = [stamp for stamp in self.attempts.get(key, []) if stamp > now - 300]
                histories[key] = history
                self.attempts[key] = history
                if len(history) >= 5:
                    return False, "Muitas tentativas. Aguarde cinco minutos."
            if not secrets.compare_digest(str(candidate or ""), self.pin):
                for key in keys:
                    histories[key].append(now)
                    self.attempts[key] = histories[key]
                return False, "ID ou código temporário incorreto."
            self.attempts.pop(("peer", peer_key), None)
            self.pin = random_pin()
            self.bridge.pin_changed.emit(self.pin)
            return True, ""

    def _ask_accept(self, controller, ip):
        response = {"event": threading.Event(), "ok": False}
        self.bridge.ask_accept.emit(controller, ip, response)
        response["event"].wait(60)
        return bool(response["ok"])

    def _ask_file(self):
        response = {"event": threading.Event(), "path": None}
        self.bridge.ask_file.emit(response)
        response["event"].wait(120)
        return response["path"]

    def _handle_client(
        self, conn, addr, expected_peer_key=None,
        verified_controller=None, verified_controller_id="", session_token="",
    ):
        is_relay_session = bool(session_token)
        session_token = session_token or ("lan-" + secrets.token_urlsafe(24))
        accepted = False
        if not self.connection_slots.acquire(blocking=False):
            conn.close()
            return
        send_lock = threading.Lock()
        stop_conn = threading.Event()
        try:
            conn.settimeout(15)
            conn = open_secure_host(conn, self.identity, expected_peer_key)
            conn.settimeout(None)
            kind, payload = recv_frame(conn)
            if kind != b"J":
                return
            hello = recv_json_payload(payload)
            if hello.get("type") != "hello":
                return

            controller_id = str(verified_controller_id or hello.get("controller_id") or "")
            known_id = "controller:" + controller_id if controller_id else "controller-key:" + conn.peer_fingerprint
            if not self.known_peers.matches(known_id, conn.peer_public_key):
                send_json(conn, {
                    "type": "hello_error",
                    "message": "A identidade conhecida deste técnico mudou. A conexão foi bloqueada.",
                }, send_lock)
                return

            pin_ok, pin_error = self._consume_pin(
                hello.get("pin"), conn.peer_public_key, addr[0]
            )
            if hello.get("id") != self.session_id or not pin_ok:
                send_json(conn, {"type": "hello_error", "message": pin_error or "ID incorreto."}, send_lock)
                return

            if verified_controller:
                controller_label = f"{verified_controller} (identidade verificada)\nDispositivo {conn.peer_fingerprint}"
            else:
                controller_label = (
                    f"{hello.get('controller') or 'Técnico'} (LAN, identidade não cadastrada)\n"
                    f"Dispositivo {conn.peer_fingerprint}"
                )
            accepted = self._ask_accept(controller_label, addr[0])
            if self.audit_callback:
                threading.Thread(
                    target=self.audit_callback, args=(session_token, accepted), daemon=True
                ).start()
            if not accepted:
                send_json(conn, {"type": "hello_error", "message": "Conexão recusada pelo usuário."}, send_lock)
                return
            self.known_peers.remember(
                known_id, conn.peer_public_key,
                verified_controller or hello.get("controller") or "Técnico",
            )
            if not is_relay_session and self.event_callback:
                threading.Thread(
                    target=self.event_callback,
                    args=("lan_session_started", session_token, {}), daemon=True,
                ).start()

            with self.lock:
                self.connections.add(conn)
                count = len(self.connections)
            self.bridge.host_connections.emit(count)

            sw, sh = pyautogui.size()
            send_json(conn, {
                "type": "hello_ok",
                "host": socket.gethostname(),
                "screen_width": sw,
                "screen_height": sh,
            }, send_lock)

            threading.Thread(
                target=self._screen_sender,
                args=(conn, send_lock, stop_conn),
                daemon=True,
            ).start()

            self._command_loop(conn, send_lock, stop_conn, session_token)

        except Exception:
            pass
        finally:
            stop_conn.set()
            try:
                conn.close()
            except Exception:
                pass
            with self.lock:
                self.connections.discard(conn)
                count = len(self.connections)
            self.bridge.host_connections.emit(count)
            if accepted and not is_relay_session and self.event_callback:
                threading.Thread(
                    target=self.event_callback,
                    args=("lan_session_ended", session_token, {}), daemon=True,
                ).start()
            self.connection_slots.release()

    def _screen_sender(self, conn, send_lock, stop_conn):
        """Streaming LAN adaptativo.

        O objetivo aqui não é guardar todos os frames; em suporte remoto,
        um frame novo é mais valioso do que um frame antigo. Por isso a rotina
        reduz resolução/qualidade quando o envio começa a atrasar e evita que
        a fila de TCP cresça indefinidamente.
        """
        try:
            try:
                conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except OSError:
                pass

            quality = JPEG_QUALITY
            max_width = MAX_WIDTH
            target_delay = 1 / FPS

            with mss.mss() as sct:
                monitor = sct.monitors[1]

                while not self.stop_event.is_set() and not stop_conn.is_set():
                    started = time.perf_counter()

                    shot = sct.grab(monitor)
                    img = Image.frombytes("RGB", shot.size, shot.rgb)
                    src_w, src_h = img.size

                    if src_w > max_width:
                        ratio = max_width / src_w
                        img = img.resize(
                            (max_width, max(1, int(src_h * ratio))),
                            Image.Resampling.BILINEAR,
                        )

                    buf = io.BytesIO()
                    img.save(
                        buf,
                        "JPEG",
                        quality=quality,
                        optimize=False,
                        subsampling=2,
                    )

                    packet = struct.pack("!II", src_w, src_h) + buf.getvalue()

                    before_send = time.perf_counter()
                    send_frame(conn, b"S", packet, send_lock)
                    send_time = time.perf_counter() - before_send

                    # Se a rede/computador estiver demorando para enviar um frame,
                    # reduzimos o peso dos próximos frames. Se estiver folgado,
                    # recuperamos gradualmente a qualidade.
                    if send_time > 0.09:
                        quality = max(34, quality - 3)
                        max_width = max(960, max_width - 80)
                    elif send_time < 0.025:
                        quality = min(JPEG_QUALITY, quality + 1)
                        max_width = min(MAX_WIDTH, max_width + 40)

                    elapsed = time.perf_counter() - started
                    sleep_for = target_delay - elapsed
                    if sleep_for > 0:
                        time.sleep(sleep_for)

        except Exception:
            stop_conn.set()

    def _command_loop(self, conn, send_lock, stop_conn, session_token=""):
        upload = None
        upload_fh = None
        try:
            while not self.stop_event.is_set() and not stop_conn.is_set():
                kind, payload = recv_frame(conn)

                if kind == b"J":
                    msg = recv_json_payload(payload)
                    t = msg.get("type")

                    if t == "mouse_move":
                        pyautogui.moveTo(int(msg["x"]), int(msg["y"]), duration=0)
                    elif t == "mouse_down":
                        pyautogui.mouseDown(int(msg["x"]), int(msg["y"]), button=msg.get("button", "left"))
                    elif t == "mouse_up":
                        pyautogui.mouseUp(int(msg["x"]), int(msg["y"]), button=msg.get("button", "left"))
                    elif t == "scroll":
                        pyautogui.scroll(int(msg.get("delta", 0)))
                    elif t == "key_down":
                        key = map_key_name(msg.get("key"))
                        if key:
                            pyautogui.keyDown(key)
                    elif t == "key_up":
                        key = map_key_name(msg.get("key"))
                        if key:
                            pyautogui.keyUp(key)

                    elif t == "file_start":
                        if upload_fh:
                            raise ValueError("Já existe uma transferência em andamento")
                        name, size, target, temp = prepare_incoming_file(msg.get("name"), msg.get("size", -1))
                        expected_hash = str(msg.get("sha256") or "").lower()
                        if len(expected_hash) != 64 or any(c not in "0123456789abcdef" for c in expected_hash):
                            raise ValueError("Hash do arquivo inválido")
                        upload = {
                            "path": target, "temp": temp, "name": name, "size": size,
                            "received": 0, "sha256": expected_hash, "hasher": hashlib.sha256(),
                        }
                        upload_fh = open(temp, "xb")

                    elif t == "file_end":
                        if upload_fh:
                            upload_fh.close()
                            upload_fh = None
                        if upload:
                            if upload["received"] != upload["size"] or upload["hasher"].hexdigest() != upload["sha256"]:
                                upload["temp"].unlink(missing_ok=True)
                                raise ValueError("Arquivo recebido incompleto ou com hash divergente")
                            os.replace(upload["temp"], upload["path"])
                            self.bridge.notify.emit(
                                "Arquivo recebido",
                                f"O arquivo foi salvo em:\n{upload['path']}",
                            )
                            send_json(conn, {
                                "type": "file_received", "name": upload["name"],
                                "size": upload["size"], "sha256": upload["sha256"],
                            }, send_lock)
                            if self.event_callback and session_token:
                                threading.Thread(
                                    target=self.event_callback,
                                    args=("file_received", session_token, {
                                        "direction": "controller_to_host", "size": upload["size"],
                                    }), daemon=True,
                                ).start()
                            upload = None

                    elif t == "request_file":
                        path = self._ask_file()
                        if path:
                            threading.Thread(
                                target=self._send_file,
                                args=(conn, send_lock, path, session_token),
                                daemon=True,
                            ).start()
                        else:
                            send_json(conn, {"type": "file_cancelled"}, send_lock)

                    elif t == "disconnect":
                        break

                elif kind == b"U" and upload_fh:
                    if upload["received"] + len(payload) > upload["size"]:
                        raise ValueError("Arquivo excedeu o tamanho declarado")
                    upload_fh.write(payload)
                    upload["received"] += len(payload)
                    upload["hasher"].update(payload)

        finally:
            if upload_fh:
                try:
                    upload_fh.close()
                except Exception:
                    pass
            if upload and upload.get("temp"):
                upload["temp"].unlink(missing_ok=True)
            stop_conn.set()

    def _send_file(self, conn, send_lock, path, session_token=""):
        try:
            with self.file_send_lock:
                p = Path(path)
                size = p.stat().st_size
                if size > MAX_FILE_SIZE:
                    raise ValueError("Arquivo excede o limite de 10 GB")
                digest = file_sha256(p)
                send_json(conn, {
                    "type": "download_start", "name": p.name, "size": size, "sha256": digest,
                }, send_lock)
                with p.open("rb") as fh:
                    while True:
                        chunk = fh.read(256 * 1024)
                        if not chunk:
                            break
                        send_frame(conn, b"D", chunk, send_lock)
                send_json(conn, {"type": "download_end", "name": p.name, "sha256": digest}, send_lock)
                if self.event_callback and session_token:
                    self.event_callback(
                        "file_sent", session_token,
                        {"direction": "host_to_controller", "size": size},
                    )
        except Exception as e:
            self.bridge.notify.emit("Falha no envio", str(e))


class SessionBridge(QObject):
    connected = Signal(str, str)
    failed = Signal(str)
    frame = Signal(object)
    status = Signal(str)
    notify = Signal(str, str)
    disconnected = Signal()
    progress = Signal(int)


class RemoteScreen(QLabel):
    mouseMoveRemote = Signal(int, int)
    mouseButtonRemote = Signal(int, int, str, bool)
    wheelRemote = Signal(int)
    keyDownRemote = Signal(str)
    keyUpRemote = Signal(str)
    filesDropped = Signal(object)

    def __init__(self):
        super().__init__()
        self.setAlignment(Qt.AlignCenter)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.remote_w = 1
        self.remote_h = 1
        self.draw_rect = None
        self.setText("Conectando ao computador remoto…")
        self.setStyleSheet(
            "QLabel { background:#0C1522; color:#B8C4D2; border-radius:12px; "
            "border:1px solid #1E3147; font-size:11pt; }"
        )

    def set_remote_size(self, w, h):
        self.remote_w = max(1, w)
        self.remote_h = max(1, h)

    def set_draw_rect(self, rect):
        self.draw_rect = rect

    def _translate(self, pos):
        if not self.draw_rect:
            return None
        x, y, w, h = self.draw_rect
        px, py = pos.x(), pos.y()
        if not (x <= px < x+w and y <= py < y+h):
            return None
        return (
            int((px-x)/w*self.remote_w),
            int((py-y)/h*self.remote_h),
        )

    def mouseMoveEvent(self, event: QMouseEvent):
        p = self._translate(event.position())
        if p:
            self.mouseMoveRemote.emit(*p)

    def mousePressEvent(self, event: QMouseEvent):
        p = self._translate(event.position())
        if not p:
            return
        self.setFocus()
        if event.button() == Qt.LeftButton:
            self.mouseButtonRemote.emit(p[0], p[1], "left", True)
        elif event.button() == Qt.RightButton:
            self.mouseButtonRemote.emit(p[0], p[1], "right", True)

    def mouseReleaseEvent(self, event: QMouseEvent):
        p = self._translate(event.position())
        if not p:
            return
        if event.button() == Qt.LeftButton:
            self.mouseButtonRemote.emit(p[0], p[1], "left", False)
        elif event.button() == Qt.RightButton:
            self.mouseButtonRemote.emit(p[0], p[1], "right", False)

    def wheelEvent(self, event: QWheelEvent):
        self.wheelRemote.emit(1 if event.angleDelta().y() > 0 else -1)

    def keyPressEvent(self, event: QKeyEvent):
        key = self._key_name(event)
        if key:
            self.keyDownRemote.emit(key)
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent):
        key = self._key_name(event)
        if key:
            self.keyUpRemote.emit(key)
            event.accept()
            return
        super().keyReleaseEvent(event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            files = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
            if any(Path(p).is_file() for p in files):
                event.acceptProposedAction()
                return
        event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        files = []
        for url in event.mimeData().urls():
            if url.isLocalFile():
                path = url.toLocalFile()
                if Path(path).is_file():
                    files.append(path)
        if files:
            self.filesDropped.emit(files)
            event.acceptProposedAction()
        else:
            event.ignore()

    @staticmethod
    def _key_name(event):
        special = {
            Qt.Key_Return: "return", Qt.Key_Enter: "return",
            Qt.Key_Escape: "escape", Qt.Key_Backspace: "backspace",
            Qt.Key_Tab: "tab", Qt.Key_Delete: "delete",
            Qt.Key_Insert: "insert", Qt.Key_Home: "home",
            Qt.Key_End: "end", Qt.Key_PageUp: "pageup",
            Qt.Key_PageDown: "pagedown", Qt.Key_Left: "left",
            Qt.Key_Right: "right", Qt.Key_Up: "up",
            Qt.Key_Down: "down", Qt.Key_Space: "space",
            Qt.Key_Control: "ctrl", Qt.Key_Shift: "shift",
            Qt.Key_Alt: "alt", Qt.Key_Meta: "meta",
        }
        if event.key() in special:
            return special[event.key()]
        if Qt.Key_F1 <= event.key() <= Qt.Key_F12:
            return f"f{event.key() - Qt.Key_F1 + 1}"
        txt = event.text()
        if len(txt) == 1:
            return txt.lower()
        return None


class RemoteSession(QWidget):
    titleChanged = Signal(str)
    stateChanged = Signal(str)
    closed = Signal(object)

    def __init__(
        self, peer, sid, pin, identity, controller_name="", event_callback=None,
        peer_key_callback=None, parent=None
    ):
        super().__init__(parent)
        self.peer = peer
        self.sid = sid
        self.pin = pin
        self.identity = identity
        self.controller_name = controller_name or socket.gethostname()
        self.event_callback = event_callback
        self.relay_session = str(peer.get("relay_session") or "")
        self.peer_key_callback = peer_key_callback

        self.sock = None
        self.connected_flag = False
        self.send_lock = threading.Lock()
        self.remote_w = 1
        self.remote_h = 1
        self.last_pil = None
        self.last_mouse_send = 0
        self.download_fh = None
        self.download_path = None
        self.download = None
        self.transfer_lock = threading.Lock()
        self.compact_mode = False

        self.bridge = SessionBridge()
        self.bridge.connected.connect(self._on_connected)
        self.bridge.failed.connect(self._on_failed)
        self.bridge.frame.connect(self._on_frame)
        self.bridge.status.connect(self._on_status)
        self.bridge.notify.connect(lambda t,m: QMessageBox.information(self,t,m))
        self.bridge.disconnected.connect(self._on_disconnected)
        self.bridge.progress.connect(self._set_progress)

        self._build_ui()
        threading.Thread(target=self._connect_thread, daemon=True).start()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14,14,14,14)
        layout.setSpacing(10)

        self.toolbar_widget = QWidget()
        toolbar = QHBoxLayout(self.toolbar_widget)
        toolbar.setContentsMargins(0,0,0,0)

        self.title_label = QLabel(f"Conectando a {self.peer['name']}…")
        self.title_label.setObjectName("SectionTitle")
        toolbar.addWidget(self.title_label)
        toolbar.addStretch(1)

        self.send_btn = QPushButton("Enviar arquivo")
        self.send_btn.setEnabled(False)
        self.send_btn.clicked.connect(self.choose_files)
        toolbar.addWidget(self.send_btn)

        self.receive_btn = QPushButton("Receber arquivo")
        self.receive_btn.setEnabled(False)
        self.receive_btn.clicked.connect(self.request_file)
        toolbar.addWidget(self.receive_btn)

        self.disconnect_btn = QPushButton("Desconectar")
        self.disconnect_btn.setObjectName("Danger")
        self.disconnect_btn.clicked.connect(self.disconnect)
        toolbar.addWidget(self.disconnect_btn)

        layout.addWidget(self.toolbar_widget)

        self.screen = RemoteScreen()
        self.screen.setMinimumHeight(420)
        self.screen.mouseMoveRemote.connect(self._mouse_move)
        self.screen.mouseButtonRemote.connect(self._mouse_button)
        self.screen.wheelRemote.connect(lambda d: self._safe_send({"type":"scroll","delta":d}))
        self.screen.keyDownRemote.connect(lambda k: self._safe_send({"type":"key_down","key":k}))
        self.screen.keyUpRemote.connect(lambda k: self._safe_send({"type":"key_up","key":k}))
        self.screen.filesDropped.connect(self.send_files)
        layout.addWidget(self.screen, 1)

        self.bottom_widget = QWidget()
        bottom = QHBoxLayout(self.bottom_widget)
        bottom.setContentsMargins(0,0,0,0)

        self.status_label = QLabel("Inicializando conexão…")
        self.status_label.setObjectName("Muted")
        bottom.addWidget(self.status_label, 1)

        self.progress = QProgressBar()
        self.progress.setRange(0,100)
        self.progress.setValue(0)
        self.progress.setMaximumWidth(260)
        self.progress.hide()
        bottom.addWidget(self.progress)
        layout.addWidget(self.bottom_widget)

    def set_immersive(self, enabled):
        """Esconde a interface da sessão para deixar apenas a tela remota."""
        self.toolbar_widget.setVisible(not enabled)
        self.bottom_widget.setVisible(not enabled and not self.compact_mode)
        layout = self.layout()
        if layout:
            margin = 0 if enabled else (8 if self.compact_mode else 14)
            layout.setContentsMargins(margin, margin, margin, margin)
            layout.setSpacing(0 if enabled else (6 if self.compact_mode else 10))
        if enabled:
            self.screen.setStyleSheet(
                "QLabel { background:#050A11; color:#B8C4D2; border:0px; border-radius:0px; }"
            )
        else:
            self.screen.setStyleSheet(
                "QLabel { background:#0C1522; color:#B8C4D2; border-radius:12px; "
                "border:1px solid #1E3147; font-size:11pt; }"
            )

    def set_compact_mode(self, enabled):
        """Ajusta uma sessão para compartilhar a área com outras telas."""
        self.compact_mode = bool(enabled)
        self.send_btn.setVisible(not enabled)
        self.receive_btn.setVisible(not enabled)
        self.bottom_widget.setVisible(not enabled)
        self.screen.setMinimumHeight(180 if enabled else 420)
        layout = self.layout()
        if layout:
            margin = 8 if enabled else 14
            layout.setContentsMargins(margin, margin, margin, margin)
            layout.setSpacing(6 if enabled else 10)
        if enabled:
            self.disconnect_btn.setText("Fechar")
        else:
            self.disconnect_btn.setText("Desconectar" if self.connected_flag else "Fechar aba")

    def _connect_thread(self):
        try:
            sock = self.peer.pop("_preconnected_socket", None)
            if sock is None:
                sock = socket.create_connection(
                    (self.peer["ip"], int(self.peer["port"])),
                    timeout=8,
                )
            try:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except OSError:
                pass
            sock.settimeout(None)
            sock = open_secure_controller(sock, self.identity, self.peer.get("expected_peer_key"))
            self.sock = sock
            send_json(sock, {
                "type":"hello",
                "id":self.sid,
                "pin":self.pin,
                "controller":self.controller_name,
                "controller_id":self.identity.device_id,
            }, self.send_lock)

            kind, payload = recv_frame(sock)
            if kind != b"J":
                raise ConnectionError("Resposta inválida.")
            msg = recv_json_payload(payload)
            if msg.get("type") != "hello_ok":
                raise ConnectionError(msg.get("message","Conexão recusada."))

            self.remote_w = int(msg.get("screen_width",1))
            self.remote_h = int(msg.get("screen_height",1))
            self.connected_flag = True
            if self.peer_key_callback:
                self.peer_key_callback(self.sid, sock.peer_public_key, msg.get("host") or self.peer["name"])
            self.bridge.connected.emit(msg.get("host") or self.peer["name"], self.peer["ip"])
            self._reader_loop(sock)

        except Exception as e:
            self.connected_flag = False
            self.bridge.failed.emit(str(e))

    def _reader_loop(self, sock):
        try:
            while self.connected_flag:
                kind, payload = recv_frame(sock)
                if kind == b"S":
                    if len(payload) < 8:
                        continue
                    self.remote_w, self.remote_h = struct.unpack("!II", payload[:8])
                    img = Image.open(io.BytesIO(payload[8:])).convert("RGB")
                    self.bridge.frame.emit(img)

                elif kind == b"J":
                    msg = recv_json_payload(payload)
                    t = msg.get("type")

                    if t == "download_start":
                        if self.download_fh:
                            raise ValueError("Já existe um recebimento em andamento")
                        name, size, target, temp = prepare_incoming_file(msg.get("name"), msg.get("size", -1))
                        expected_hash = str(msg.get("sha256") or "").lower()
                        if len(expected_hash) != 64 or any(c not in "0123456789abcdef" for c in expected_hash):
                            raise ValueError("Hash do arquivo inválido")
                        self.download_path = target
                        self.download = {
                            "temp": temp, "size": size, "received": 0,
                            "sha256": expected_hash, "hasher": hashlib.sha256(),
                        }
                        self.download_fh = open(temp, "xb")
                        self.bridge.status.emit(f"Recebendo {target.name}…")

                    elif t == "download_end":
                        if self.download_fh:
                            self.download_fh.close()
                            self.download_fh = None
                        if self.download_path and self.download:
                            if (
                                self.download["received"] != self.download["size"]
                                or self.download["hasher"].hexdigest() != self.download["sha256"]
                            ):
                                self.download["temp"].unlink(missing_ok=True)
                                raise ValueError("Arquivo recebido incompleto ou com hash divergente")
                            os.replace(self.download["temp"], self.download_path)
                            self.bridge.notify.emit("Arquivo recebido", f"Salvo em:\n{self.download_path}")
                            if self.event_callback and self.relay_session:
                                threading.Thread(
                                    target=self.event_callback,
                                    args=("file_received", self.relay_session, {
                                        "direction": "host_to_controller", "size": self.download["size"],
                                    }), daemon=True,
                                ).start()
                            self.download_path = None
                            self.download = None

                    elif t == "file_received":
                        self.bridge.status.emit(f"Arquivo enviado: {msg.get('name','')}")

                    elif t == "file_cancelled":
                        self.bridge.status.emit("Seleção de arquivo cancelada no computador remoto.")

                    elif t == "error":
                        self.bridge.status.emit(msg.get("message","Erro remoto."))

                elif kind == b"D" and self.download_fh:
                    if self.download["received"] + len(payload) > self.download["size"]:
                        raise ValueError("Arquivo excedeu o tamanho declarado")
                    self.download_fh.write(payload)
                    self.download["received"] += len(payload)
                    self.download["hasher"].update(payload)

        except Exception as e:
            if self.connected_flag:
                self.bridge.status.emit(f"Conexão encerrada: {e}")
        finally:
            self.connected_flag = False
            if self.download_fh:
                try:
                    self.download_fh.close()
                except Exception:
                    pass
                self.download_fh = None
            if self.download and self.download.get("temp"):
                self.download["temp"].unlink(missing_ok=True)
            self.download = None
            try:
                sock.close()
            except Exception:
                pass
            self.sock = None
            self.bridge.disconnected.emit()

    def _on_connected(self, name, ip):
        self.title_label.setText(f"●  {name}  •  {ip}")
        self.title_label.setObjectName("SessionTitleOnline")
        self.title_label.style().unpolish(self.title_label)
        self.title_label.style().polish(self.title_label)
        self.status_label.setText("Conectado • arraste arquivos sobre a tela para enviar")
        self.send_btn.setEnabled(True)
        self.receive_btn.setEnabled(True)
        self.screen.setFocus()
        self.titleChanged.emit(name)
        self.stateChanged.emit("connected")

    def _on_failed(self, msg):
        self.status_label.setText(f"Falha: {msg}")
        self.screen.clear()
        self.screen.setText("Não foi possível conectar.\n\n" + msg)
        self.disconnect_btn.setText("Fechar aba")
        self.stateChanged.emit("failed")

    def _on_disconnected(self):
        self.connected_flag = False
        self.send_btn.setEnabled(False)
        self.receive_btn.setEnabled(False)
        self.status_label.setText("Desconectado")
        self.disconnect_btn.setText("Fechar aba")
        self.stateChanged.emit("disconnected")

    def _on_status(self, text):
        self.status_label.setText(text)

    def _on_frame(self, pil_img):
        self.last_pil = pil_img
        self._draw_frame()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.last_pil is not None:
            self._draw_frame()

    def _draw_frame(self):
        if self.last_pil is None:
            return
        img = self.last_pil
        data = img.tobytes("raw","RGB")
        qimg = QImage(data, img.width, img.height, img.width*3, QImage.Format_RGB888)
        pix = QPixmap.fromImage(qimg)
        area = self.screen.size()
        scaled = pix.scaled(area, Qt.KeepAspectRatio, Qt.FastTransformation)
        self.screen.setPixmap(scaled)
        x = (area.width()-scaled.width())//2
        y = (area.height()-scaled.height())//2
        self.screen.set_remote_size(self.remote_w, self.remote_h)
        self.screen.set_draw_rect((x,y,scaled.width(),scaled.height()))

    def _mouse_move(self, x, y):
        now = time.time()
        if now - self.last_mouse_send < MOUSE_MOVE_INTERVAL:
            return
        self.last_mouse_send = now
        self._safe_send({"type":"mouse_move","x":x,"y":y})

    def _mouse_button(self, x, y, button, down):
        self._safe_send({
            "type":"mouse_down" if down else "mouse_up",
            "x":x,"y":y,"button":button
        })

    def _safe_send(self, obj):
        if not self.connected_flag or not self.sock:
            return
        try:
            send_json(self.sock, obj, self.send_lock)
        except Exception:
            pass

    def choose_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Enviar arquivos")
        if files:
            self.send_files(files)

    def send_files(self, files):
        valid = [str(Path(p)) for p in files if Path(p).is_file()]
        if not valid:
            return
        if not self.connected_flag:
            QMessageBox.warning(self, APP_NAME, "A sessão ainda não está conectada.")
            return
        threading.Thread(target=self._send_files_thread, args=(valid,), daemon=True).start()

    def _send_files_thread(self, files):
        try:
            with self.transfer_lock:
                total = len(files)
                for idx, path in enumerate(files, 1):
                    p = Path(path)
                    size = p.stat().st_size
                    if size > MAX_FILE_SIZE:
                        raise ValueError(f"{p.name} excede o limite de 10 GB")
                    digest = file_sha256(p)
                    self.bridge.status.emit(f"Enviando {p.name} ({idx}/{total})…")
                    self.bridge.progress.emit(0)
                    send_json(self.sock, {
                        "type":"file_start", "name":p.name, "size":size, "sha256":digest,
                    }, self.send_lock)
                    sent = 0
                    with p.open("rb") as fh:
                        while True:
                            chunk = fh.read(256*1024)
                            if not chunk:
                                break
                            send_frame(self.sock, b"U", chunk, self.send_lock)
                            sent += len(chunk)
                            pct = 100 if size == 0 else int(sent*100/size)
                            self.bridge.progress.emit(pct)
                    send_json(self.sock, {
                        "type":"file_end", "name":p.name, "sha256":digest,
                    }, self.send_lock)
                    if self.event_callback and self.relay_session:
                        self.event_callback(
                            "file_sent", self.relay_session,
                            {"direction": "controller_to_host", "size": size},
                        )
            self.bridge.status.emit(f"{total} arquivo(s) enviado(s).")
            self.bridge.progress.emit(100)
            time.sleep(.5)
            self.bridge.progress.emit(-1)
        except Exception as e:
            self.bridge.status.emit(f"Falha no envio: {e}")
            self.bridge.progress.emit(-1)

    def _set_progress(self, value):
        if value < 0:
            self.progress.hide()
            return
        self.progress.show()
        self.progress.setValue(max(0,min(100,value)))

    def request_file(self):
        self._safe_send({"type":"request_file"})
        self.status_label.setText("Aguardando o usuário remoto escolher um arquivo…")

    def disconnect(self):
        if self.connected_flag and self.sock:
            try:
                send_json(self.sock, {"type":"disconnect"}, self.send_lock)
            except Exception:
                pass
        self.connected_flag = False
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
        self.sock = None
        self.closed.emit(self)


class _OpenSessionEvent(QEvent):
    TYPE = QEvent.Type(QEvent.registerEventType())

    def __init__(self, peer, sid, pin, error=""):
        super().__init__(self.TYPE)
        self.peer = peer
        self.sid = sid
        self.pin = pin
        self.error = error


class _RelayFallbackEvent(QEvent):
    TYPE = QEvent.Type(QEvent.registerEventType())

    def __init__(self, sid, pin):
        super().__init__(self.TYPE)
        self.sid = sid
        self.pin = pin


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} - Suporte Remoto")
        self.setWindowIcon(QIcon(resource_path("assets/conectapc.ico")))
        self.resize(1180, 780)
        self.setMinimumSize(980, 680)

        self.identity = load_or_create_identity(app_data_dir())
        self.known_peers = load_known_peers(app_data_dir())
        self.session_id = self.identity.device_id
        self.pin = random_pin()
        self.ip = local_ip()
        self.recents = load_recents()
        self.sessions = []
        self.session_titles = {}
        self.session_states = {}
        self.session_view_mode = "tabs"
        self.last_tab_session = None

        self.bridge = UiBridge()
        self.bridge.host_status.connect(self._set_status)
        self.bridge.internet_status.connect(self._set_internet_status)
        self.bridge.host_connections.connect(self._set_incoming_count)
        self.bridge.ask_accept.connect(self._ask_accept_ui)
        self.bridge.ask_file.connect(self._ask_file_ui)
        self.bridge.notify.connect(lambda t,m: QMessageBox.information(self,t,m))
        self.bridge.pin_changed.connect(self._set_new_pin)
        self.bridge.update_ready.connect(self._offer_update)
        self.bridge.update_status.connect(self._set_update_status)

        self.discovery = DiscoveryService(self.session_id)
        self.host = HostService(
            self.session_id, self.pin, self.identity, self.known_peers, self.bridge
        )
        self.relay = RelayClient(
            self.session_id,
            self.identity,
            self.host,
            self.bridge,
            resource_path("relay_config.json"),
            APP_VERSION,
        )
        self.host.audit_callback = self.relay.record_consent
        self.host.event_callback = self.relay.record_event

        self._build_ui()
        self.discovery.start()
        self.host.start()
        self.relay.start()

        self.f11_shortcut = QShortcut(QKeySequence("F11"), self)
        self.f11_shortcut.setContext(Qt.ApplicationShortcut)
        self.f11_shortcut.activated.connect(self.toggle_fullscreen)

        self.esc_shortcut = QShortcut(QKeySequence("Esc"), self)
        self.esc_shortcut.setContext(Qt.ApplicationShortcut)
        self.esc_shortcut.activated.connect(self._escape_action)

    def _build_ui(self):
        self.stack = QStackedWidget()
        self.dashboard_page = self._build_dashboard_page()
        self.remote_page = self._build_remote_page()

        self.stack.addWidget(self.dashboard_page)
        self.stack.addWidget(self.remote_page)
        self.setCentralWidget(self.stack)
        self.stack.setCurrentWidget(self.dashboard_page)
        self._update_session_ui()

    def _build_dashboard_page(self):
        root = QWidget()
        root.setObjectName("Root")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0,0,0,0)
        outer.setSpacing(0)

        # Header
        header = QFrame()
        header.setObjectName("Header")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(30,15,30,15)
        hl.setSpacing(14)

        logo = QLabel()
        pix = QPixmap(resource_path("assets/conectapc-logo.png"))
        logo.setPixmap(pix.scaled(52,52,Qt.KeepAspectRatio,Qt.SmoothTransformation))
        logo.setFixedSize(58,58)
        hl.addWidget(logo)

        title_box = QVBoxLayout()
        title_box.setSpacing(1)
        title = QLabel(APP_NAME)
        title.setObjectName("AppTitle")
        title_box.addWidget(title)
        subtitle = QLabel("Suporte remoto seguro")
        subtitle.setObjectName("BrandSubtitle")
        title_box.addWidget(subtitle)
        hl.addLayout(title_box)

        hl.addStretch(1)

        status_box = QVBoxLayout()
        status_box.setSpacing(5)
        status_caption = QLabel("STATUS DE CONEXÃO")
        status_caption.setObjectName("HeaderEyebrow")
        status_caption.setAlignment(Qt.AlignRight)
        status_box.addWidget(status_caption)

        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        self.status_badge = QLabel("LAN inicializando…")
        self.status_badge.setObjectName("StatusOffline")
        status_row.addWidget(self.status_badge)

        self.internet_badge = QLabel("Internet inicializando…")
        self.internet_badge.setObjectName("StatusOffline")
        status_row.addWidget(self.internet_badge)
        status_box.addLayout(status_row)
        hl.addLayout(status_box)

        outer.addWidget(header)

        body = QWidget()
        body.setMinimumWidth(0)
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(30,18,30,16)
        body_layout.setSpacing(14)

        intro = QHBoxLayout()
        intro_text = QVBoxLayout()
        intro_text.setSpacing(2)
        page_title = QLabel("Nova sessão")
        page_title.setObjectName("PageTitle")
        intro_text.addWidget(page_title)
        page_subtitle = QLabel(
            "Conecte-se a outro computador ou compartilhe seu endereço de acesso."
        )
        page_subtitle.setObjectName("PageSubtitle")
        page_subtitle.setWordWrap(True)
        page_subtitle.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        intro_text.addWidget(page_subtitle)
        intro.addLayout(intro_text, 1)

        secure_badge = QLabel("●  LAN disponível")
        secure_badge.setObjectName("SecureBadge")
        intro.addWidget(secure_badge, 0, Qt.AlignBottom)
        body_layout.addLayout(intro)

        cards_container = QWidget()
        cards_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        cards = QHBoxLayout(cards_container)
        cards.setContentsMargins(0,0,0,0)
        cards.setSpacing(16)

        # Este computador
        local_card = QFrame()
        local_card.setObjectName("LocalCard")
        local_card.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Maximum)
        ll = QVBoxLayout(local_card)
        ll.setContentsMargins(20,17,20,17)
        ll.setSpacing(10)

        local_head = QHBoxLayout()
        local_head.setSpacing(8)
        local_title = QLabel("Este dispositivo")
        local_title.setObjectName("CardTitle")
        local_head.addWidget(local_title)
        local_head.addStretch(1)
        local_ready = QLabel("ONLINE")
        local_ready.setObjectName("AvailabilityBadge")
        local_head.addWidget(local_ready)
        ll.addLayout(local_head)

        local_subtitle = QLabel("Compartilhe seu endereço e o código para receber acesso.")
        local_subtitle.setObjectName("CardDescription")
        local_subtitle.setWordWrap(True)
        local_subtitle.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        ll.addWidget(local_subtitle)

        id_field = QFrame()
        id_field.setObjectName("IdentityField")
        id_field_layout = QVBoxLayout(id_field)
        id_field_layout.setContentsMargins(14,9,12,9)
        id_field_layout.setSpacing(3)
        lbl_id = QLabel("SEU ENDEREÇO")
        lbl_id.setObjectName("FieldEyebrow")
        id_field_layout.addWidget(lbl_id)
        idrow = QHBoxLayout()
        self.id_value = QLabel(pretty_id(self.session_id))
        self.id_value.setObjectName("LocalValue")
        idrow.addWidget(self.id_value, 1)
        copy_id = QPushButton("⧉")
        copy_id.setObjectName("CopyButton")
        copy_id.setToolTip("Copiar ID")
        copy_id.clicked.connect(lambda: QApplication.clipboard().setText(self.session_id))
        idrow.addWidget(copy_id)
        id_field_layout.addLayout(idrow)
        ll.addWidget(id_field)

        pin_field = QFrame()
        pin_field.setObjectName("IdentityField")
        pin_field_layout = QVBoxLayout(pin_field)
        pin_field_layout.setContentsMargins(14,9,12,9)
        pin_field_layout.setSpacing(3)
        lbl_pin = QLabel("Código temporário")
        lbl_pin.setText("CÓDIGO TEMPORÁRIO")
        lbl_pin.setObjectName("FieldEyebrow")
        pin_field_layout.addWidget(lbl_pin)

        pinrow = QHBoxLayout()
        self.pin_value = QLabel(self.pin)
        self.pin_value.setObjectName("PinValue")
        pinrow.addWidget(self.pin_value, 1)
        copy_pin = QPushButton("⧉")
        copy_pin.setObjectName("CopyButton")
        copy_pin.setToolTip("Copiar código temporário")
        copy_pin.clicked.connect(lambda: QApplication.clipboard().setText(self.pin))
        pinrow.addWidget(copy_pin)
        pin_field_layout.addLayout(pinrow)
        ll.addWidget(pin_field)

        self.incoming_label = QLabel("●  Aguardando solicitação de acesso")
        self.incoming_label.setObjectName("IncomingStatus")
        ll.addWidget(self.incoming_label)

        cards.addWidget(local_card, 1)

        # Acessar
        remote_card = QFrame()
        remote_card.setObjectName("RemoteCard")
        remote_card.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Maximum)
        rl = QVBoxLayout(remote_card)
        rl.setContentsMargins(20,17,20,17)
        rl.setSpacing(9)

        remote_head = QHBoxLayout()
        rt = QLabel("Endereço remoto")
        rt.setObjectName("CardTitle")
        remote_head.addWidget(rt)
        remote_head.addStretch(1)
        remote_badge = QLabel("CONECTAR")
        remote_badge.setObjectName("PrimaryBadge")
        remote_head.addWidget(remote_badge)
        rl.addLayout(remote_head)

        remote_subtitle = QLabel("Digite o endereço e o código exibidos no dispositivo remoto.")
        remote_subtitle.setObjectName("CardDescription")
        remote_subtitle.setWordWrap(True)
        remote_subtitle.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        rl.addWidget(remote_subtitle)

        labels = QHBoxLayout()
        lid = QLabel("ID do computador")
        lid.setObjectName("FieldLabel")
        lpin = QLabel("Código temporário")
        lpin.setObjectName("FieldLabel")
        labels.addWidget(lid, 3)
        labels.addWidget(lpin, 1)
        rl.addLayout(labels)

        fields = QHBoxLayout()
        self.remote_id = QLineEdit()
        self.remote_id.setPlaceholderText("Insira o ID do computador")
        self.remote_id.setMaxLength(12)
        fields.addWidget(self.remote_id, 3)

        self.remote_pin = QLineEdit()
        self.remote_pin.setPlaceholderText("6 dígitos")
        self.remote_pin.setMaxLength(6)
        self.remote_pin.setEchoMode(QLineEdit.Password)
        self.remote_pin.returnPressed.connect(self.connect_remote)
        fields.addWidget(self.remote_pin, 1)
        rl.addLayout(fields)

        self.connect_btn = QPushButton("Conectar")
        self.connect_btn.setObjectName("Primary")
        self.connect_btn.clicked.connect(self.connect_remote)
        rl.addWidget(self.connect_btn)

        self.login_btn = QPushButton("Entrar como técnico")
        self.login_btn.setObjectName("Secondary")
        self.login_btn.setEnabled(self.relay.is_ready())
        self.login_btn.clicked.connect(self._login_technician_ui)
        rl.addWidget(self.login_btn)

        self.enroll_btn = QPushButton("Cadastrar este computador")
        self.enroll_btn.setVisible(self.relay.enabled and not self.identity.device_token)
        self.enroll_btn.clicked.connect(self._enroll_device_ui)
        rl.addWidget(self.enroll_btn)

        access_security = QFrame()
        access_security.setObjectName("AccessSecurity")
        access_security_layout = QHBoxLayout(access_security)
        access_security_layout.setContentsMargins(11,7,11,7)
        access_security_layout.setSpacing(7)
        security_icon = QLabel("✓")
        security_icon.setObjectName("SecurityIcon")
        access_security_layout.addWidget(security_icon)
        info = QLabel(
            "Rede local disponível agora  •  Servidor usado automaticamente quando configurado"
        )
        info.setWordWrap(True)
        info.setObjectName("SecurityText")
        info.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        access_security_layout.addWidget(info, 1)
        rl.addWidget(access_security)

        cards.addWidget(remote_card, 1)
        body_layout.addWidget(cards_container)

        self.active_sessions_banner = QFrame()
        self.active_sessions_banner.setObjectName("ActiveSessions")
        active_layout = QHBoxLayout(self.active_sessions_banner)
        active_layout.setContentsMargins(16,11,16,11)
        active_layout.setSpacing(12)

        active_icon = QLabel("▣")
        active_icon.setObjectName("ActiveSessionsIcon")
        active_layout.addWidget(active_icon)

        active_text = QVBoxLayout()
        active_text.setSpacing(1)
        self.active_sessions_title = QLabel("Sessões em andamento")
        self.active_sessions_title.setObjectName("ActiveSessionsTitle")
        active_text.addWidget(self.active_sessions_title)
        active_hint = QLabel("As conexões continuam abertas enquanto você inicia outro acesso.")
        active_hint.setObjectName("Muted")
        active_hint.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        active_text.addWidget(active_hint)
        active_layout.addLayout(active_text, 1)

        return_sessions = QPushButton("Voltar às sessões")
        return_sessions.setObjectName("PrimaryCompact")
        return_sessions.clicked.connect(self.show_remote)
        active_layout.addWidget(return_sessions)
        self.active_sessions_banner.hide()
        body_layout.addWidget(self.active_sessions_banner)

        # Recentes
        recent_card = QFrame()
        recent_card.setObjectName("Card")
        recent_card.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Maximum)
        rcl = QVBoxLayout(recent_card)
        rcl.setContentsMargins(20,16,20,16)
        rcl.setSpacing(10)

        recent_header = QHBoxLayout()
        recent_heading = QVBoxLayout()
        recent_heading.setSpacing(1)
        recent_title = QLabel("Sessões recentes")
        recent_title.setObjectName("SectionTitle")
        recent_heading.addWidget(recent_title)
        recent_subtitle = QLabel("Seus computadores acessados ficam disponíveis aqui.")
        recent_subtitle.setObjectName("CardDescription")
        recent_subtitle.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        recent_heading.addWidget(recent_subtitle)
        recent_header.addLayout(recent_heading)
        recent_header.addStretch(1)

        self.clear_recents_btn = QPushButton("Limpar histórico")
        self.clear_recents_btn.setObjectName("Ghost")
        self.clear_recents_btn.clicked.connect(self.clear_recents)
        recent_header.addWidget(self.clear_recents_btn)
        rcl.addLayout(recent_header)

        self.recents_container = QWidget()
        self.recents_layout = QGridLayout(self.recents_container)
        self.recents_layout.setContentsMargins(0,0,0,0)
        self.recents_layout.setHorizontalSpacing(8)
        self.recents_layout.setVerticalSpacing(8)
        for column in range(3):
            self.recents_layout.setColumnStretch(column, 1)
        rcl.addWidget(self.recents_container)

        body_layout.addWidget(recent_card)
        self.refresh_recents_ui()

        # Arquivos / ajuda
        tip = QFrame()
        tip.setObjectName("Tip")
        tip_l = QHBoxLayout(tip)
        tip_l.setContentsMargins(14,9,14,9)
        tip_l.setSpacing(9)
        tip_title = QLabel("i")
        tip_title.setObjectName("TipIcon")
        tip_l.addWidget(tip_title)
        tip_text = QLabel(
            "Cada conexão abre em uma aba. Use “Dividir tela” para acompanhar vários computadores ao mesmo tempo."
        )
        tip_text.setObjectName("TipText")
        tip_text.setWordWrap(True)
        tip_text.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        tip_l.addWidget(tip_text, 1)
        body_layout.addWidget(tip)
        body_layout.addStretch(1)

        dashboard_scroll = QScrollArea()
        dashboard_scroll.setObjectName("DashboardScroll")
        dashboard_scroll.setWidgetResizable(True)
        dashboard_scroll.setFrameShape(QFrame.NoFrame)
        dashboard_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        dashboard_scroll.setWidget(body)
        outer.addWidget(dashboard_scroll, 1)

        footer = QFrame()
        footer.setObjectName("Footer")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(30,9,30,9)
        left = QLabel("●  Conexão local ativa  •  Criptografia ponta a ponta  •  Consentimento")
        left.setObjectName("FooterSecurity")
        fl.addWidget(left)
        fl.addStretch(1)
        ver = QLabel(f"{APP_NAME} {APP_VERSION}")
        ver.setObjectName("FooterVersion")
        fl.addWidget(ver)

        self.update_btn = QPushButton("Verificar atualizações")
        self.update_btn.setObjectName("FooterButton")
        self.update_btn.clicked.connect(self._check_updates)
        fl.addWidget(self.update_btn)

        self.rollback_btn = QPushButton("Restaurar versão anterior")
        self.rollback_btn.setVisible(rollback_available(app_data_dir()))
        self.rollback_btn.clicked.connect(self._apply_rollback)
        fl.addWidget(self.rollback_btn)
        outer.addWidget(footer)

        return root

    def _build_remote_page(self):
        page = QWidget()
        page.setObjectName("Root")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0,0,0,0)
        layout.setSpacing(0)

        self.remote_topbar = QFrame()
        self.remote_topbar.setObjectName("Header")
        top = QHBoxLayout(self.remote_topbar)
        top.setContentsMargins(12,8,12,8)
        top.setSpacing(8)

        back = QPushButton("← Início")
        back.clicked.connect(self.show_dashboard)
        top.addWidget(back)

        logo = QLabel()
        pix = QPixmap(resource_path("assets/conectapc-logo.png"))
        logo.setPixmap(pix.scaled(32,32,Qt.KeepAspectRatio,Qt.SmoothTransformation))
        logo.setFixedSize(36,36)
        top.addWidget(logo)

        title = QLabel("Central de sessões")
        title.setObjectName("SectionTitle")
        top.addWidget(title)

        self.session_count_badge = QLabel("Nenhuma sessão")
        self.session_count_badge.setObjectName("SessionCount")
        top.addWidget(self.session_count_badge)
        top.addStretch(1)

        self.tabs_view_btn = QPushButton("▣  Abas")
        self.tabs_view_btn.setObjectName("ViewMode")
        self.tabs_view_btn.setCheckable(True)
        self.tabs_view_btn.setChecked(True)
        self.tabs_view_btn.clicked.connect(lambda: self._set_session_view("tabs"))
        top.addWidget(self.tabs_view_btn)

        self.split_view_btn = QPushButton("▦  Dividir tela")
        self.split_view_btn.setObjectName("ViewMode")
        self.split_view_btn.setCheckable(True)
        self.split_view_btn.setToolTip("Mostra dois ou mais computadores ao mesmo tempo")
        self.split_view_btn.clicked.connect(lambda: self._set_session_view("split"))
        top.addWidget(self.split_view_btn)

        new_session = QPushButton("＋  Novo acesso")
        new_session.setObjectName("PrimaryCompact")
        new_session.clicked.connect(self.show_dashboard)
        top.addWidget(new_session)

        self.fullscreen_btn = QPushButton("Tela cheia  F11")
        self.fullscreen_btn.clicked.connect(self.toggle_fullscreen)
        top.addWidget(self.fullscreen_btn)

        layout.addWidget(self.remote_topbar)

        self.session_views = QStackedWidget()

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.tabBar().setExpanding(False)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        self.tabs.currentChanged.connect(self._current_session_changed)
        self.session_views.addWidget(self.tabs)

        self.split_page = QWidget()
        self.split_page.setObjectName("SplitPage")
        self.split_layout = QGridLayout(self.split_page)
        self.split_layout.setContentsMargins(8,8,8,8)
        self.split_layout.setHorizontalSpacing(8)
        self.split_layout.setVerticalSpacing(8)
        self.session_views.addWidget(self.split_page)

        layout.addWidget(self.session_views, 1)

        return page

    def refresh_recents_ui(self):
        while self.recents_layout.count():
            item = self.recents_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        self.clear_recents_btn.setEnabled(bool(self.recents))

        if not self.recents:
            empty = QLabel("Nenhum computador acessado recentemente.")
            empty.setObjectName("Muted")
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet("padding:24px;")
            self.recents_layout.addWidget(empty, 0, 0, 1, 3)
            return

        for index, item in enumerate(self.recents[:6]):
            tile = QFrame()
            tile.setObjectName("RecentRow")
            tile.setMinimumHeight(104)
            tile.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            tile_layout = QVBoxLayout(tile)
            tile_layout.setContentsMargins(12,10,12,10)
            tile_layout.setSpacing(7)

            top = QHBoxLayout()
            top.setSpacing(9)
            recent_icon = QLabel("PC")
            recent_icon.setObjectName("RecentIcon")
            recent_icon.setAlignment(Qt.AlignCenter)
            recent_icon.setFixedSize(36,36)
            top.addWidget(recent_icon)

            name_box = QVBoxLayout()
            name_box.setSpacing(1)
            name = QLabel(item.get("name") or "Computador")
            name.setObjectName("RecentName")
            name.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            name_box.addWidget(name)

            details = QLabel(
                f"{pretty_id(item['id'])}  •  {item.get('last_access','')}"
            )
            details.setObjectName("RecentMeta")
            details.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            name_box.addWidget(details)
            top.addLayout(name_box, 1)
            tile_layout.addLayout(top)

            use_btn = QPushButton("Conectar")
            use_btn.setObjectName("RecentAction")
            use_btn.clicked.connect(
                lambda checked=False, sid=item["id"]: self.use_recent(sid)
            )
            tile_layout.addWidget(use_btn)

            self.recents_layout.addWidget(tile, index // 3, index % 3)

    def use_recent(self, sid):
        self.remote_id.setText(pretty_id(sid))
        self.remote_pin.clear()
        self.remote_pin.setFocus()

    def clear_recents(self):
        if not self.recents:
            return
        answer = QMessageBox.question(
            self,
            "Limpar histórico",
            "Deseja remover a lista de últimos acessos?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self.recents = []
        save_recents(self.recents)
        self.refresh_recents_ui()

    def remember_access(self, sid, name):
        now = time.strftime("%d/%m/%Y %H:%M")
        self.recents = [
            item for item in self.recents
            if item.get("id") != sid
        ]
        self.recents.insert(0, {
            "id": sid,
            "name": name or "Computador",
            "last_access": now,
        })
        self.recents = self.recents[:8]
        save_recents(self.recents)
        self.refresh_recents_ui()

    def show_dashboard(self):
        if self.isFullScreen():
            self.showNormal()
        self._set_immersive(False)
        self.stack.setCurrentWidget(self.dashboard_page)
        self.remote_id.setFocus()

    def show_remote(self):
        if not self.sessions:
            self.show_dashboard()
            return
        self.stack.setCurrentWidget(self.remote_page)
        if self.session_view_mode == "tabs":
            current = self.tabs.currentWidget()
            if isinstance(current, RemoteSession):
                current.screen.setFocus()

    def _set_immersive(self, enabled):
        self.remote_topbar.setVisible(not enabled)
        self.tabs.tabBar().setVisible(not enabled)
        targets = self.sessions if self.session_view_mode == "split" else [self.tabs.currentWidget()]
        for session in targets:
            if isinstance(session, RemoteSession):
                session.set_immersive(enabled)

    def toggle_fullscreen(self):
        if self.stack.currentWidget() != self.remote_page:
            return

        if self.isFullScreen():
            self.showNormal()
            self._set_immersive(False)
            self.fullscreen_btn.setText("Tela cheia  F11")
        else:
            self._set_immersive(True)
            self.showFullScreen()
            self.fullscreen_btn.setText("Sair da tela cheia  F11")

    def _escape_action(self):
        if self.isFullScreen():
            self.showNormal()
            self._set_immersive(False)
            self.fullscreen_btn.setText("Tela cheia  F11")

    def _current_session_changed(self, _index):
        current = self.tabs.currentWidget()
        if isinstance(current, RemoteSession):
            self.last_tab_session = current
        if self.isFullScreen():
            if isinstance(current, RemoteSession):
                current.set_immersive(True)

    def _set_session_view(self, mode):
        if mode not in {"tabs", "split"}:
            return
        if mode == "split" and len(self.sessions) < 2:
            self.tabs_view_btn.setChecked(True)
            self.split_view_btn.setChecked(False)
            return
        if mode == self.session_view_mode:
            self.tabs_view_btn.setChecked(mode == "tabs")
            self.split_view_btn.setChecked(mode == "split")
            return

        if mode == "split":
            current = self.tabs.currentWidget()
            if isinstance(current, RemoteSession):
                self.last_tab_session = current
            tab_order = [
                self.tabs.widget(index) for index in range(self.tabs.count())
                if isinstance(self.tabs.widget(index), RemoteSession)
            ]
            if len(tab_order) == len(self.sessions):
                self.sessions = tab_order
            for session in self.sessions:
                idx = self.tabs.indexOf(session)
                if idx >= 0:
                    self.tabs.removeTab(idx)
                session.set_compact_mode(True)
            self._refresh_split_layout()
            self.session_views.setCurrentWidget(self.split_page)
        else:
            self._clear_split_layout()
            for session in self.sessions:
                session.set_compact_mode(False)
                self.tabs.addTab(session, self._session_tab_text(session))
            if self.last_tab_session in self.sessions:
                self.tabs.setCurrentWidget(self.last_tab_session)
            self.session_views.setCurrentWidget(self.tabs)

        self.session_view_mode = mode
        self.tabs_view_btn.setChecked(mode == "tabs")
        self.split_view_btn.setChecked(mode == "split")

    def _clear_split_layout(self):
        while self.split_layout.count():
            item = self.split_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.hide()

    def _refresh_split_layout(self):
        self._clear_split_layout()
        count = len(self.sessions)
        columns = 1 if count <= 1 else (2 if count <= 4 else 3)
        for index, session in enumerate(self.sessions):
            row, column = divmod(index, columns)
            if count == 3 and index == 2:
                self.split_layout.addWidget(session, row, 0, 1, 2)
            else:
                self.split_layout.addWidget(session, row, column)
            session.show()

    def _session_tab_text(self, session):
        state = self.session_states.get(session, "connecting")
        marker = {
            "connected": "●",
            "failed": "!",
            "disconnected": "○",
            "connecting": "◌",
        }.get(state, "◌")
        return f"{marker}  {self.session_titles.get(session, 'Computador')}"

    def _session_state_changed(self, session, state):
        if session not in self.sessions:
            return
        self.session_states[session] = state
        idx = self.tabs.indexOf(session)
        if idx >= 0:
            self.tabs.setTabText(idx, self._session_tab_text(session))
        self._update_session_ui()

    def _update_session_ui(self):
        count = len(self.sessions)
        connected = sum(
            1 for session in self.sessions
            if self.session_states.get(session) == "connected"
        )
        if count == 0:
            summary = "Nenhuma sessão"
        elif count == 1:
            summary = "1 sessão aberta"
        else:
            summary = f"{count} sessões abertas"
        if connected:
            summary += f"  •  {connected} conectada" + ("s" if connected != 1 else "")

        self.session_count_badge.setText(summary)
        self.split_view_btn.setEnabled(count >= 2)
        self.active_sessions_banner.setVisible(count > 0)
        if count == 1:
            self.active_sessions_title.setText("1 sessão continua aberta")
        elif count > 1:
            self.active_sessions_title.setText(f"{count} sessões continuam abertas")

        if count < 2 and self.session_view_mode == "split":
            self._set_session_view("tabs")

    def _set_status(self, text, online):
        self.status_badge.setText("● " + text)
        self.status_badge.setObjectName("StatusOnline" if online else "StatusOffline")
        self.status_badge.style().unpolish(self.status_badge)
        self.status_badge.style().polish(self.status_badge)

    def _set_internet_status(self, text, online):
        if not self.relay.enabled:
            self.internet_badge.setText("○ Servidor opcional")
            self.internet_badge.setObjectName("StatusOptional")
        else:
            self.internet_badge.setText("● " + text)
            self.internet_badge.setObjectName(
                "StatusOnline" if online else "StatusOffline"
            )
        self.internet_badge.style().unpolish(self.internet_badge)
        self.internet_badge.style().polish(self.internet_badge)
        if hasattr(self, "enroll_btn"):
            self.enroll_btn.setVisible(self.relay.enabled and not self.identity.device_token)
        if hasattr(self, "login_btn"):
            self.login_btn.setEnabled(bool(online))

    def _set_incoming_count(self, n):
        if n == 0:
            self.incoming_label.setText("●  Aguardando solicitação de acesso")
        elif n == 1:
            self.incoming_label.setText("●  1 sessão de suporte ativa")
        else:
            self.incoming_label.setText(f"●  {n} sessões de suporte ativas")

    def _set_new_pin(self, pin):
        self.pin = pin
        self.pin_value.setText(pin)

    def _set_update_status(self, text):
        self.update_btn.setText(text)
        self.update_btn.setEnabled(text == "Verificar atualizações")

    def _check_updates(self):
        self.update_btn.setEnabled(False)
        self.update_btn.setText("Verificando…")
        threading.Thread(target=self._check_updates_thread, daemon=True).start()

    def _check_updates_thread(self):
        try:
            path, manifest = check_and_download(
                self.relay.config.get("updates") or {}, APP_VERSION, app_data_dir()
            )
            if path is None:
                self.bridge.notify.emit("Atualizações", "O ConectaPC já está atualizado.")
            else:
                self.bridge.update_ready.emit(str(path), str(manifest["version"]))
        except Exception as exc:
            self.bridge.notify.emit("Atualizações", str(exc))
        finally:
            self.bridge.update_status.emit("Verificar atualizações")

    def _offer_update(self, path, version):
        answer = QMessageBox.question(
            self, "Atualização verificada",
            f"A versão {version} foi baixada e teve assinatura e SHA-256 validados.\n\nInstalar agora?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            apply_update(path, app_data_dir())
            QApplication.quit()

    def _apply_rollback(self):
        answer = QMessageBox.question(
            self, "Restaurar versão anterior",
            "Deseja executar o instalador da versão anterior verificada?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            try:
                apply_rollback(app_data_dir())
                QApplication.quit()
            except Exception as exc:
                QMessageBox.critical(self, "Restauração", str(exc))

    def _login_technician_ui(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Identificação do técnico")
        form = QFormLayout(dialog)
        username = QLineEdit()
        password = QLineEdit()
        password.setEchoMode(QLineEdit.Password)
        otp = QLineEdit()
        otp.setMaxLength(6)
        otp.setPlaceholderText("Código de 6 dígitos do autenticador")
        form.addRow("Usuário", username)
        form.addRow("Senha", password)
        form.addRow("MFA", otp)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() != QDialog.Accepted:
            return False

    def _enroll_device_ui(self):
        token, ok = QInputDialog.getText(
            self, "Cadastrar computador",
            "Informe o código de cadastro de uso único gerado no servidor:",
            QLineEdit.Password,
        )
        if not ok:
            return
        try:
            self.relay.set_enrollment_token(token)
            QMessageBox.information(
                self, "Cadastro",
                "Código recebido. O cadastro será concluído automaticamente pelo relay.",
            )
        except Exception as exc:
            QMessageBox.critical(self, "Cadastro", str(exc))
        try:
            name = self.relay.login_technician(username.text(), password.text(), otp.text())
            self.login_btn.setText(f"Técnico: {name}")
            return True
        except Exception as exc:
            QMessageBox.critical(self, "Autenticação", str(exc))
            return False

    def _ask_accept_ui(self, controller, ip, response):
        box = QMessageBox(self)
        box.setWindowTitle("Solicitação de acesso")
        box.setIcon(QMessageBox.Question)
        box.setText(f"{controller} deseja acessar este computador.")
        box.setInformativeText(
            f"Origem: {ip}\n\n"
            "Permissões solicitadas:\n"
            "• Visualizar a tela\n"
            "• Controlar mouse e teclado\n"
            "• Transferir arquivos\n\n"
            "Deseja permitir esta conexão?"
        )
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.button(QMessageBox.Yes).setText("Permitir")
        box.button(QMessageBox.No).setText("Recusar")
        response["ok"] = box.exec() == QMessageBox.Yes
        response["event"].set()

    def _ask_file_ui(self, response):
        path, _ = QFileDialog.getOpenFileName(self, "Escolha um arquivo para enviar")
        response["path"] = path or None
        response["event"].set()

    def connect_remote(self):
        sid = "".join(c for c in self.remote_id.text() if c.isdigit())
        pin = "".join(c for c in self.remote_pin.text() if c.isdigit())

        if len(sid) != 9 or len(pin) != 6:
            QMessageBox.warning(
                self,
                APP_NAME,
                "Informe um ID de 9 dígitos e um código temporário de 6 dígitos.",
            )
            return

        if sid == self.session_id:
            QMessageBox.warning(self, APP_NAME, "Esse é o ID deste próprio computador.")
            return

        self.connect_btn.setEnabled(False)
        self.connect_btn.setText("Localizando…")
        threading.Thread(
            target=self._locate_peer,
            args=(sid, pin),
            daemon=True,
        ).start()

    def _locate_peer(self, sid, pin):
        # 1) LAN primeiro: mais rápido e não consome banda do servidor.
        peer = None
        deadline = time.time() + 2.0

        while time.time() < deadline:
            peer = self.discovery.find_peer(sid)
            if peer:
                break
            time.sleep(.20)

        if peer:
            peer["expected_peer_key"] = self.known_peers.expected("target:" + sid)
            QApplication.instance().postEvent(
                self,
                _OpenSessionEvent(peer, sid, pin),
            )
            return

        # A decisão de usar o relay volta para a thread da interface. Isso
        # permite solicitar MFA somente depois de confirmar que o ID não está
        # disponível na rede local.
        QApplication.instance().postEvent(
            self,
            _RelayFallbackEvent(sid, pin),
        )

    def _connect_via_relay(self, sid, pin):
        try:
            tunnel, meta = self.relay.open_controller_tunnel(sid)
            known_key = self.known_peers.expected("target:" + sid)
            target_key = meta.get("target_key") or ""
            if known_key and not secrets.compare_digest(known_key, target_key):
                tunnel.close()
                raise RelayError("A identidade conhecida do computador remoto mudou. Conexão bloqueada.")
            relay_peer = {
                "name": meta.get("name") or f"PC {sid}",
                "ip": "Internet via relay",
                "port": 0,
                "mode": "relay",
                "_preconnected_socket": tunnel,
                "expected_peer_key": meta.get("target_key") or None,
                "relay_session": meta.get("session") or "",
            }
            QApplication.instance().postEvent(
                self,
                _OpenSessionEvent(relay_peer, sid, pin),
            )
        except Exception as exc:
            QApplication.instance().postEvent(
                self,
                _OpenSessionEvent(None, sid, pin, str(exc)),
            )

    def customEvent(self, event):
        if isinstance(event, _RelayFallbackEvent):
            if not self.relay.enabled:
                self.connect_btn.setEnabled(True)
                self.connect_btn.setText("Conectar")
                QMessageBox.information(
                    self,
                    APP_NAME,
                    "Esse ID não foi encontrado na rede local.\n\n"
                    "O modo local continua disponível sem servidor. Para acessar "
                    "computadores fora da rede, configure o VPS depois.",
                )
                return

            if not self.relay.is_ready():
                self.connect_btn.setEnabled(True)
                self.connect_btn.setText("Conectar")
                QMessageBox.warning(
                    self,
                    APP_NAME,
                    "Esse ID não foi encontrado na rede local e o servidor está indisponível.\n\n"
                    f"Detalhe: {self.relay.status_detail()}",
                )
                return

            if not self.relay.access_token and not self._login_technician_ui():
                self.connect_btn.setEnabled(True)
                self.connect_btn.setText("Conectar")
                return

            self.connect_btn.setText("Conectando pelo servidor…")
            threading.Thread(
                target=self._connect_via_relay,
                args=(event.sid, event.pin),
                daemon=True,
            ).start()
            return

        if isinstance(event, _OpenSessionEvent):
            self.connect_btn.setEnabled(True)
            self.connect_btn.setText("Conectar")

            if not event.peer:
                detail = event.error or "Servidor de internet indisponível."
                QMessageBox.critical(
                    self,
                    APP_NAME,
                    "Não foi possível conectar a esse ID.\n\n"
                    "O computador não foi encontrado na rede local e a tentativa "
                    "pelo servidor não foi concluída.\n\n"
                    f"Detalhe: {detail}",
                )
                return

            session = RemoteSession(
                event.peer, event.sid, event.pin, self.identity,
                self.relay.technician_name or socket.gethostname(),
                self.relay.record_event,
                self._remember_peer,
            )
            self.sessions.append(session)
            self.session_titles[session] = event.peer["name"]
            self.session_states[session] = "connecting"

            if self.session_view_mode == "tabs":
                idx = self.tabs.addTab(session, self._session_tab_text(session))
                self.tabs.setCurrentIndex(idx)
            else:
                session.set_compact_mode(True)
                self._refresh_split_layout()

            # Sai do dashboard imediatamente e entrega a janela para a sessão.
            self.show_remote()

            session.titleChanged.connect(
                lambda title, s=session, sid=event.sid:
                    self._session_connected(s, sid, title)
            )
            session.stateChanged.connect(
                lambda state, s=session: self._session_state_changed(s, state)
            )
            session.closed.connect(self._close_session_widget)
            self._update_session_ui()

            self.remote_id.clear()
            self.remote_pin.clear()
            return

        super().customEvent(event)

    def _remember_peer(self, sid, public_key, label):
        self.known_peers.remember("target:" + sid, public_key, label)

    def _session_connected(self, session, sid, title):
        self.session_titles[session] = title
        idx = self.tabs.indexOf(session)
        if idx >= 0:
            self.tabs.setTabText(idx, self._session_tab_text(session))
        self.remember_access(sid, title)

    def _close_session_widget(self, session):
        idx = self.tabs.indexOf(session)
        if idx >= 0:
            self.tabs.removeTab(idx)
        self.split_layout.removeWidget(session)
        if session in self.sessions:
            self.sessions.remove(session)
        self.session_titles.pop(session, None)
        self.session_states.pop(session, None)
        if self.last_tab_session is session:
            self.last_tab_session = None
        session.deleteLater()

        if self.session_view_mode == "split" and self.sessions:
            self._refresh_split_layout()
        self._update_session_ui()

        if not self.sessions:
            self.show_dashboard()

    def _close_tab(self, idx):
        widget = self.tabs.widget(idx)
        if isinstance(widget, RemoteSession):
            widget.disconnect()
        else:
            self.tabs.removeTab(idx)

    def closeEvent(self, event):
        for session in list(self.sessions):
            session.disconnect()
        self.relay.stop()
        self.host.stop()
        self.discovery.stop()
        event.accept()

def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setWindowIcon(QIcon(resource_path("assets/conectapc.ico")))
    app.setStyleSheet(APP_QSS)

    try:
        window = MainWindow()
    except Exception as exc:
        QMessageBox.critical(
            None, "Falha de segurança do ConectaPC",
            "Não foi possível carregar a identidade protegida deste computador.\n\n"
            f"Detalhe: {exc}",
        )
        return 1
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
