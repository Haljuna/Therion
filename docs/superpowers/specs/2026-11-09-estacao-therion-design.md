# Estação Therion: o tablet antigo como a cara e o painel do Therion

**Data:** 09/11/2026
**Estado:** desenho aprovado em conversa; especificação aguardando revisão
**Escopo:** porteiro e página do tablet (novos, em `scripts/estacao/`); um ajuste na ponte do celular (spec `2026-11-05-ponte-celular-design.md`)
**Depende de:** a fase 2 depende da ponte do celular estar construída

## 1. Objetivo

Transformar um tablet antigo (TR101, Allwinner A10, Android 4.0.4, navegador de 2012) numa estação fixa na mesa que:

- mostra, num olhar, o que o Therion está fazendo (orbe "anel de onda" com um comportamento por estado);
- mostra a saúde do PC (RAM, VRAM, Ollama, voz, transcrição, Therion);
- religa as peças do Therion com um toque, inclusive quando o próprio Therion está fechado ou travado;
- mostra a conversa e permite confirmar ou cancelar ações pendentes (fase 2).

### Decisões do usuário

| Tema | Decisão |
|---|---|
| Entrada | Só tela e toque. O tablet não usa microfone; você continua falando pelo PC. |
| Quem atende o tablet | Um "porteiro" separado no PC, sempre ligado, independente do Therion. |
| Confirmações | O tablet mostra o cartão da ação pendente com Confirmar e Cancelar (fase 2). |
| Visual | Interface de terminal roxa (texto mono, botões `[1] ...`) com a orbe "anel de onda" em vetor, estilo sci-fi anos 80. |
| Orbe por estado | Uma forma só (anel de onda), com comportamento diferente por estado. |
| Botões | Ligar Therion, Subir Ollama, Reiniciar Ollama, Religar voz. |

### Critérios de sucesso

1. Com o Ollama caído, um toque no tablet (dois, no caso de reiniciar) o põe de pé, e o status volta para `ok` sem tocar no PC.
2. O status do tablet reflete uma queda de serviço em no máximo ~4 s.
3. A página roda no navegador do Android 4.0.4 sem erro e com o anel animando a ~10 quadros por segundo.
4. Um aparelho com outro IP, ou sem pareamento, não consegue ver o status nem disparar nenhuma ação.
5. (Fase 2) O anel muda de estado em no máximo ~2 s depois do PC, e uma confirmação feita no tablet tem o mesmo efeito e as mesmas proteções de uma feita no PC.

### Fora do escopo (YAGNI)

- Microfone ou fala no tablet (ficaria para um app Android próprio, se um dia fizer falta).
- Acesso fora da rede de casa e criptografia do tráfego.
- Comandos livres, parâmetros vindos do tablet ou botões configuráveis pela tela.
- Mais de um tablet.
- Orbe sincronizada sílaba a sílaba com a voz (o "falando" tem ritmo genérico).

## 2. Contexto do código atual

- Serviços locais: voz Jarvis em `127.0.0.1:3901`, transcrição em `:3902`, Ollama do Therion em `:11435` (não a 11434 padrão). `Start-Therion.ps1` já checa a saúde de todos (`/health`, `/stt/health`, `/api/version`).
- `scripts/start-local-ollama.ps1` sobe o Ollama de `F:\Ollama\ollama.exe` com os modelos em `F:\Therion\ollama-models` e não sobe outra cópia se a porta 11435 já responde.
- `scripts/VoiceStartup.ps1` sobe voz e transcrição; `scripts/Launch-Therion.ps1` abre o Therion.
- O gateway de voz (`scripts/voice_gateway/server.py`) é o padrão a seguir: `ThreadingHTTPServer` da biblioteca padrão, processo próprio.
- A ponte do celular (spec de 05/11, ainda não construída) cria um servidor na porta 3903 dentro do Therion, com um `ConversationLog` de entradas numeradas (`seq`), estados e confirmações, aceitando um único IP de cliente.

## 3. Arquitetura

```
tablet (navegador) ──HTTP──► PORTEIRO :3904 (PC, sempre ligado) ──loopback──► ponte do Therion :3903 (quando aberto)
                                   │
                                   ├──► saúde: Ollama :11435, voz :3901, transcrição :3902, processo do Therion
                                   ├──► métricas: RAM (Windows), VRAM (nvidia-smi)
                                   └──► ações fixas: scripts .ps1 já existentes
```

