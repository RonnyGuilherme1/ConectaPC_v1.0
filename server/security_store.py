from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import struct
import time
from pathlib import Path


PASSWORD_N = 2 ** 14
ACCESS_TOKEN_TTL = 15 * 60


def _token_hash(token: str) -> str:
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=PASSWORD_N, r=8, p=1, dklen=32)
    return "scrypt$%d$%s$%s" % (
        PASSWORD_N,
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(derived).decode("ascii"),
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, n_value, salt_b64, hash_b64 = encoded.split("$", 3)
        if scheme != "scrypt":
            return False
        salt = base64.urlsafe_b64decode(salt_b64)
        expected = base64.urlsafe_b64decode(hash_b64)
        actual = hashlib.scrypt(
            password.encode("utf-8"), salt=salt, n=int(n_value), r=8, p=1, dklen=len(expected)
        )
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def generate_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def totp_code(secret: str, when: int | None = None) -> str:
    when = int(time.time()) if when is None else int(when)
    padded = secret.upper() + "=" * (-len(secret) % 8)
    key = base64.b32decode(padded)
    counter = struct.pack("!Q", when // 30)
    digest = hmac.new(key, counter, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = (struct.unpack("!I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % 1_000_000
    return f"{value:06d}"


def verify_totp(secret: str, code: str, now: int | None = None) -> bool:
    now = int(time.time()) if now is None else int(now)
    code = str(code or "").strip()
    if len(code) != 6 or not code.isdigit():
        return False
    return any(hmac.compare_digest(totp_code(secret, now + offset), code) for offset in (-30, 0, 30))


class SecurityStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self._create_schema()
        self.audit_key = os.environ.get("CONECTAPC_AUDIT_KEY") or self._get_or_create_setting(
            "audit_key", secrets.token_hex(32)
        )

    def _create_schema(self):
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS technicians (
                username TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                totp_secret TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS devices (
                device_id TEXT PRIMARY KEY,
                label TEXT NOT NULL,
                public_key TEXT NOT NULL,
                token_hash TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                created_at INTEGER NOT NULL,
                last_seen_at INTEGER
            );
            CREATE TABLE IF NOT EXISTS enrollment_tokens (
                token_hash TEXT PRIMARY KEY,
                label TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                used_at INTEGER
            );
            CREATE TABLE IF NOT EXISTS access_tokens (
                token_hash TEXT PRIMARY KEY,
                username TEXT NOT NULL REFERENCES technicians(username),
                controller_id TEXT NOT NULL,
                public_key TEXT NOT NULL,
                expires_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at INTEGER NOT NULL,
                event TEXT NOT NULL,
                actor TEXT,
                target TEXT,
                source_hash TEXT,
                detail_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_events(created_at);
            """
        )
        self.db.commit()

    def _get_or_create_setting(self, key: str, default: str) -> str:
        row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        if row:
            return row["value"]
        self.db.execute("INSERT INTO settings(key,value) VALUES(?,?)", (key, default))
        self.db.commit()
        return default

    def close(self):
        self.db.close()

    def add_technician(self, username: str, display_name: str, password: str) -> str:
        username = username.strip().lower()
        if not username or len(username) > 80 or len(password) < 12:
            raise ValueError("Usuário inválido ou senha com menos de 12 caracteres")
        secret = generate_totp_secret()
        self.db.execute("DELETE FROM access_tokens WHERE username=?", (username,))
        self.db.execute(
            """INSERT INTO technicians(username,display_name,password_hash,totp_secret,active,created_at)
               VALUES(?,?,?,?,1,?)
               ON CONFLICT(username) DO UPDATE SET
                 display_name=excluded.display_name,
                 password_hash=excluded.password_hash,
                 totp_secret=excluded.totp_secret,
                 active=1""",
            (username, display_name.strip()[:120] or username, hash_password(password), secret, int(time.time())),
        )
        self.db.commit()
        return secret

    def create_enrollment(self, label: str, ttl_hours: int = 24) -> str:
        token = secrets.token_urlsafe(32)
        self.db.execute(
            "INSERT INTO enrollment_tokens(token_hash,label,expires_at) VALUES(?,?,?)",
            (_token_hash(token), label.strip()[:120] or "Computador", int(time.time()) + ttl_hours * 3600),
        )
        self.db.commit()
        return token

    def enroll_device(self, enrollment_token: str, device_id: str, public_key: str, name: str) -> str | None:
        now = int(time.time())
        row = self.db.execute(
            "SELECT * FROM enrollment_tokens WHERE token_hash=? AND used_at IS NULL AND expires_at>=?",
            (_token_hash(enrollment_token), now),
        ).fetchone()
        if not row:
            return None
        existing = self.db.execute("SELECT 1 FROM devices WHERE device_id=?", (device_id,)).fetchone()
        if existing:
            return None
        token = secrets.token_urlsafe(48)
        self.db.execute(
            "INSERT INTO devices(device_id,label,public_key,token_hash,created_at,last_seen_at) VALUES(?,?,?,?,?,?)",
            (device_id, row["label"] or name[:120], public_key, _token_hash(token), now, now),
        )
        self.db.execute("UPDATE enrollment_tokens SET used_at=? WHERE token_hash=?", (now, row["token_hash"]))
        self.db.commit()
        return token

    def authenticate_device(self, device_id: str, public_key: str, token: str) -> bool:
        row = self.db.execute(
            "SELECT token_hash,public_key,active FROM devices WHERE device_id=?", (device_id,)
        ).fetchone()
        ok = bool(
            row and row["active"] and hmac.compare_digest(row["public_key"], public_key)
            and hmac.compare_digest(row["token_hash"], _token_hash(token))
        )
        if ok:
            self.db.execute("UPDATE devices SET last_seen_at=? WHERE device_id=?", (int(time.time()), device_id))
            self.db.commit()
        return ok

    def authenticate_technician(
        self, username: str, password: str, otp: str, controller_id: str, public_key: str
    ) -> tuple[str, str] | None:
        username = username.strip().lower()
        row = self.db.execute("SELECT * FROM technicians WHERE username=?", (username,)).fetchone()
        if not row or not row["active"]:
            return None
        if not verify_password(password, row["password_hash"]) or not verify_totp(row["totp_secret"], otp):
            return None
        token = secrets.token_urlsafe(48)
        expires = int(time.time()) + ACCESS_TOKEN_TTL
        self.db.execute("DELETE FROM access_tokens WHERE expires_at<?", (int(time.time()),))
        self.db.execute(
            "INSERT INTO access_tokens(token_hash,username,controller_id,public_key,expires_at) VALUES(?,?,?,?,?)",
            (_token_hash(token), username, controller_id, public_key, expires),
        )
        self.db.commit()
        return token, row["display_name"]

    def validate_access(self, token: str, controller_id: str, public_key: str):
        row = self.db.execute(
            """SELECT a.username,t.display_name,a.controller_id,a.public_key,a.expires_at
               FROM access_tokens a JOIN technicians t ON t.username=a.username
               WHERE a.token_hash=? AND t.active=1""",
            (_token_hash(token),),
        ).fetchone()
        if not row or row["expires_at"] < int(time.time()):
            return None
        if not hmac.compare_digest(row["controller_id"], controller_id):
            return None
        if not hmac.compare_digest(row["public_key"], public_key):
            return None
        return {"username": row["username"], "display_name": row["display_name"]}

    def audit(self, event: str, actor: str = "", target: str = "", source: str = "", detail=None):
        source_hash = ""
        if source:
            source_hash = hmac.new(
                bytes.fromhex(self.audit_key), source.encode("utf-8", "replace"), hashlib.sha256
            ).hexdigest()[:24]
        safe_detail = detail if isinstance(detail, dict) else {}
        self.db.execute(
            "INSERT INTO audit_events(created_at,event,actor,target,source_hash,detail_json) VALUES(?,?,?,?,?,?)",
            (int(time.time()), event[:80], actor[:120], target[:120], source_hash, json.dumps(safe_detail, separators=(",", ":"))),
        )
        self.db.commit()

    def purge_audit(self, retention_days: int):
        cutoff = int(time.time()) - max(1, retention_days) * 86400
        self.db.execute("DELETE FROM audit_events WHERE created_at<?", (cutoff,))
        self.db.execute("DELETE FROM access_tokens WHERE expires_at<?", (int(time.time()),))
        self.db.commit()
