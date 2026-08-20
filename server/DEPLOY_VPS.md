# Publicar o ConectaPC Relay em uma VPS Ubuntu

## Arquitetura

O ConectaPC 2.0 tenta:

1. localizar o ID diretamente na LAN;
2. se não encontrar, pedir ao relay o computador daquele ID;
3. o PC remoto abre uma conexão de saída para o relay;
4. o relay liga os dois fluxos;
5. ID/PIN e consentimento continuam sendo validados no aplicativo remoto.

Não há banco de dados. A lista de IDs online fica somente na memória do servidor.

## Requisitos

- Ubuntu 22.04/24.04 ou equivalente
- Python 3.11+
- IP público
- porta TCP 443 liberada
- recomendado: domínio como `relay.seudominio.com.br`
- certificado TLS válido

## Instalação básica

    sudo useradd --system --home /opt/conectapc-relay --shell /usr/sbin/nologin conectapc
    sudo mkdir -p /opt/conectapc-relay /etc/conectapc
    sudo cp relay_server.py /opt/conectapc-relay/
    sudo chown -R conectapc:conectapc /opt/conectapc-relay

Coloque o certificado e a chave em:

    /etc/conectapc/relay.crt
    /etc/conectapc/relay.key

Permissões:

    sudo chown root:conectapc /etc/conectapc/relay.crt /etc/conectapc/relay.key
    sudo chmod 640 /etc/conectapc/relay.crt /etc/conectapc/relay.key

Copie o serviço:

    sudo cp systemd/conectapc-relay.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable --now conectapc-relay

Ver logs:

    sudo journalctl -u conectapc-relay -f

## Firewall

Com UFW:

    sudo ufw allow 443/tcp

## Certificado público

A opção mais prática para uso real é um domínio apontando para a VPS e um
certificado emitido por uma autoridade confiável. Depois copie o certificado
e a chave para `/etc/conectapc/`.

O aplicativo Windows usa a validação TLS normal do sistema.

## Certificado autoassinado para laboratório

Existe `GERAR_CERTIFICADO_TESTE.sh`.

Exemplo:

    chmod +x GERAR_CERTIFICADO_TESTE.sh
    ./GERAR_CERTIFICADO_TESTE.sh 203.0.113.10

ou:

    ./GERAR_CERTIFICADO_TESTE.sh relay.seudominio.com.br

Depois:

1. instale `relay.crt` e `relay.key` no servidor;
2. copie somente `relay.crt` para a raiz do projeto Windows;
3. em `relay_config.json`, defina:

       "tls": true,
       "ca_file": "relay.crt",
       "server_name": "203.0.113.10"

4. gere novamente o ConectaPC.exe.

Nunca distribua `relay.key` para clientes.

## Segurança desta versão

- conexão cliente ↔ relay protegida por TLS quando configurada corretamente;
- o servidor não armazena IDs permanentemente;
- PIN não é enviado no registro do ID;
- o PC remoto continua exibindo a solicitação de consentimento;
- sessões possuem tokens aleatórios temporários;
- não existe acesso oculto ou não assistido.

Importante: TLS nesta versão termina no relay. Portanto, esta versão ainda não
é criptografia ponta a ponta entre os dois PCs. Antes de usar como produto
comercial em larga escala, o próximo passo deve adicionar uma camada E2E
autenticada entre os clientes.

## Capacidade

O relay retransmite a tela inteira, então largura de banda importa.

Exemplo aproximado: 10 sessões usando 2 Mbit/s cada consomem cerca de
20 Mbit/s de entrada e 20 Mbit/s de saída no VPS.

Comece pequeno e meça o uso real.