### 3.1 Porteiro (`scripts/estacao/porteiro.py`, novo)

- Processo Python próprio, só biblioteca padrão. Não importa o pacote `therion` (sobe rápido e não cai junto com ele).
- `ThreadingHTTPServer` na porta 3904 (configurável), escutando no IP da rede de casa.
- Configuração e segredos em `%LOCALAPPDATA%\Therion\estacao\` (fora do repositório, que é público):
  - `config.json`: `client_ip` (IP do tablet, reservado no roteador), `port` (3904), `bind` (IP do PC na rede).
  - `token`: senha longa (`secrets.token_urlsafe(32)`), gerada na primeira execução.
- Partes internas, cada uma testável sozinha:
  - **Guarda**: aceita só `client_ip`; exige o cookie `estacao=<token>`, exceto na página de pareamento.
  - **Pareamento**: `porteiro.py --parear` grava um código de 6 dígitos com validade de 5 minutos e o mostra no terminal. O tablet envia o código; se bater, o porteiro responde com o cookie (sem expiração) e o código é apagado. No máximo 5 tentativas erradas por código.
  - **Saúde**: a cada 2 s mede RAM (`GlobalMemoryStatusEx` via `ctypes`), VRAM (`nvidia-smi --query-gpu=memory.used,memory.total --format=csv`), Ollama (`GET :11435/api/version`), voz (`GET :3901/health`), transcrição (`GET :3902/stt/health`) e Therion (fase 1: existe um `pythonw.exe` do `F:\Therion\app\.venv` cuja linha de comando contém o ponto de entrada do desktop que o `Start-Therion.ps1` inicia, lido via `Get-CimInstance Win32_Process`; o nome exato do ponto de entrada é confirmado no plano; fase 2: ponte respondendo). Timeout de 1 s por checagem; falha vira `--`.
  - **Ações**: tabela fixa no código, `id → script .ps1`. Uma ação por vez; outra chegando no meio recebe `ocupado`. Timeout de 120 s; estouro vira `falhou: tempo esgotado`. O resultado entra no registro de mensagens do porteiro.
  - **Repasse da ponte (fase 2)**: lê o token da ponte em `%LOCALAPPDATA%\Therion\remote\token` e repassa conversa, estado e confirmação.

### 3.2 Ações (fase 1)

| id | Botão | Executa | Proteção |
|---|---|---|---|
| 1 | `LIGAR THERION` | `scripts/Launch-Therion.ps1` | se o Therion já está vivo, responde `já está ligado` sem executar |
| 2 | `SUBIR OLLAMA` | `scripts/start-local-ollama.ps1` | o script já ignora se a 11435 responde |
| 3 | `REINICIAR OLLAMA` | encerra só o `ollama.exe` que escuta na 11435 (PID achado pela porta) e roda `start-local-ollama.ps1` | toque duplo |
| 4 | `RELIGAR VOZ` | `scripts/VoiceStartup.ps1` | toque duplo |

- Toque duplo é feito na página: o primeiro toque muda o rótulo para `[ TOQUE DE NOVO ]` por 3 s; só o segundo toque envia a ação.
- Os scripts rodam com `powershell -NoProfile -ExecutionPolicy Bypass -File <script>`, sem janela, com o caminho montado a partir da pasta do repositório; nada vindo do tablet entra na linha de comando.

### 3.3 Página do tablet (`scripts/estacao/estacao.html`, nova)

- Um arquivo só (HTML, CSS e JS juntos), servido pelo porteiro.
- **JavaScript ES5 apenas** (sem `=>`, `let`, `const`, crases, `fetch`, `class`), porque o navegador do Android 4.0 não entende o resto. Usa `XMLHttpRequest`.
- Sem WebSocket (o navegador não tem): pergunta `GET /estado` a cada 1 s.
- **Duas posições** (o tablet fica deitado ou em pé; tem acelerômetro e a rotação automática está ligada):
  - **Deitado (1024×600)**, como o mockup aprovado: anel à esquerda com o rótulo `[ ESTADO ]`; à direita, o cabeçalho `THERION OS v1 -- ESTACAO 01`, as últimas linhas da conversa, o cartão de confirmação (fase 2), a linha de status e os 4 botões em grade 2×2.
  - **Em pé (600×1024)**: tudo empilhado. De cima para baixo: cabeçalho, anel maior (raio até ~1,5× o de deitado) com o rótulo, conversa, cartão de confirmação, status e botões em grade 2×2 no rodapé, ao alcance do polegar.
  - A troca é só por CSS (`@media (orientation: portrait)`, que o navegador de 2012 entende), sem recarregar a página. O anel usa o mesmo `viewBox` e só muda de tamanho.
- Paleta: fundo `#0d0a18`, texto `#b9a8ff`, apagado `#6e5bd6`, claro `#e7e0ff`, linhas `#9b87ff`/`#4b3bb0`, erro `#e2738f`. Fonte monoespaçada do sistema.
- Anel desenhado em SVG por JS a ~10 quadros por segundo (`setInterval` de 100 ms), com 120 pontos por volta.

