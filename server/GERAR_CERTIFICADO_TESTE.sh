#!/usr/bin/env bash
set -euo pipefail

NAME="${1:-}"
if [ -z "$NAME" ]; then
  echo "Uso: ./GERAR_CERTIFICADO_TESTE.sh relay.seudominio.com.br"
  echo "ou:  ./GERAR_CERTIFICADO_TESTE.sh 203.0.113.10"
  exit 1
fi

if [[ "$NAME" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  SAN="IP:$NAME"
else
  SAN="DNS:$NAME"
fi

openssl req -x509 -newkey rsa:3072 -nodes \
  -keyout relay.key \
  -out relay.crt \
  -days 365 \
  -subj "/CN=$NAME" \
  -addext "subjectAltName=$SAN"

chmod 600 relay.key
chmod 644 relay.crt

echo
echo "Gerados:"
echo "  relay.crt"
echo "  relay.key"
echo
echo "Para teste com certificado autoassinado, copie relay.crt para a pasta"
echo "raiz do projeto Windows e configure ca_file como relay.crt."
