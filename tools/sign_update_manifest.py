#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from updates import canonical_manifest


def main():
    parser = argparse.ArgumentParser(description="Assina um manifesto de atualização ConectaPC")
    parser.add_argument("installer")
    parser.add_argument("--version", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--private-key", required=True, help="Chave Ed25519 PEM mantida fora do servidor")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    installer = Path(args.installer)
    private_key = serialization.load_pem_private_key(
        Path(args.private_key).read_bytes(), password=None
    )
    digest = hashlib.sha256(installer.read_bytes()).hexdigest()
    manifest = {
        "version": args.version,
        "installer_url": args.url,
        "sha256": digest,
        "size": installer.stat().st_size,
    }
    signature = private_key.sign(canonical_manifest(manifest))
    manifest["signature"] = base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
    Path(args.output).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Manifesto assinado: {args.output}")


if __name__ == "__main__":
    main()