### 3.4 Comportamento do anel por estado

| Estado | Comportamento | Fase |
|---|---|---|
| parado | anel liso, raio respirando devagar (±2 px) | 1 |
| ouvindo | ondulação fina e ondas concêntricas fechando para o centro | 2 |
| pensando | um calombo correndo em volta do anel e um anel tracejado girando por dentro | 2 |
| falando | onda grande (8 lóbulos) com amplitude variando, e um eco menor por dentro | 2 |
| aguarda sim | anel claro pulsando e um anel tracejado por fora; cartão de confirmação visível | 2 |
| offline | anel vermelho, partido numa ponta, com falhas raras; ponto central vermelho | 1 |

- Na fase 1, o anel fica em `parado` quando o Therion está vivo e em `offline` quando não está.
- Na fase 2, o estado vem da ponte. A ponte precisa expor `ouvindo` e `falando` além dos estados já previstos na spec dela (ver 3.6).

### 3.5 Contrato HTTP do porteiro

| Rota | Uso | Resposta |
|---|---|---|
| `GET /` | página do tablet (ou de pareamento, sem cookie válido) | HTML |
| `POST /parear` | corpo `codigo=123456` | `204` + `Set-Cookie`, ou `403` |
| `GET /estado` | status, estado do anel e mensagens novas (`?desde=<seq>`) | JSON: `{"estado","status":{...},"mensagens":[...],"confirmacao":null\|{...},"acao":null\|"<id>"}` |
| `POST /acao/<id>` | dispara a ação `id` (1–4) | `202` aceito, `409` ocupado, `404` id desconhecido |
| `POST /confirmar` (fase 2) | corpo `confirmation_id=...&resposta=sim\|nao` | repasse da ponte |

Qualquer rota fora da guarda (IP ou cookie) responde `403` sem corpo.

### 3.6 Ajuste na ponte do celular

- Aceitar também conexões de `127.0.0.1` (o porteiro), além do `client_ip` do celular, sempre com a mesma senha.
- Registrar no `ConversationLog` os estados `ouvindo` e `falando`, nos mesmos pontos em que a tela muda a orbe.
- Nenhum poder novo: o porteiro repassa apenas o que a ponte já oferece ao celular.

## 4. Falhas e como aparecem

| Situação | O que o tablet mostra |
|---|---|
| Therion fechado | status `THERION --`, anel `offline`; botão 1 funciona |
| Ollama, voz ou transcrição caídos | a palavra do serviço em vermelho (`OLLAMA caiu`) |
| Porteiro parou depois da página aberta | `PORTEIRO SEM RESPOSTA` no lugar da conversa; continua tentando a cada 3 s |
| Ação em curso | botão mostra `[ ... ]`; outros toques recebem `> porteiro: ocupado` |
| Ação falhou ou estourou o tempo | `> porteiro: falhou: <motivo curto>` |
| `nvidia-smi` ausente | `VRAM --` |

**Inicialização com o Windows:** `scripts/estacao/Install-Estacao.ps1` cria uma tarefa agendada no logon do usuário que roda o porteiro e o reinicia se cair. O usuário roda o script; nada é criado automaticamente.

**Firewall:** o usuário cria a regra liberando a porta 3904 só para o IP do tablet, no perfil Privado. O comando fica pronto no `README.md` da pasta.

**Tablet:** em Configurações → Tela, tempo limite em "Nunca" (fica na tomada); a página fica aberta no navegador padrão.

## 5. Riscos aceitos

- Tráfego HTTP sem criptografia na rede de casa: alguém na mesma rede pode ler o cookie e o status. Mitigado pelo filtro de IP e pela lista fixa de ações.
- A ação 3 encerra o Ollama mesmo no meio de uma resposta do Therion. É exatamente o uso esperado (Ollama travado), e exige toque duplo.

