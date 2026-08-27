# Publicar o ConectaPC Relay em Ubuntu

## Requisitos

- Ubuntu 22.04/24.04 ou equivalente;
- Python 3.11+;
- domínio público apontado para a VPS;
- porta TCP 443;
- certificado TLS público válido.

## Instalação

    sudo useradd --system --home /opt/conectapc-relay --shell /usr/sbin/nologin conectapc
    sudo mkdir -p /opt/conectapc-relay /etc/conectapc
    sudo cp relay_server.py security_store.py manage_security.py /opt/conectapc-relay/
    sudo chown -R conectapc:conectapc /opt/conectapc-relay

Instale o certificado e a chave em `/etc/conectapc/relay.crt` e `/etc/conectapc/relay.key`:

    sudo chown root:conectapc /etc/conectapc/relay.crt /etc/conectapc/relay.key
    sudo chmod 640 /etc/conectapc/relay.crt /etc/conectapc/relay.key

Instale o serviço:

    sudo cp systemd/conectapc-relay.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable --now conectapc-relay
    sudo ufw allow 443/tcp

O systemd cria `/var/lib/conectapc` com acesso restrito ao serviço. Não use `--allow-plain` em produção.

Configure também `CONECTAPC_AUDIT_KEY` por `EnvironmentFile` protegido pelo root para que a chave usada na pseudonimização das origens não fique no próprio banco.

    sudo sh -c 'umask 027; printf "CONECTAPC_AUDIT_KEY=%s\n" "$(openssl rand -hex 32)" > /etc/conectapc/relay.env'
    sudo chown root:conectapc /etc/conectapc/relay.env
    sudo chmod 640 /etc/conectapc/relay.env

## Primeiro técnico com MFA

    sudo -u conectapc python3 /opt/conectapc-relay/manage_security.py \
      --db /var/lib/conectapc/relay.db \
      add-technician suporte --name "Nome do técnico"

Cadastre o segredo TOTP exibido no autenticador e guarde os códigos de recuperação segundo a política da empresa.

## Cadastrar um cliente

    sudo -u conectapc python3 /opt/conectapc-relay/manage_security.py \
      --db /var/lib/conectapc/relay.db \
      create-enrollment --label "Cliente - Computador" --hours 24

O código é de uso único. O cliente deve colá-lo em **Cadastrar este computador**.

## Revogação

    sudo -u conectapc python3 /opt/conectapc-relay/manage_security.py \
      --db /var/lib/conectapc/relay.db disable-technician usuario

    sudo -u conectapc python3 /opt/conectapc-relay/manage_security.py \
      --db /var/lib/conectapc/relay.db disable-device 123456789

Revogar no banco bloqueia novos acessos. Para derrubar imediatamente conexões TCP já estabelecidas, reinicie o serviço enquanto não houver um canal administrativo dedicado:

    sudo systemctl restart conectapc-relay

## Operação

    sudo systemctl status conectapc-relay
    sudo journalctl -u conectapc-relay -f

O relay registra metadados de auditoria em SQLite e retém 90 dias por padrão. Faça backup criptografado de `/var/lib/conectapc/relay.db`, monitore CPU/memória/banda, expiração TLS, falhas de login e volume de sessões.

## Teste integrado com TLS

Depois que o DNS e o certificado estiverem válidos e o serviço estiver ativo,
execute na própria VPS, substituindo o domínio:

    sudo -u conectapc python3 /opt/conectapc-relay/TESTAR_RELAY_LOCAL.py \
      relay.suaempresa.com.br 443 /var/lib/conectapc/relay.db \
      --tls --server-name relay.suaempresa.com.br

O resultado esperado começa com `RELAY_OK` e confirma explicitamente
`Transporte: TLS verificado`. O teste cria dispositivos e um técnico sintéticos
no banco de auditoria; não use nomes ou credenciais reais.

Para um certificado de laboratório assinado por uma CA privada, acrescente
`--ca-file /caminho/ca.crt`. Não existe opção para desabilitar a validação do
certificado no teste TLS.

O relay permanece de processo único e memória local. Antes de alta disponibilidade/horizontalização, será necessário um coordenador compartilhado para presença e sessões.

## Laboratório local

    python relay_server.py --host 127.0.0.1 --port 45443 --allow-plain --db relay-test.db
    python TESTAR_RELAY_LOCAL.py 127.0.0.1 45443 relay-test.db

O teste valida cadastro de dispositivos, MFA, autorização, identidades declaradas e túnel bidirecional. A criptografia E2E é validada pelos testes unitários do projeto.
