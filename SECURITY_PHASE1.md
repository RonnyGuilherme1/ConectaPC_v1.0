# ConectaPC 2.1 — implantação segura da Fase 1

## O que mudou

- identidade Ed25519 permanente por instalação, com chave privada protegida pelo DPAPI no Windows;
- confiança no primeiro uso (TOFU): depois do primeiro acesso aprovado, mudança da chave do computador ou console é bloqueada;
- handshake autenticado X25519 e frames ChaCha20-Poly1305 entre os dois computadores;
- código temporário de seis dígitos, uso único e bloqueio após cinco erros em cinco minutos;
- dispositivos cadastrados por token de uso único;
- técnicos autenticados por usuário, senha com scrypt e TOTP/MFA;
- sessão do técnico com validade de 15 minutos e vínculo ao dispositivo do console;
- rate limits, limite de sessões e tamanho máximo de frames no relay;
- auditoria SQLite sem PIN, senha, conteúdo de tela, nome ou hash de arquivo;
- arquivos recebidos por arquivo temporário, limite de 10 GB, espaço livre, tamanho e SHA-256;
- manifesto de atualização Ed25519, HTTPS, SHA-256, limite de tamanho e instalador anterior para rollback;
- pipeline Authenticode que bloqueia releases quando `CONECTAPC_RELEASE=1` e não há certificado.

## 1. Preparar o relay

No Windows de desenvolvimento, gere primeiro o pacote sem segredos:

    .\PREPARAR_ENTREGA_COORDENADOR.ps1

Envie `dist_relay\conectapc-relay-2.1.0.zip` para a VPS, extraia e execute `sudo ./install_relay.sh` depois de instalar o certificado TLS nos caminhos documentados.

Copie para `/opt/conectapc-relay`:

    relay_server.py
    security_store.py
    manage_security.py

O serviço systemd cria e protege `/var/lib/conectapc/relay.db`. TLS público continua obrigatório.

Crie o primeiro técnico:

    sudo -u conectapc python3 /opt/conectapc-relay/manage_security.py \
      --db /var/lib/conectapc/relay.db \
      add-technician suporte --name "Nome do técnico"

Use uma senha de pelo menos 12 caracteres e cadastre o segredo/URI exibido em um autenticador TOTP. O segredo aparece somente no comando de criação.

## 2. Cadastrar cada computador

Gere um código individual e de uso único:

    sudo -u conectapc python3 /opt/conectapc-relay/manage_security.py \
      --db /var/lib/conectapc/relay.db \
      create-enrollment --label "Cliente - Computador" --hours 24

No ConectaPC do cliente, clique em **Cadastrar este computador** e cole o código. A credencial definitiva será protegida pelo DPAPI e o código de cadastro não será salvo.

Para revogar imediatamente:

    sudo -u conectapc python3 /opt/conectapc-relay/manage_security.py \
      --db /var/lib/conectapc/relay.db disable-device 123456789

Também é possível revogar um técnico e todas as sessões dele com `disable-technician`.

## 3. Configurar o cliente

Antes do build, configure `relay_config.json` com `enabled`, domínio, porta 443 e TLS. Nunca distribua `allow_insecure_dev=true`.

    .\CONFIGURAR_CLIENTE_PRODUCAO.ps1 -RelayHost relay.suaempresa.com.br
    .\VERIFICAR_PILOTO.ps1 -Profile VpsTest

Use `-Profile Preparation` antes de receber o domínio, `-Profile VpsTest` para
a homologação pública sem assinatura comercial e `-Profile Production` para a
liberação oficial com atualização assinada e Authenticode.

A versão 2.1 é incompatível com o protocolo 2.0. Atualize console e clientes em conjunto.

No primeiro acesso, confira a impressão digital mostrada ao cliente. Nos acessos seguintes, o ConectaPC bloqueia automaticamente qualquer mudança de identidade. Para trocar legitimamente um computador/reinstalar a identidade, é necessário revogar o dispositivo e remover conscientemente a entrada correspondente de `%LOCALAPPDATA%\ConectaPC\known_peers.json` nos lados que já confiavam nele.

## 4. Assinatura do executável e instalador

Obtenha um certificado Authenticode OV/EV ou serviço de assinatura compatível e configure somente na máquina/CI de release:

    $env:CONECTAPC_RELEASE = "1"
    $env:CONECTAPC_SIGN_PFX = "C:\segredos\empresa.pfx"
    $env:CONECTAPC_SIGN_PASSWORD = "senha-do-pfx"
    .\GERAR_INSTALADOR.ps1

O pipeline assina e verifica tanto `ConectaPC.exe` quanto o Setup. Sem assinatura válida, um release marcado é interrompido.

## 5. Atualizações assinadas e rollback

Gere a chave Ed25519 em um computador offline:

    python tools/generate_update_key.py --private-key D:\offline\conectapc-update.pem

Nunca coloque a chave privada no relay, repositório ou instalador. Copie somente a chave pública exibida para `PINNED_UPDATE_PUBLIC_KEY` em `updates.py`, gere e assine o release Authenticode.

Depois de publicar o Setup via HTTPS, crie o manifesto:

    python tools/sign_update_manifest.py \
      dist_installer\ConectaPC_Setup_v2.1.0.exe \
      --version 2.1.0 \
      --url https://updates.exemplo.com/ConectaPC_Setup_v2.1.0.exe \
      --private-key D:\offline\conectapc-update.pem \
      --output update.json

Configure apenas a URL HTTPS do manifesto. O aplicativo verifica assinatura, versão, tamanho e SHA-256 antes de executar. O instalador anterior fica em `%LOCALAPPDATA%\ConectaPC\updates\rollback_setup.exe`.

## 6. Auditoria e privacidade

O banco registra autenticações, dispositivo online/offline, início/fim de sessão, decisão de consentimento e direção/tamanho de transferências. Endereços de origem são registrados somente como HMAC truncado. O padrão retém 90 dias.

Em produção, defina `CONECTAPC_AUDIT_KEY` no ambiente protegido do serviço com 32 bytes aleatórios em hexadecimal e mantenha essa chave fora do banco/backup. Sem ela, o relay cria uma chave local no SQLite para facilitar apenas o primeiro laboratório.

Faça backup criptografado do banco, restrinja acesso ao grupo do serviço e defina a retenção adequada aos contratos da empresa. Não registre conteúdo de tela, teclas, PIN, senha, MFA ou nomes de arquivos.

## Limites que permanecem fora da Fase 1

Ainda não existem serviço Windows para tela de login/UAC, múltiplos monitores, codec por hardware, P2P/ICE, clipboard ou reinício com reconexão. Esses itens pertencem às fases seguintes e não devem ser anunciados como disponíveis.