## 6. Testes

- **Porteiro (pytest, com peças falsas para relógio, rede e execução de scripts):** IP bloqueado; sem cookie; pareamento certo, expirado e com tentativas demais; ação aceita, `ocupado`, id desconhecido, erro do script e tempo esgotado; saúde com serviço caído e com `nvidia-smi` ausente.
- **Página:** teste que reprova o `estacao.html` se encontrar sintaxe fora do ES5 (`=>`, `let `, `const `, crase, `fetch(`, `class `).
- **No tablet real (lista manual):** página abre e pareia; anel anima sem engasgar; derrubar o Ollama muda o status; o botão 3 com toque duplo o religa; desligar o porteiro mostra `PORTEIRO SEM RESPOSTA`.

## 7. Ordem de construção

1. **Fase 1:** porteiro (guarda, pareamento, saúde, ações), página com anel em `parado`/`offline`, script da tarefa agendada, README com o comando de firewall; depois, o modo estação (seção 8: app, animação de inicialização e configuração do tablet).
2. **Ponte do celular**, pela spec de 05/11, já com o ajuste da seção 3.6.
3. **Fase 2:** repasse da ponte no porteiro, estados completos do anel, conversa e cartão de confirmação.

## 8. Modo estação (o tablet vira um aparelho só da estação)

Decidido em 09/11/2026, depois da otimização do tablet (root via ADB, 30 apps desativados). Faz parte da fase 1 e vem depois da página pronta.

### 8.1 Objetivo e critérios

O tablet liga direto na estação, em tela cheia, sem tela de bloqueio nem barra do Android, com uma animação de inicialização no tema do Therion.

1. Do botão de ligar até a estação aparecem só a animação do Therion e a estação, sem a área de trabalho do Android, sem o bloqueio e sem a barra.
2. A estação ocupa a tela inteira, deitado (1024×600) ou em pé (600×1024), gira sozinha quando o tablet muda de posição, e a tela não apaga.
3. Se o porteiro ou o Wi-Fi ainda não estiverem de pé, o app mostra uma tela de espera no tema e tenta de novo sozinho, sem página de erro do Android.
4. Existe uma saída sem cabo: segurar 5 s no cabeçalho liga a barra e abre as configurações; repetir o gesto desliga a barra de novo.
5. Tudo é reversível por um script (`-Desfazer`), que devolve o launcher, a barra, o bloqueio e a animação de fábrica.

### 8.2 App "Estação" (APK)

- Pacote `com.therion.estacao`, `minSdkVersion` e `targetSdkVersion` 15, uma única `Activity` (`EstacaoActivity`), sem bibliotecas.
- Filtros de intent: `MAIN` + `HOME` + `DEFAULT` (é a tela inicial) e `MAIN` + `LAUNCHER`.
- Tema `Theme.NoTitleBar.Fullscreen`, `screenOrientation="sensor"` (gira com o tablet, deitado ou em pé), `configChanges` com `orientation|screenSize` (a página não recarrega ao girar), `FLAG_KEEP_SCREEN_ON`.
- Um `WebView` com JavaScript e cookies ligados (`CookieManager` + `CookieSyncManager.sync()` em `onPause`) carrega o endereço do porteiro, guardado em `SharedPreferences`. O endereço é gravado na instalação: `am start -n com.therion.estacao/.EstacaoActivity --es url http://<IP do PC>:3904/`. Sem endereço gravado, abre a tela de espera com o texto `SEM ENDERECO DO PORTEIRO`.
- Erro de carregamento (`onReceivedError`) → carrega `file:///android_asset/espera.html`: o mesmo visual (fundo `#0d0a18`, anel em `offline`, texto `AGUARDANDO PORTEIRO...`), que volta ao endereço do porteiro a cada 5 s.
- Botão voltar ignorado. **Sem `addJavascriptInterface`**, que é inseguro no Android 4.0. A página fala com o app só navegando para `estacao://manutencao`, interceptado em `shouldOverrideUrlLoading`.
- `estacao://manutencao`:
  - se a barra está desligada → `su -c "pm enable com.android.systemui"` e abre `Settings.ACTION_SETTINGS`;
  - se está ligada → `su -c "pm disable com.android.systemui"`.
  - O estado vem de `PackageManager.getApplicationEnabledSetting("com.android.systemui")`.
