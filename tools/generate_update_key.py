#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def main():
    parser = argparse.ArgumentParser(description="Gera a chave offline de atualização ConectaPC")
    parser.add_argument("--private-key", required=True)
    args = parser.parse_args()
    path = Path(args.private_key)
    if path.exists():
        raise SystemExit("O arquivo já existe; nenhuma chave foi substituída")
    private = Ed25519PrivateKey.generate()
    path.write_bytes(private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    print("Guarde a chave privada offline e configure somente esta chave pública no aplicativo:")
    print(base64.urlsafe_b64encode(public).decode("ascii").rstrip("="))


if __name__ == "__main__":
    main()
