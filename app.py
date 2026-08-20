from __future__ import annotations

import io
import json
import os
import random
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
    QApplication, QFileDialog, QFrame, QGraphicsDropShadowEffect, QHBoxLayout,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QProgressBar, QPushButton,
    QSizePolicy, QSpacerItem, QStackedWidget, QTabBar, QTabWidget, QVBoxLayout, QWidget
)

from protocol import recv_frame, recv_json_payload, send_frame, send_json
from internet import RelayClient, RelayError
from theme import APP_QSS

APP_NAME = "ConectaPC"
APP_VERSION = "2.0.0"
TCP_PORT = 45888
DISCOVERY_PORT = 45889
SERVICE = "CONECTAPC_LAN_V1"
FPS = 14
JPEG_QUALITY = 48
MAX_WIDTH = 1280
VIDEO_SEND_TIMEOUT = 1.5
MOUSE_MOVE_INTERVAL = 0.018


pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0


def resource_path(relative):
    base = getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)
    return str(Path(base) / relative)


def random_id():
    return f"{random.randint(100_000_000, 999_999_999):09d}"


def random_pin():
    return f"{random.randint(0, 9999):04d}"


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
    def __init__(self, session_id, pin, bridge):
        self.session_id = session_id
        self.pin = pin
        self.bridge = bridge
        self.stop_event = threading.Event()
        self.connections = set()
        self.lock = threading.Lock()

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

    def handle_tunneled_client(self, conn, origin_label="Internet"):
        """Recebe uma conexão já transportada pelo relay.

        A autenticação ID/PIN e o consentimento continuam ocorrendo dentro do
        protocolo normal; o relay apenas transporta os bytes.
        """
        self._handle_client(conn, (origin_label, 0))

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

    def _handle_client(self, conn, addr):
        send_lock = threading.Lock()
        stop_conn = threading.Event()
        try:
            kind, payload = recv_frame(conn)
            if kind != b"J":
                return
            hello = recv_json_payload(payload)
            if hello.get("type") != "hello":
                return

            if hello.get("id") != self.session_id or hello.get("pin") != self.pin:
                send_json(conn, {"type": "hello_error", "message": "ID ou PIN incorreto."}, send_lock)
                return

            if not self._ask_accept(hello.get("controller") or "Técnico", addr[0]):
                send_json(conn, {"type": "hello_error", "message": "Conexão recusada pelo usuário."}, send_lock)
                return

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

            self._command_loop(conn, send_lock, stop_conn)

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

    def _command_loop(self, conn, send_lock, stop_conn):
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
                        name = os.path.basename(msg.get("name", "arquivo.bin"))
                        folder = Path.home() / "Downloads" / "ConectaPC Recebidos"
                        folder.mkdir(parents=True, exist_ok=True)
                        target = unique_path(folder / name)
                        upload = {"path": target, "name": name}
                        upload_fh = open(target, "wb")

                    elif t == "file_end":
                        if upload_fh:
                            upload_fh.close()
                            upload_fh = None
                        if upload:
                            self.bridge.notify.emit(
                                "Arquivo recebido",
                                f"O arquivo foi salvo em:\n{upload['path']}",
                            )
                            send_json(conn, {"type": "file_received", "name": upload["name"]}, send_lock)
                            upload = None

                    elif t == "request_file":
                        path = self._ask_file()
                        if path:
                            threading.Thread(
                                target=self._send_file,
                                args=(conn, send_lock, path),
                                daemon=True,
                            ).start()
                        else:
                            send_json(conn, {"type": "file_cancelled"}, send_lock)

                    elif t == "disconnect":
                        break

                elif kind == b"U" and upload_fh:
                    upload_fh.write(payload)

        finally:
            if upload_fh:
                try:
                    upload_fh.close()
                except Exception:
                    pass
            stop_conn.set()

    def _send_file(self, conn, send_lock, path):
        try:
            p = Path(path)
            size = p.stat().st_size
            send_json(conn, {"type": "download_start", "name": p.name, "size": size}, send_lock)
            with p.open("rb") as fh:
                while True:
                    chunk = fh.read(256 * 1024)
                    if not chunk:
                        break
                    send_frame(conn, b"D", chunk, send_lock)
            send_json(conn, {"type": "download_end", "name": p.name}, send_lock)
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
    closed = Signal(object)

    def __init__(self, peer, sid, pin, parent=None):
        super().__init__(parent)
        self.peer = peer
        self.sid = sid
        self.pin = pin

        self.sock = None
        self.connected_flag = False
        self.send_lock = threading.Lock()
        self.remote_w = 1
        self.remote_h = 1
        self.last_pil = None
        self.last_mouse_send = 0
        self.download_fh = None
        self.download_path = None

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
        self.bottom_widget.setVisible(not enabled)
        layout = self.layout()
        if layout:
            margin = 0 if enabled else 14
            layout.setContentsMargins(margin, margin, margin, margin)
            layout.setSpacing(0 if enabled else 10)
        if enabled:
            self.screen.setStyleSheet(
                "QLabel { background:#050A11; color:#B8C4D2; border:0px; border-radius:0px; }"
            )
        else:
            self.screen.setStyleSheet(
                "QLabel { background:#0C1522; color:#B8C4D2; border-radius:12px; "
                "border:1px solid #1E3147; font-size:11pt; }"
            )

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
            self.sock = sock
            send_json(sock, {
                "type":"hello",
                "id":self.sid,
                "pin":self.pin,
                "controller":socket.gethostname(),
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
                        folder = Path.home() / "Downloads" / "ConectaPC Recebidos"
                        folder.mkdir(parents=True, exist_ok=True)
                        target = unique_path(folder / os.path.basename(msg.get("name","arquivo.bin")))
                        self.download_path = target
                        self.download_fh = open(target, "wb")
                        self.bridge.status.emit(f"Recebendo {target.name}…")

                    elif t == "download_end":
                        if self.download_fh:
                            self.download_fh.close()
                            self.download_fh = None
                        if self.download_path:
                            self.bridge.notify.emit("Arquivo recebido", f"Salvo em:\n{self.download_path}")
                            self.download_path = None

                    elif t == "file_received":
                        self.bridge.status.emit(f"Arquivo enviado: {msg.get('name','')}")

                    elif t == "file_cancelled":
                        self.bridge.status.emit("Seleção de arquivo cancelada no computador remoto.")

                    elif t == "error":
                        self.bridge.status.emit(msg.get("message","Erro remoto."))

                elif kind == b"D" and self.download_fh:
                    self.download_fh.write(payload)

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
            try:
                sock.close()
            except Exception:
                pass
            self.sock = None
            self.bridge.disconnected.emit()

    def _on_connected(self, name, ip):
        self.title_label.setText(f"{name}  •  {ip}")
        self.status_label.setText("Conectado • arraste arquivos sobre a tela para enviar")
        self.send_btn.setEnabled(True)
        self.receive_btn.setEnabled(True)
        self.screen.setFocus()
        self.titleChanged.emit(name)

    def _on_failed(self, msg):
        self.status_label.setText(f"Falha: {msg}")
        self.screen.clear()
        self.screen.setText("Não foi possível conectar.\n\n" + msg)
        self.disconnect_btn.setText("Fechar aba")

    def _on_disconnected(self):
        self.connected_flag = False
        self.send_btn.setEnabled(False)
        self.receive_btn.setEnabled(False)
        self.status_label.setText("Desconectado")
        self.disconnect_btn.setText("Fechar aba")

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
            total = len(files)
            for idx, path in enumerate(files, 1):
                p = Path(path)
                size = p.stat().st_size
                self.bridge.status.emit(f"Enviando {p.name} ({idx}/{total})…")
                self.bridge.progress.emit(0)
                send_json(self.sock, {"type":"file_start","name":p.name,"size":size}, self.send_lock)
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
                send_json(self.sock, {"type":"file_end","name":p.name}, self.send_lock)
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


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} - Suporte Remoto")
        self.setWindowIcon(QIcon(resource_path("assets/conectapc.ico")))
        self.resize(1180, 780)
        self.setMinimumSize(980, 680)

        self.session_id = random_id()
        self.pin = random_pin()
        self.ip = local_ip()
        self.recents = load_recents()

        self.bridge = UiBridge()
        self.bridge.host_status.connect(self._set_status)
        self.bridge.internet_status.connect(self._set_internet_status)
        self.bridge.host_connections.connect(self._set_incoming_count)
        self.bridge.ask_accept.connect(self._ask_accept_ui)
        self.bridge.ask_file.connect(self._ask_file_ui)
        self.bridge.notify.connect(lambda t,m: QMessageBox.information(self,t,m))

        self.discovery = DiscoveryService(self.session_id)
        self.host = HostService(self.session_id, self.pin, self.bridge)
        self.relay = RelayClient(
            self.session_id,
            self.host,
            self.bridge,
            resource_path("relay_config.json"),
            APP_VERSION,
        )

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
        hl.setContentsMargins(26,16,26,16)
        hl.setSpacing(12)

        logo = QLabel()
        pix = QPixmap(resource_path("assets/conectapc-logo.png"))
        logo.setPixmap(pix.scaled(58,58,Qt.KeepAspectRatio,Qt.SmoothTransformation))
        logo.setFixedSize(64,64)
        hl.addWidget(logo)

        title_box = QVBoxLayout()
        title = QLabel(APP_NAME)
        title.setObjectName("AppTitle")
        title_box.addWidget(title)
        subtitle = QLabel("Suporte remoto simples e rápido")
        subtitle.setObjectName("Muted")
        title_box.addWidget(subtitle)
        hl.addLayout(title_box)

        hl.addStretch(1)

        self.status_badge = QLabel("LAN inicializando…")
        self.status_badge.setObjectName("StatusOffline")
        hl.addWidget(self.status_badge)

        self.internet_badge = QLabel("Internet inicializando…")
        self.internet_badge.setObjectName("StatusOffline")
        hl.addWidget(self.internet_badge)

        outer.addWidget(header)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(26,20,26,18)
        body_layout.setSpacing(16)

        cards_container = QWidget()
        cards = QHBoxLayout(cards_container)
        cards.setContentsMargins(0,0,0,0)
        cards.setSpacing(16)

        # Este computador
        local_card = QFrame()
        local_card.setObjectName("LocalCard")
        ll = QVBoxLayout(local_card)
        ll.setContentsMargins(22,18,22,18)
        ll.setSpacing(7)

        local_title = QLabel("Este computador")
        local_title.setObjectName("CardTitle")
        local_title.setStyleSheet("color:#17823A;")
        ll.addWidget(local_title)

        lbl_id = QLabel("Seu ID")
        lbl_id.setObjectName("Muted")
        ll.addWidget(lbl_id)

        idrow = QHBoxLayout()
        self.id_value = QLabel(pretty_id(self.session_id))
        self.id_value.setObjectName("LocalValue")
        idrow.addWidget(self.id_value, 1)
        copy_id = QPushButton("⧉")
        copy_id.setObjectName("CopyButton")
        copy_id.setToolTip("Copiar ID")
        copy_id.clicked.connect(lambda: QApplication.clipboard().setText(self.session_id))
        idrow.addWidget(copy_id)
        ll.addLayout(idrow)

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background:#DCEFE1;")
        ll.addWidget(sep)

        lbl_pin = QLabel("PIN")
        lbl_pin.setObjectName("Muted")
        ll.addWidget(lbl_pin)

        pinrow = QHBoxLayout()
        self.pin_value = QLabel(self.pin)
        self.pin_value.setObjectName("PinValue")
        pinrow.addWidget(self.pin_value, 1)
        copy_pin = QPushButton("⧉")
        copy_pin.setObjectName("CopyButton")
        copy_pin.setToolTip("Copiar PIN")
        copy_pin.clicked.connect(lambda: QApplication.clipboard().setText(self.pin))
        pinrow.addWidget(copy_pin)
        ll.addLayout(pinrow)

        self.incoming_label = QLabel("Nenhuma sessão recebida")
        self.incoming_label.setObjectName("Muted")
        ll.addWidget(self.incoming_label)

        cards.addWidget(local_card, 1)

        # Acessar
        remote_card = QFrame()
        remote_card.setObjectName("RemoteCard")
        rl = QVBoxLayout(remote_card)
        rl.setContentsMargins(22,18,22,18)
        rl.setSpacing(10)

        rt = QLabel("Acessar outro computador")
        rt.setObjectName("CardTitle")
        rt.setStyleSheet("color:#0B67AB;")
        rl.addWidget(rt)

        labels = QHBoxLayout()
        lid = QLabel("ID")
        lid.setObjectName("Muted")
        lpin = QLabel("PIN")
        lpin.setObjectName("Muted")
        labels.addWidget(lid, 3)
        labels.addWidget(lpin, 1)
        rl.addLayout(labels)

        fields = QHBoxLayout()
        self.remote_id = QLineEdit()
        self.remote_id.setPlaceholderText("Insira o ID do computador")
        self.remote_id.setMaxLength(12)
        fields.addWidget(self.remote_id, 3)

        self.remote_pin = QLineEdit()
        self.remote_pin.setPlaceholderText("PIN")
        self.remote_pin.setMaxLength(4)
        self.remote_pin.setEchoMode(QLineEdit.Password)
        self.remote_pin.returnPressed.connect(self.connect_remote)
        fields.addWidget(self.remote_pin, 1)
        rl.addLayout(fields)

        self.connect_btn = QPushButton("Conectar")
        self.connect_btn.setObjectName("Primary")
        self.connect_btn.clicked.connect(self.connect_remote)
        rl.addWidget(self.connect_btn)

        info = QLabel(
            "O ConectaPC tenta primeiro a rede local. Se o ID não estiver na LAN, "
            "usa automaticamente o servidor relay pela internet. O PIN nunca é salvo."
        )
        info.setWordWrap(True)
        info.setObjectName("Muted")
        rl.addWidget(info)

        cards.addWidget(remote_card, 1)
        body_layout.addWidget(cards_container)

        # Recentes
        recent_card = QFrame()
        recent_card.setObjectName("Card")
        rcl = QVBoxLayout(recent_card)
        rcl.setContentsMargins(20,16,20,16)
        rcl.setSpacing(10)

        recent_header = QHBoxLayout()
        recent_title = QLabel("Últimos acessos")
        recent_title.setObjectName("SectionTitle")
        recent_header.addWidget(recent_title)
        recent_header.addStretch(1)

        self.clear_recents_btn = QPushButton("Limpar histórico")
        self.clear_recents_btn.clicked.connect(self.clear_recents)
        recent_header.addWidget(self.clear_recents_btn)
        rcl.addLayout(recent_header)

        self.recents_container = QWidget()
        self.recents_layout = QVBoxLayout(self.recents_container)
        self.recents_layout.setContentsMargins(0,0,0,0)
        self.recents_layout.setSpacing(7)
        rcl.addWidget(self.recents_container)

        body_layout.addWidget(recent_card, 1)
        self.refresh_recents_ui()

        # Arquivos / ajuda
        tip = QFrame()
        tip.setStyleSheet(
            "QFrame{background:#F7FBFF;border:1px dashed #B7D5EE;border-radius:12px;}"
        )
        tip_l = QHBoxLayout(tip)
        tip_l.setContentsMargins(16,12,16,12)
        tip_title = QLabel("Dica")
        tip_title.setStyleSheet("font-weight:700;color:#0B67AB;")
        tip_l.addWidget(tip_title)
        tip_text = QLabel(
            "Ao conectar, o painel inicial sai da tela e o computador remoto ocupa toda a área de trabalho do ConectaPC."
        )
        tip_text.setObjectName("Muted")
        tip_text.setWordWrap(True)
        tip_l.addWidget(tip_text, 1)
        body_layout.addWidget(tip)

        outer.addWidget(body, 1)

        footer = QFrame()
        footer.setObjectName("Footer")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(26,10,26,10)
        left = QLabel("Seguro  •  Rápido  •  Confiável")
        left.setObjectName("Muted")
        fl.addWidget(left)
        fl.addStretch(1)
        ver = QLabel(f"{APP_NAME} {APP_VERSION}")
        ver.setObjectName("Muted")
        fl.addWidget(ver)
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

        title = QLabel("Sessão remota")
        title.setObjectName("SectionTitle")
        top.addWidget(title)
        top.addStretch(1)

        new_session = QPushButton("Nova conexão")
        new_session.clicked.connect(self.show_dashboard)
        top.addWidget(new_session)

        self.fullscreen_btn = QPushButton("Tela cheia  F11")
        self.fullscreen_btn.clicked.connect(self.toggle_fullscreen)
        top.addWidget(self.fullscreen_btn)

        layout.addWidget(self.remote_topbar)

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        self.tabs.currentChanged.connect(self._current_session_changed)
        layout.addWidget(self.tabs, 1)

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
            self.recents_layout.addWidget(empty)
            return

        for item in self.recents[:6]:
            row = QFrame()
            row.setStyleSheet(
                "QFrame{background:#FAFCFE;border:1px solid #E0E8F0;border-radius:10px;}"
            )
            rl = QHBoxLayout(row)
            rl.setContentsMargins(12,9,12,9)

            name_box = QVBoxLayout()
            name = QLabel(item.get("name") or "Computador")
            name.setStyleSheet("font-weight:700;")
            name_box.addWidget(name)

            details = QLabel(
                f"ID {pretty_id(item['id'])}  •  {item.get('last_access','')}"
            )
            details.setObjectName("Muted")
            name_box.addWidget(details)
            rl.addLayout(name_box, 1)

            use_btn = QPushButton("Conectar novamente")
            use_btn.clicked.connect(
                lambda checked=False, sid=item["id"]: self.use_recent(sid)
            )
            rl.addWidget(use_btn)

            self.recents_layout.addWidget(row)

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

    def show_remote(self):
        self.stack.setCurrentWidget(self.remote_page)
        current = self.tabs.currentWidget()
        if isinstance(current, RemoteSession):
            current.screen.setFocus()

    def _set_immersive(self, enabled):
        self.remote_topbar.setVisible(not enabled)
        self.tabs.tabBar().setVisible(not enabled)
        current = self.tabs.currentWidget()
        if isinstance(current, RemoteSession):
            current.set_immersive(enabled)

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
        if self.isFullScreen():
            current = self.tabs.currentWidget()
            if isinstance(current, RemoteSession):
                current.set_immersive(True)

    def _set_status(self, text, online):
        self.status_badge.setText("● " + text)
        self.status_badge.setObjectName("StatusOnline" if online else "StatusOffline")
        self.status_badge.style().unpolish(self.status_badge)
        self.status_badge.style().polish(self.status_badge)

    def _set_internet_status(self, text, online):
        self.internet_badge.setText("● " + text)
        self.internet_badge.setObjectName(
            "StatusOnline" if online else "StatusOffline"
        )
        self.internet_badge.style().unpolish(self.internet_badge)
        self.internet_badge.style().polish(self.internet_badge)

    def _set_incoming_count(self, n):
        if n == 0:
            self.incoming_label.setText("Nenhuma sessão recebida")
        elif n == 1:
            self.incoming_label.setText("1 sessão recebida")
        else:
            self.incoming_label.setText(f"{n} sessões recebidas")

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

        if len(sid) != 9 or len(pin) != 4:
            QMessageBox.warning(
                self,
                APP_NAME,
                "Informe um ID de 9 dígitos e um PIN de 4 dígitos.",
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
            QApplication.instance().postEvent(
                self,
                _OpenSessionEvent(peer, sid, pin),
            )
            return

        # 2) Fora da LAN: abre um túnel pelo relay.
        try:
            tunnel, meta = self.relay.open_controller_tunnel(sid)
            relay_peer = {
                "name": meta.get("name") or f"PC {sid}",
                "ip": "Internet via relay",
                "port": 0,
                "mode": "relay",
                "_preconnected_socket": tunnel,
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
        if isinstance(event, _OpenSessionEvent):
            self.connect_btn.setEnabled(True)
            self.connect_btn.setText("Conectar")

            if not event.peer:
                detail = event.error or "Servidor de internet indisponível."
                QMessageBox.critical(
                    self,
                    APP_NAME,
                    "Não foi possível localizar esse ID.\n\n"
                    "O ConectaPC tentou primeiro a rede local e depois o relay pela internet.\n\n"
                    f"Detalhe: {detail}",
                )
                return

            session = RemoteSession(event.peer, event.sid, event.pin)
            idx = self.tabs.addTab(session, event.peer["name"])
            self.tabs.setCurrentIndex(idx)

            # Sai do dashboard imediatamente e entrega a janela para a sessão.
            self.show_remote()

            session.titleChanged.connect(
                lambda title, s=session, sid=event.sid:
                    self._session_connected(s, sid, title)
            )
            session.closed.connect(self._close_session_widget)

            self.remote_id.clear()
            self.remote_pin.clear()
            return

        super().customEvent(event)

    def _session_connected(self, session, sid, title):
        idx = self.tabs.indexOf(session)
        if idx >= 0:
            self.tabs.setTabText(idx, title)
        self.remember_access(sid, title)

    def _close_session_widget(self, session):
        idx = self.tabs.indexOf(session)
        if idx >= 0:
            self.tabs.removeTab(idx)
        session.deleteLater()

        if self.tabs.count() == 0:
            self.show_dashboard()

    def _close_tab(self, idx):
        widget = self.tabs.widget(idx)
        if isinstance(widget, RemoteSession):
            widget.disconnect()
        else:
            self.tabs.removeTab(idx)

    def closeEvent(self, event):
        for idx in range(self.tabs.count()-1, -1, -1):
            widget = self.tabs.widget(idx)
            if isinstance(widget, RemoteSession):
                widget.disconnect()
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

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