- Montado sem Gradle (`aapt2`, `javac --release 8`, `d8 --min-api 15`, `zipalign`, `apksigner` com assinatura v1) por `scripts/estacao/app/build.ps1`. A chave de assinatura fica em `%LOCALAPPDATA%\Therion\estacao\estacao.keystore`, fora do repositório. As ferramentas oficiais do Android (command-line tools, build-tools e plataforma android-15) ficam em `F:\Android-SDK`. O JDK 21 já instalado é usado.

### 8.3 Mudanças na página

- Em `estacao.html`, segurar 5 s em cima do cabeçalho `THERION OS v1 -- ESTACAO 01` faz `location.href = 'estacao://manutencao'`. Funciona com toque (`touchstart`/`touchend`) e mouse. No navegador comum, o link desconhecido não faz nada.
- O layout passa a ocupar a tela inteira (1024×600 deitado, 600×1024 em pé), sem a faixa de 48 px que a barra ocupava.

### 8.4 Configuração do tablet (`scripts/estacao/tablet/Modo-Estacao.ps1`, via ADB com `ADB_LIBUSB=1`)

Em ordem:
1. Instala o APK (`adb install -r`).
2. Grava o endereço do porteiro (comando do 8.2).
3. Desativa o launcher de fábrica (`pm disable com.android.launcher`), para o app ser a única tela inicial, sem a pergunta "usar por padrão".
4. Desliga o bloqueio de tela: grava `lockscreen.disabled=1` na tabela `secure` do `settings.db` via `sqlite3` (root). A tela de bloqueio já está em "Nenhum" ou "Deslizar"; se houver PIN ou padrão, o script para e avisa.
5. Copia `bootanimation.zip` para `/data/local/bootanimation.zip`. O Android 4.0 usa esse arquivo antes do de fábrica, então a animação original em `/system/media` fica intacta e não é preciso mexer em `/system`.
6. Desliga a barra (`pm disable com.android.systemui`) e reinicia.

Com `-Desfazer`, faz o caminho inverso: liga barra e launcher, `lockscreen.disabled=0`, apaga `/data/local/bootanimation.zip` e desinstala o app. Cada passo informa o que fez. Se o tablet não aparecer no ADB, o script para logo no início.

### 8.5 Animação de inicialização (`scripts/estacao/tablet/bootanimacao.py`)

- Gera `bootanimation.zip` com Pillow (já no `.venv`): `desc.txt` = `1024 600 12`, `p 1 0 part0` e `p 0 0 part1`; arquivos PNG sem compressão no zip (`ZIP_STORED`, exigência do Android).
- **Funciona nas duas posições:** a animação de inicialização do Android não gira (é desenhada sempre deitada), então ela **não tem texto**. Só o anel, que é redondo e centralizado, fica igual com o tablet deitado ou em pé.
- `part0` (toca uma vez, ~2,5 s): fundo `#0d0a18`; o anel de onda se forma no centro, de um ponto até o raio cheio, com um clarão `#e7e0ff` no fim.
- `part1` (repete até o Android terminar de ligar): o anel de onda no estado `falando`, em loop de 24 quadros.
- Mesma paleta e mesmo desenho de anel da página (seção 3.4).

### 8.6 Riscos aceitos

- Sem a barra, também somem as notificações do Android e o relógio do sistema. A estação substitui os dois.
- Se o app travar sem abrir, a saída é pelo cabo (`Modo-Estacao.ps1 -Desfazer`). O `su` desse firmware responde sem pedir confirmação; o plano confere isso antes de depender dele.

## 9. Arquivos

| Arquivo | Novo/alterado | Fase |
|---|---|---|
| `scripts/estacao/porteiro.py` | novo | 1 (repasse na 2) |
| `scripts/estacao/estacao.html` | novo | 1 (estados e cartão na 2) |
| `scripts/estacao/Install-Estacao.ps1` | novo | 1 |
| `scripts/estacao/README.md` | novo | 1 |
| `tests/test_estacao_porteiro.py`, `tests/test_estacao_es5.py` | novos | 1 |
| `therion/interface/remote_bridge.py` | ajuste da 3.6 | ponte |
| `scripts/estacao/app/` (`AndroidManifest.xml`, `EstacaoActivity.java`, `assets/espera.html`, `build.ps1`) | novos | 1 (modo estação) |
| `scripts/estacao/tablet/Modo-Estacao.ps1`, `scripts/estacao/tablet/bootanimacao.py` | novos | 1 (modo estação) |
