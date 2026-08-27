# Entrega ao coordenador — ConectaPC Relay 2.1.0

Esta entrega instala somente o relay público na VPS. Ela não contém domínio,
certificado TLS, senhas, códigos de MFA, tokens de clientes ou chaves privadas.

## Arquivos a enviar

- `dist_relay/conectapc-relay-2.1.0.zip`;
- `dist_relay/SHA256.txt`;
- este documento.

Confira o hash antes de enviar e novamente na VPS. No Windows:

    Get-FileHash .\dist_relay\conectapc-relay-2.1.0.zip -Algorithm SHA256

No Ubuntu:

    sha256sum conectapc-relay-2.1.0.zip

## Dados que o coordenador precisa providenciar

- VPS Ubuntu 22.04/24.04 com IP público;
- domínio apontado por DNS para o IP da VPS;
- porta TCP 443 liberada;
- certificado TLS público válido e respectiva chave privada.

## Instalação resumida

    unzip conectapc-relay-2.1.0.zip
    cd conectapc-relay-2.1.0
    sudo mkdir -p /etc/conectapc
    sudo cp /origem/relay.crt /etc/conectapc/relay.crt
    sudo cp /origem/relay.key /etc/conectapc/relay.key
    sudo ./install_relay.sh

Os caminhos e permissões completos estão em `DEPLOY_VPS.md`. Não execute o
relay com `--allow-plain` em uma VPS pública.

## Validação na VPS

Substitua `relay.suaempresa.com.br` pelo domínio real:

    sudo -u conectapc python3 /opt/conectapc-relay/TESTAR_RELAY_LOCAL.py \
      relay.suaempresa.com.br 443 /var/lib/conectapc/relay.db \
      --tls --server-name relay.suaempresa.com.br

O resultado esperado é `RELAY_OK` com `Transporte: TLS verificado`.

## Retorno necessário para gerar o cliente Windows

Depois que a VPS estiver acessível, o coordenador deve informar o domínio real.
Na máquina Windows de build, execute:

    .\CONFIGURAR_CLIENTE_PRODUCAO.ps1 -RelayHost relay.suaempresa.com.br
    .\VERIFICAR_PILOTO.ps1 -Profile VpsTest
    .\GERAR_INSTALADOR.ps1

O perfil `VpsTest` permite um Setup de homologação sem Authenticode, mas testa
DNS, certificado TLS, dependências, suíte automatizada e integridade do pacote.
O perfil `Production` continua exigindo assinatura Authenticode e chave pública
de atualização antes de liberar uma distribuição oficial.
