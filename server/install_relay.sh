#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Execute como root: sudo ./install_relay.sh" >&2
  exit 1
fi

base_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if ! id -u conectapc >/dev/null 2>&1; then
  useradd --system --home /opt/conectapc-relay --shell /usr/sbin/nologin conectapc
fi
install -d -o conectapc -g conectapc -m 0750 /opt/conectapc-relay
install -d -o root -g conectapc -m 0750 /etc/conectapc
install -m 0755 "${base_dir}/relay_server.py" /opt/conectapc-relay/
install -m 0644 "${base_dir}/security_store.py" /opt/conectapc-relay/
install -m 0755 "${base_dir}/manage_security.py" /opt/conectapc-relay/
install -m 0644 "${base_dir}/systemd/conectapc-relay.service" /etc/systemd/system/
chown -R conectapc:conectapc /opt/conectapc-relay

if [[ ! -s /etc/conectapc/relay.crt || ! -s /etc/conectapc/relay.key ]]; then
  echo "Instale relay.crt e relay.key em /etc/conectapc antes de iniciar o serviço." >&2
  exit 2
fi
chown root:conectapc /etc/conectapc/relay.crt /etc/conectapc/relay.key
chmod 0640 /etc/conectapc/relay.crt /etc/conectapc/relay.key

if [[ ! -s /etc/conectapc/relay.env ]]; then
  umask 027
  printf 'CONECTAPC_AUDIT_KEY=%s\n' "$(openssl rand -hex 32)" > /etc/conectapc/relay.env
fi
chown root:conectapc /etc/conectapc/relay.env
chmod 0640 /etc/conectapc/relay.env

systemctl daemon-reload
systemctl enable --now conectapc-relay
systemctl --no-pager --full status conectapc-relay
