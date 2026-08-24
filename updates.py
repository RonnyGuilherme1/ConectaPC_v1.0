from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


MAX_MANIFEST_SIZE = 256 * 1024
MAX_INSTALLER_SIZE = 250 * 1024 * 1024
# Esta chave precisa ser preenchida antes do release e ficará protegida pela
# assinatura Authenticode do executável. Chaves vindas da configuração externa
# são aceitas somente no modo de desenvolvimento inseguro.
PINNED_UPDATE_PUBLIC_KEY = ""


class UpdateError(RuntimeError):
    pass


def _unb64(value):
    value = str(value or "")
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def canonical_manifest(manifest):
    signed = {key: value for key, value in manifest.items() if key != "signature"}
    return json.dumps(signed, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def verify_manifest(manifest, public_key):
    if not isinstance(manifest, dict):
        raise UpdateError("Manifesto de atualização inválido")
    required = {"version", "installer_url", "sha256", "size", "signature"}
    if not required.issubset(manifest):
        raise UpdateError("Manifesto de atualização incompleto")
    digest = str(manifest["sha256"]).lower()
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise UpdateError("SHA-256 da atualização inválido")
    size = int(manifest["size"])
    if size <= 0 or size > MAX_INSTALLER_SIZE:
        raise UpdateError("Tamanho da atualização não permitido")
    try:
        Ed25519PublicKey.from_public_bytes(_unb64(public_key)).verify(
            _unb64(manifest["signature"]), canonical_manifest(manifest)
        )
    except Exception as exc:
        raise UpdateError("Assinatura da atualização é inválida") from exc
    return manifest


def version_tuple(value):
    try:
        parts = tuple(int(item) for item in str(value).split("."))
    except ValueError as exc:
        raise UpdateError("Versão da atualização inválida") from exc
    if not parts or len(parts) > 4 or any(item < 0 or item > 65535 for item in parts):
        raise UpdateError("Versão da atualização inválida")
    return parts + (0,) * (4 - len(parts))


def _require_https(url, allow_insecure_dev=False):
    parsed = urllib.parse.urlparse(str(url))
    if parsed.scheme != "https" and not allow_insecure_dev:
        raise UpdateError("Atualizações exigem HTTPS")
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        raise UpdateError("URL de atualização inválida")


def check_and_download(update_config, current_version, data_dir, progress=None):
    manifest_url = str(update_config.get("manifest_url") or "").strip()
    allow_insecure = bool(update_config.get("allow_insecure_dev", False))
    public_key = PINNED_UPDATE_PUBLIC_KEY
    if not public_key and allow_insecure:
        public_key = str(update_config.get("public_key") or "").strip()
    if not manifest_url or not public_key:
        raise UpdateError("Servidor de atualização ou chave pública não configurado")
    _require_https(manifest_url, allow_insecure)
    request = urllib.request.Request(manifest_url, headers={"User-Agent": "ConectaPC-Updater/1"})
    with urllib.request.urlopen(request, timeout=15) as response:
        raw = response.read(MAX_MANIFEST_SIZE + 1)
    if len(raw) > MAX_MANIFEST_SIZE:
        raise UpdateError("Manifesto de atualização muito grande")
    manifest = verify_manifest(json.loads(raw.decode("utf-8")), public_key)
    if version_tuple(manifest["version"]) <= version_tuple(current_version):
        return None, manifest

    installer_url = str(manifest["installer_url"])
    _require_https(installer_url, allow_insecure)
    update_dir = Path(data_dir) / "updates"
    update_dir.mkdir(parents=True, exist_ok=True)
    final_path = update_dir / f"ConectaPC_Setup_v{manifest['version']}.exe"
    temp_path = final_path.with_suffix(".part")
    digest = hashlib.sha256()
    received = 0
    try:
        request = urllib.request.Request(installer_url, headers={"User-Agent": "ConectaPC-Updater/1"})
        with urllib.request.urlopen(request, timeout=30) as response, temp_path.open("wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                received += len(chunk)
                if received > int(manifest["size"]) or received > MAX_INSTALLER_SIZE:
                    raise UpdateError("Download excedeu o tamanho assinado")
                output.write(chunk)
                digest.update(chunk)
                if progress:
                    progress(int(received * 100 / int(manifest["size"])))
        if received != int(manifest["size"]) or digest.hexdigest() != manifest["sha256"]:
            raise UpdateError("Atualização incompleta ou com hash divergente")
        os.replace(temp_path, final_path)
        return final_path, manifest
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def apply_update(installer_path, data_dir):
    installer_path = Path(installer_path).resolve()
    update_dir = Path(data_dir) / "updates"
    update_dir.mkdir(parents=True, exist_ok=True)
    current = update_dir / "current_setup.exe"
    rollback = update_dir / "rollback_setup.exe"
    if current.exists():
        shutil.copy2(current, rollback)
    subprocess.Popen(
        [str(installer_path), "/SILENT", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"],
        close_fds=True,
    )


def rollback_available(data_dir):
    return (Path(data_dir) / "updates" / "rollback_setup.exe").is_file()


def apply_rollback(data_dir):
    rollback = Path(data_dir) / "updates" / "rollback_setup.exe"
    if not rollback.is_file():
        raise UpdateError("Nenhuma versão anterior está disponível")
    subprocess.Popen(
        [str(rollback), "/SILENT", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"],
        close_fds=True,
    )
