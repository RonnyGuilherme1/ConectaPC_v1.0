# ConectaPC 2.0.0 — LAN + Internet Relay

Esta versão mantém tudo que já existia no ConectaPC 1.2 e adiciona acesso fora
da rede local.

## Como a conexão funciona

Ao digitar ID + PIN:

1. o ConectaPC procura o ID na LAN por aproximadamente 2 segundos;
2. se encontrar, conecta diretamente PC → PC;
3. se não encontrar, tenta o servidor ConectaPC;
4. o servidor localiza o ID online em memória;
5. o PC remoto abre um túnel de saída para o servidor;
6. o servidor retransmite os bytes entre os dois PCs;
7. ID + PIN são conferidos pelo PC remoto;
8. o usuário remoto ainda precisa clicar em Permitir.

Nenhuma porta precisa ser aberta no roteador do cliente.

## Sem banco de dados

O servidor mantém apenas em RAM:

    123456789 -> conexão online
    987654321 -> conexão online

Ao fechar o ConectaPC, o ID sai da lista.
Ao reiniciar o servidor, a lista zera.

## Configurar o servidor no Windows

Edite:

    relay_config.json

Exemplo com certificado público:

    {
      "enabled": true,
      "host": "relay.seudominio.com.br",
      "port": 443,
      "tls": true,
      "server_name": "relay.seudominio.com.br",
      "ca_file": "",
      "allow_insecure_dev": false
    }

Depois execute:

    EXECUTAR_TESTE.bat

Na tela inicial aparecerão dois estados:

- LAN
- Internet

Quando o servidor estiver conectado:

    Internet pronta

## Gerar o instalador

Depois de configurar `relay_config.json`:

    GERAR_INSTALADOR.bat

Resultado:

    dist_installer\ConectaPC_Setup_v2.0.0.exe

O arquivo de configuração é incorporado no executável.

## Override local de configuração

Para testes, o ConectaPC também procura:

    %LOCALAPPDATA%\ConectaPC\relay_config.json

Se esse arquivo existir, ele substitui a configuração empacotada.

Isso permite trocar de relay sem recompilar durante desenvolvimento.

## Servidor

A pasta:

    server\

contém:

    relay_server.py
    DEPLOY_VPS.md
    GERAR_CERTIFICADO_TESTE.sh
    systemd\conectapc-relay.service

O servidor usa somente Python 3.11+ e biblioteca padrão.

## TLS

Para internet real use TLS.

Não habilite:

    "tls": false

em computadores de clientes.

O modo sem TLS existe apenas para laboratório privado e precisa de:

    "allow_insecure_dev": true

no cliente e:

    --allow-plain

no servidor.

## O que o relay vê

O servidor não recebe o PIN durante o registro do ID e não mantém banco de dados.

Porém, nesta versão o TLS termina no relay. Portanto o relay tecnicamente pode
observar o tráfego da sessão enquanto o retransmite.

Para uma versão comercial, a próxima camada de segurança deve ser criptografia
ponta a ponta entre os dois ConectaPC, por cima do relay.

## Funcionalidades mantidas

- interface PySide6/Qt;
- ID + PIN temporários;
- consentimento no PC remoto;
- tela remota;
- mouse/teclado;
- envio/recebimento de arquivos;
- drag and drop;
- múltiplas sessões;
- últimos acessos;
- tela dedicada da sessão;
- F11;
- instalador Inno Setup.

## Sem servidor: é possível?

### LAN
Sim. Já funciona sem servidor.

### Internet com IP público e redirecionamento de porta
Tecnicamente sim, mas:

- exige configurar roteador;
- CGNAT pode impedir completamente;
- IP pode mudar;
- é inadequado expor o protocolo atual diretamente.

### VPN de malha
Tailscale/ZeroTier podem fazer os dois PCs parecerem estar na mesma LAN.
Você não precisa manter uma VPS própria, mas usa infraestrutura de terceiros.

### P2P/WebRTC
P2P reduz o uso do relay, mas normalmente ainda precisa de:

- signaling/rendezvous;
- STUN;
- TURN/relay quando NAT impede P2P.

Por isso o desenho recomendado para o ConectaPC é:

    LAN direta
       ↓ se não encontrar
    Internet P2P (futuro)
       ↓ se falhar
    Relay

## Próximas melhorias recomendadas

1. criptografia E2E entre clientes;
2. P2P/ICE/STUN;
3. relay apenas como fallback;
4. H.264/H.265 com aceleração de hardware;
5. canais separados para vídeo, controle e arquivos;
6. métricas de latência/bitrate.
