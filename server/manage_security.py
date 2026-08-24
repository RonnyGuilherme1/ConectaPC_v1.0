#!/usr/bin/env python3
from __future__ import annotations

import argparse
import getpass
import urllib.parse

from security_store import SecurityStore


def main():
    parser = argparse.ArgumentParser(description="Administração de segurança do ConectaPC Relay")
    parser.add_argument("--db", default="/var/lib/conectapc/relay.db")
    sub = parser.add_subparsers(dest="command", required=True)

    tech = sub.add_parser("add-technician", help="Cria ou redefine um técnico e seu MFA")
    tech.add_argument("username")
    tech.add_argument("--name", default="")

    enroll = sub.add_parser("create-enrollment", help="Cria um código de uso único para instalar um dispositivo")
    enroll.add_argument("--label", required=True)
    enroll.add_argument("--hours", type=int, default=24)

    disable_tech = sub.add_parser("disable-technician")
    disable_tech.add_argument("username")
    disable_device = sub.add_parser("disable-device")
    disable_device.add_argument("device_id")

    args = parser.parse_args()
    store = SecurityStore(args.db)
    try:
        if args.command == "add-technician":
            password = getpass.getpass("Senha forte (mínimo 12 caracteres): ")
            confirmation = getpass.getpass("Repita a senha: ")
            if password != confirmation:
                raise SystemExit("As senhas não conferem")
            secret = store.add_technician(args.username, args.name or args.username, password)
            label = urllib.parse.quote(args.name or args.username)
            issuer = urllib.parse.quote("ConectaPC")
            print("Técnico criado. Cadastre o MFA no aplicativo autenticador:")
            print(f"Segredo: {secret}")
            print(f"otpauth://totp/{issuer}:{label}?secret={secret}&issuer={issuer}&digits=6&period=30")
        elif args.command == "create-enrollment":
            print(store.create_enrollment(args.label, max(1, args.hours)))
        elif args.command == "disable-technician":
            store.db.execute("UPDATE technicians SET active=0 WHERE username=?", (args.username.lower(),))
            store.db.execute("DELETE FROM access_tokens WHERE username=?", (args.username.lower(),))
            store.db.commit()
            print("Técnico e sessões desabilitados.")
        elif args.command == "disable-device":
            store.db.execute("UPDATE devices SET active=0 WHERE device_id=?", (args.device_id,))
            store.db.execute("DELETE FROM access_tokens WHERE controller_id=?", (args.device_id,))
            store.db.commit()
            print("Dispositivo e sessões desabilitados.")
    finally:
        store.close()


if __name__ == "__main__":
    main()
