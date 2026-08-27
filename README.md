# ConectaPC 2.1 — suporte remoto autenticado

Aplicativo Windows para suporte remoto assistido em LAN ou pela internet. A versão 2.1 adiciona a fundação de segurança empresarial: identidade por dispositivo, contas de técnicos com MFA, criptografia ponta a ponta, auditoria, limites contra abuso, atualização assinada e rollback.

## Fluxo de conexão

1. Cada instalação cria uma identidade Ed25519 e um ID permanente.
2. Para internet, o computador é cadastrado uma única vez no relay.
3. O técnico entra com usuário, senha e TOTP/MFA.
4. O ConectaPC tenta localizar o ID na LAN e usa o relay como fallback.
5. Os dois aplicativos validam suas identidades e negociam chaves X25519.
6. Tela, comandos, código temporário e arquivos trafegam em frames ChaCha20-Poly1305.
7. O cliente vê o nome verificado do técnico e a impressão digital do dispositivo antes de permitir.
8. O código temporário possui seis dígitos, uso único e limite de tentativas.

O relay transporta bytes criptografados e não recebe conteúdo de tela, comandos, código temporário ou arquivos em texto claro.

## Modos de funcionamento

O ConectaPC funciona em modo automático e não depende do VPS para uso local:

1. **Rede local:** com `relay_config.json` usando `"enabled": false`, dois computadores na mesma LAN podem se conectar diretamente por ID e código temporário. Não há login de técnico nem servidor intermediário.
2. **Rede local + VPS:** quando o relay for configurado, o aplicativo continua procurando o ID primeiro na LAN. O login do técnico e o túnel pelo servidor só são solicitados se o computador não for encontrado localmente.

Assim, a configuração futura do VPS não desativa nem bloqueia as conexões locais. Para testar a LAN, abra o ConectaPC em dois computadores da mesma rede, informe no primeiro o ID e o código exibidos no segundo e permita o acesso no computador remoto.

## Funcionalidades atuais

- tela remota, mouse e teclado;
- detecção de múltiplos monitores, com botões `Tela 1`, `Tela 2` e controle do mouse na tela selecionada;
- múltiplas sessões simultâneas, com troca por abas ou visualização lado a lado;
- miniaturas locais e suavizadas da última tela nos cartões de sessões recentes;
- envio, recebimento e drag-and-drop de arquivos com tamanho e SHA-256;
- conexão LAN direta;
- conexão por relay sem abrir porta no roteador do cliente;
- consentimento local obrigatório em uma janela separada e persistente;
- painel do proprietário com identificação do solicitante, estado da conexão e encerramento imediato da sessão;
- proteção do painel contra cliques remotos e exclusão da captura quando suportada pelo Windows;
- contas de técnico com MFA;
- cadastro e revogação de dispositivos;
- auditoria de sessões e transferências sem conteúdo sensível;
- atualização por manifesto Ed25519 e rollback do instalador anterior;
- instalador Inno Setup e pipeline Authenticode.

## Configuração mínima

Edite `relay_config.json` antes do build:

    {
      "enabled": true,
      "host": "relay.suaempresa.com.br",
      "port": 443,
      "tls": true,
      "server_name": "relay.suaempresa.com.br",
      "ca_file": "",
      "allow_insecure_dev": false,
      "enrollment_token": "",
      "updates": {
        "manifest_url": "https://updates.suaempresa.com.br/update.json",
        "public_key": "",
        "allow_insecure_dev": false
      }
    }

TLS e validação de certificado são obrigatórios fora do laboratório. A chave pública de atualização de produção deve ser fixada em `updates.py`; a chave vinda do JSON só funciona no modo de desenvolvimento inseguro.

## Relay e cadastro

Os arquivos do servidor estão em `server/`. Depois de instalar o serviço, crie técnicos e códigos de cadastro usando:

    python3 server/manage_security.py --db relay.db add-technician suporte --name "Suporte"
    python3 server/manage_security.py --db relay.db create-enrollment --label "Cliente - PC"

Instruções completas, revogação, auditoria, assinatura e atualização estão em [SECURITY_PHASE1.md](SECURITY_PHASE1.md). A implantação Ubuntu/TLS está em [server/DEPLOY_VPS.md](server/DEPLOY_VPS.md).

## Desenvolvimento e testes

    python -m pip install -r requirements.txt
    python -m unittest discover -v
    python app.py

Teste integrado do relay em laboratório:

    python server/relay_server.py --host 127.0.0.1 --port 45443 --allow-plain --db relay-test.db
    python server/TESTAR_RELAY_LOCAL.py 127.0.0.1 45443 relay-test.db

## Build

    GERAR_INSTALADOR.bat

Resultado esperado:

    dist_installer\ConectaPC_Setup_v2.1.0.exe

Builds de desenvolvimento podem ficar sem assinatura. Para release, defina `CONECTAPC_RELEASE=1`; o pipeline recusará artefatos sem certificado Authenticode válido.

## Preparar um piloto

    .\PREPARAR_ENTREGA_COORDENADOR.ps1
    .\CONFIGURAR_CLIENTE_PRODUCAO.ps1 -RelayHost relay.suaempresa.com.br
    .\VERIFICAR_PILOTO.ps1 -Profile VpsTest

O preflight possui os perfis `Preparation`, `VpsTest` e `Production`. A preparação valida código, testes e pacote sem inventar o domínio; o teste VPS exige DNS/TLS e o Setup de homologação; produção acrescenta chave de atualização e Authenticode. Todos retornam código 2 enquanto houver qualquer bloqueio obrigatório.

## Limites conhecidos

A versão 2.1 ainda é de acesso assistido. Ela não controla tela de login/UAC, não inicia como serviço Windows e ainda não possui clipboard, áudio, codec de vídeo por hardware, P2P/ICE ou reinício com reconexão. Esses itens continuam nas fases posteriores.
