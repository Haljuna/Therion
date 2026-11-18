# Modo foco e lembretes por voz — desenho

Data: 2026-11-18. Branch: `foco-lembretes` (árvore `F:\Therion\foco-wt`, criada a partir do master 11f0390).
Modelos visuais escolhidos: https://claude.ai/artifact/7N2rDLWNLfrcHSgM7zYbG1 (modelo **E**, "minutos no centro").

## 1. Intenção

Duas funções novas, faladas ou digitadas, que respondem na hora (rota local, sem o modelo):

1. **Modo foco** — "Therion, foco 50 minutos". O Therion segura os próprios avisos, mostra o tempo na orbe e, no fim, diz numa fala só: quanto tempo focou (e o total do dia), o que segurou, quantos e-mails chegaram (e os importantes) e oferece uma pausa no estilo Pomodoro.
2. **Lembretes por voz** — "me lembra de tirar a roupa da máquina em 40 minutos", "às 18h", "amanhã às 9", e também os que repetem ("todo dia às 8h tomar remédio", "toda segunda e quarta às 7", "dias úteis às 9").

Por quê: o usuário passa muito tempo no PC (estudo, projetos, jogos) e quer que o Therion cuide do tempo por ele, sem abrir app nem clicar. Toda decisão abaixo parte do momento de uso: falar uma frase e esquecer.

## 2. Objetivos, não objetivos e o que seria fracasso

**Objetivos**
- Criar lembrete com uma frase, sem confirmação visual, com resposta falada imediata repetindo o que entendeu (dia, hora e texto).
- Lembrete avisa na hora certa (erro ≤ 2 s com o PC ligado), com voz, **mesmo no jogo em tela cheia e mesmo durante o foco**.
- Lembrete sobrevive a fechar e reabrir o Therion.
- Foco com tempo visível na mini orbe e na orbe grande (modelo E), resumo no fim e oferta de pausa.

**Não objetivos (fora desta versão)**
- Avisar com o Therion fechado (Agendador do Windows, notificação do sistema) — caminho B, recusado.
- Sincronizar com Google Agenda/Tarefas ou celular — caminho C, recusado.
- Segurar notificações de outros apps (Discord, WhatsApp, Windows). O "Não perturbe" do Windows é configuração do sistema e não tem API oficial; não mexer.
- Repetição mensal/anual ("todo dia 5", "todo aniversário"), "a cada 2 horas", lembrete por lugar.
- Vigiar o Gmail durante o foco. O Therion não tem vigia de e-mail; a contagem é feita uma vez, no fim.

**Fracasso mesmo funcionando**
- Lembrete que corta a fala do Therion no meio (o `SpeechOutput.speak` chama `stop()`; ver §6.4).
- Lembrete perdido em silêncio (fechou, hibernou, deu erro de arquivo) sem aviso nenhum depois.
- "Me lembra que…" de memória (rota que já existe) virar lembrete, ou o contrário.
- A orbe mudar fora do foco, ou a contagem cortada nas bordas da mini orbe.
- Foco que trava a conversa: o Therion tem de continuar respondendo normalmente durante o foco.

## 3. Caminhos considerados

| Caminho | Como | Troca | Decisão |
|---|---|---|---|
| **A. Dentro do Therion** | Módulos puros em `core/`, depósito JSON em `%LOCALAPPDATA%\Therion`, disparo por `QTimer` na janela | Sem aviso com o Therion fechado; ao abrir, avisa o que passou | **Escolhido pelo usuário** |
| B. Agendador do Windows + notificação | Uma tarefa agendada por lembrete | Avisa fechado, mas sem a voz do Therion, sem conversar com o foco, e cria configuração no sistema | Recusado |
| C. Google Agenda/Tarefas | Escrita na conta Google | Toda escrita passa pelo painel Capacidades (regra de segurança), depende da rede, lento | Recusado |

## 4. Decisões do usuário (18/11)

1. Lembrete que vence durante o foco **fura o foco** (fala na hora). Só os avisos automáticos (vigia do PC, compromissos da agenda) esperam o fim.
2. No jogo em tela cheia ou com modo jogo ligado, o lembrete **fala mesmo assim**. O vigia continua só escrevendo, como hoje.
3. O fim do foco traz os **quatro** itens: avisos segurados, e-mails que chegaram, tempo focado (com total do dia) e sugestão de pausa.
4. Repetição **entra já** nesta versão.
5. Caminho **A**.
6. Visual: modelo **E** — minutos no centro + arco fino de progresso **por fora dos anéis** da moldura HUD, que ficam intactos.
7. Aparece **nas duas orbes** (mini e grande).
8. A orbe continua sendo a Orbe HUD atual; o modelo E só soma o número e o arco por cima, e só durante foco e pausa.

## 5. Funcionamento — Lembretes

### 5.1 Frases que criam lembrete

Gatilhos (depois de `control()` / `normalized()` — sem acento, minúsculas): `me lembra`, `me lembre`, `lembra-me`, `lembre-me`, `me avisa`, `me avise`, `me chama`, `cria (um) lembrete`, `lembrete:`. Todos exigem **quando** e **o quê**.

Quando (uma vez):
- relativo: `em 40 minutos`, `daqui a 2 horas`, `daqui a uma hora e meia`, `daqui a meia hora`, `em 1 hora e 15`, `daqui a pouco` (= 10 min).
- hora: `às 18h`, `às 18:30`, `às 6 da tarde`, `ao meio-dia`, `à meia-noite`, `às dezoito horas` (números falados via `normalize_spoken_fields`).
- dia + hora: `amanhã às 9`, `segunda às 10`, `sexta que vem às 14h`, `dia 25 às 8` (próximo dia 25).
- Reaproveitar `calendar/dialogue.py` (`parse_day`, `parse_time`) e `calendar/spoken.py` (`spoken_time`, `spoken_date`) — o mesmo entendimento de horário da agenda, inclusive o erro de "dez seis" ambíguo.

Quando (repete):
- `todo dia às 8`, `todos os dias às 8`, `diariamente às 8`.
- `toda segunda às 7`, `toda segunda e quarta às 7`, `às terças e quintas às 19h`.
- `dias úteis às 9`, `de segunda a sexta às 9` (seg–sex).
- `fim de semana às 10`, `sábado e domingo às 10`.
- Repetição **exige hora**. Sem hora: pergunta "Que horas?".
- Repetição com hora de 1 a 11 **sem período** ("todo dia às 6"): pergunta "Seis da manhã ou da tarde?" (decisão do usuário, 18/11) e aceita "manhã", "tarde", "noite" ou a hora com 24 h na próxima frase (2 min). Com 0, 12, 13–23, "meio-dia", "meia-noite" ou período na frase, não pergunta.

Regra da hora sem período ("às 6") num lembrete **de uma vez**: vale a próxima ocorrência futura entre 6:00 e 18:00 (a mais próxima de agora). Com "da manhã/tarde/noite" vale o período. Hora já passada hoje sem dia dito → amanhã. A resposta sempre diz o dia e a hora por extenso, então o usuário percebe o erro na hora.

O quê: o resto da frase depois de tirar gatilho e tempo, sem `de`/`para`/`que` iniciais (`me lembra de tirar a roupa da máquina` → "tirar a roupa da máquina"). Máximo 200 caracteres. Ordem livre: "me lembra às 18h de ligar pro João" também vale.

Falta algo → pergunta curta, válida por 2 min e só para a próxima frase (mesmo padrão de `pc_cleanup.offer`):
- sem quando: "Quando eu te lembro?"
- sem o quê: "Te lembro do quê?"
- frase ambígua de horário: a mensagem do `CalendarError`.

**Fronteira com a memória** (`memory/commands.py`, "lembre que…", "anota que…"): "me lembra/lembre **que** X" **sem tempo** continua sendo memória como hoje. Só vira lembrete quando há expressão de tempo. Todas as frases novas entram em `tests/frases_reais.txt` (`frase => rota`) junto com as de memória que não podem mudar de rota.

### 5.2 Respostas ao criar

- Uma vez: "Combinado: hoje às 18h, tirar a roupa da máquina." / "Combinado: em 40 minutos, às 15h12, tirar a roupa da máquina." / "Combinado: amanhã, quinta, às 9h, …".
- Repete: "Combinado: todo dia às 8h, tomar remédio. O próximo é amanhã."
- Fala usa `spoken_time` ("às dezoito horas"); a tela usa "18:00".

### 5.3 Outras frases

- Listar: "quais lembretes eu tenho", "meus lembretes", "tem algum lembrete?" → "Você tem 3 lembretes: hoje às 18h, tirar a roupa…; todo dia às 8h, tomar remédio; …". Nenhum: "Nenhum lembrete marcado."
- Cancelar um: "cancela o lembrete (da roupa / das 18h)", "apaga o lembrete do remédio". Escolhe pelo texto (palavras em comum) ou pela hora. Um só candidato → cancela e diz qual. Vários → "Qual deles? 1) … 2) …" e aceita o número ou o texto na próxima frase (2 min). Nenhum → "Não achei esse lembrete."
- Cancelar todos: "cancela todos os lembretes" → "Cancelo os 3 lembretes?" e espera "sim" (2 min). Única ação que pede "sim" — apaga mais de um de uma vez.
- Adiar (até 5 min depois de um lembrete tocar): "adia 10 minutos", "me lembra de novo em 5 minutos", "daqui a pouco" → reagenda o mesmo texto como lembrete de uma vez. Num lembrete que repete, o adiamento cria uma cópia de uma vez; o próximo da repetição continua no horário.
- "Pula o de amanhã" / pular uma ocorrência: fora desta versão.

### 5.4 Quando toca

- Na hora, se o Therion está livre: escreve na conversa e fala "Lembrete: tirar a roupa da máquina." (lembrete que repete: igual).
- "Livre" = sem pedido em andamento (`_processing`), sem plano esperando (`_pending_plan`), sem fala tocando, sem microfone gravando/transcrevendo, sem confirmação aberta. Se não está livre, o lembrete entra numa fila e sai assim que ficar livre (checado a cada mudança de estado da orbe e no tique de 30 s). **Nunca interrompe a fala nem a escuta.**
- Fura o foco e fala no jogo (decisões 1 e 2). Não abre a janela grande sozinho.
- A mini orbe acompanha: enquanto fala, ela já vai para o estado "speaking" pelo caminho atual (`_sync_mini_orb`).
- Vários vencendo juntos: uma fala só — "Dois lembretes: tirar a roupa da máquina; ligar para o João."
- Depois de tocar: o de uma vez sai do depósito; o que repete ganha a próxima data.

### 5.5 Atrasado (Therion fechado, PC dormindo ou hibernando)

- Ao abrir o Therion (depois da janela pronta, antes da saudação se ela vier): "Enquanto eu estava fechado, passou da hora de: tirar a roupa da máquina (18:00)." Mais de 3 → "Passaram 5 lembretes enquanto eu estava fechado: …" com os 3 primeiros e "e mais 2".
- Ao acordar de suspensão/hibernação: o `QTimer` dispara atrasado; tudo que venceu há mais de 2 min usa a mesma frase com "passou da hora".
- O que repete: avisa uma vez (só a ocorrência mais recente perdida) e agenda a próxima futura. Nunca fala 7 vezes "tomar remédio" depois de uma semana fechado.
- Atrasado há mais de 7 dias: some sem aviso individual, entra só na contagem ("e mais N antigos").

### 5.6 Depósito

- Arquivo `%LOCALAPPDATA%\Therion\lembretes.json`:
  ```json
  {"version": 1, "items": [
    {"id": "r-7f3a", "text": "tirar a roupa da máquina", "due": "2026-11-18T18:00:00",
     "repeat": null, "created": "2026-11-18T17:20:04"},
    {"id": "r-91bc", "text": "tomar remédio", "due": "2026-11-19T08:00:00",
     "repeat": {"days": [0,1,2,3,4,5,6], "time": "08:00"}, "created": "…"}
  ]}
  ```
  `days` usa `weekday()` do Python (0 = segunda). Horas locais sem fuso (o Brasil não tem horário de verão desde 2019; se voltar, a hora local continua sendo a certa para o usuário).
- Gravação atômica (temporário + `fsync` + `os.replace`, como `briefing.BriefingMarker` e `pc_watch._write_photo`) sob um `threading.Lock` do processo, porque o orchestrator (thread do worker) cria/cancela e a janela (thread do Qt) dispara/reagenda.
- Arquivo corrompido ou ilegível: renomeia para `lembretes.json.bad-<data>`, começa vazio e avisa uma vez: "Não consegui ler seus lembretes antigos; guardei o arquivo como … ." Nunca apaga.
- Limite: 50 lembretes ativos ("Você já tem 50 lembretes; cancele algum antes.").
- Os testes nunca tocam o arquivo real: o caminho vem de `LOCALAPPDATA`, já isolado por `tests/conftest.py`.
- Privacidade: o texto do lembrete é pessoal e só fica local. O repositório é **público**: testes e frases de exemplo com textos inventados.

## 6. Funcionamento — Modo foco

### 6.1 Frases

- Começar: "foco", "modo foco", "ativa o modo foco", "foco 50 minutos", "foco de 1 hora", "foco de uma hora e meia", "vou focar 30 minutos", "quero focar", "começa um foco". Sem duração → 50 min (`focus.minutes`, padrão 50). Aceita 5 a 180 min; fora disso: "Dá para focar de 5 a 180 minutos."
- Durante: "quanto falta (do foco)?" → "Faltam 32 minutos de foco." / "mais 10 minutos" (estica, até 180 no total) / "sai do foco", "para o foco", "cancela o foco", "chega de foco" → termina antes (resumo igual ao do fim, com o tempo real focado).
- "foco" com um foco já ligado → "Você já está em foco; faltam 32 minutos."
- Pausa: só pela oferta do fim (§6.3) ou "pausa de 10 minutos" depois de um foco. "sai da pausa" encerra a pausa.

Resposta ao começar: "Foco de 50 minutos, até as 15h40. Seguro meus avisos até lá; seus lembretes continuam valendo."

### 6.2 Durante o foco

- **Segura**: falas e textos do vigia do PC (`_pc_watch_said`), avisos de compromisso (`EventReminders.due`), resumo pós-jogo do vigia e a frase do modo jogo automático. Tudo vai para uma lista do foco, em ordem, sem duplicar.
- **Não segura**: lembretes (decisão 1), respostas a qualquer coisa que o usuário pedir, a fila de lembretes atrasados.
- O Therion continua respondendo normalmente.
- Foco e modo jogo podem estar ligados juntos.
- Fechar o Therion durante o foco: o estado fica em `%LOCALAPPDATA%\Therion\foco.json` (`start`, `minutes`, `phase`, `held`). Ao reabrir antes do fim → retoma o tempo e a orbe. Depois do fim → "Seu foco terminou às 15h40 enquanto eu estava fechado." + tempo do dia (sem contagem de e-mails nem oferta de pausa).

### 6.3 Fim do foco

Uma fala só, nesta ordem, cada parte só se tiver conteúdo:

1. Tempo: "Foco de 50 minutos concluído. Hoje são 1 hora e 40 de foco."
2. E-mails: "Chegaram 6 e-mails, 2 importantes: Fulano, sobre Prova de cálculo; Sicrano, sobre Entrega." (até 3 importantes, só remetente e assunto). Nenhum: "Nenhum e-mail novo."
3. Avisos segurados: "Enquanto você focava: o disco C ficou com 3 GB; a reunião das 15h começou." (as próprias frases, encurtadas; mais de 3 → "e mais N avisos", lista completa escrita na conversa).
4. Pausa: "Que tal 10 minutos de pausa?" — oferta vale 2 min para a próxima frase. "sim"/"pode" → pausa de `focus.pause` (padrão 10) min. "não" → "Tudo bem." Outra frase → a oferta some.

Fim da pausa: "Pausa acabou. Mais 50 minutos de foco?" (mesma oferta de 2 min; "sim" começa outro foco com a última duração).

Na tela: a mesma fala escrita, mais a lista completa dos avisos segurados.

No jogo em tela cheia ou com modo jogo ligado, o fim do foco e o fim da pausa **falam igual ao lembrete**, com a oferta de pausa por voz (decisão do usuário, 18/11).

Aviso do vigia segurado que vinha com oferta de limpeza (`pc_cleanup.offer`): no resumo sai só a frase, **sem rearmar a oferta**. O "sim" depois do fim do foco pertence só à pausa; para limpar, o usuário diz "libera espaço" (já existe). Regra geral: só uma oferta pendente por vez é dona do "sim".

Se o Therion estiver ocupado quando o foco acabar: a fala espera ficar livre (§5.4). A orbe sai do modo foco na hora certa, mesmo com a fala esperando.

**E-mails** — numa thread, nunca na janela:
- Só se o Gmail estiver conectado (`host._mailbox.identity()` não nulo); senão pula a parte 2 sem dizer nada.
- `in:inbox after:<início do foco, em s>` contando só ids (como o miolo de `briefing.mail_since`, `limit=500`) e `in:inbox is:important after:<início>` com `metadata` de até 3 (remetente e assunto). Não abre corpo de e-mail.
- Usa `box.io_lock` e um `CancelToken` próprio; prazo de 10 s. Falha ou prazo → "Não consegui contar os e-mails agora." e o resto da fala sai normalmente.
- Não mexe no marco da saudação (`BriefingMarker`).

**Histórico do dia** — `foco.json` guarda `{"days": {"2026-11-18": 100}}` em minutos, 30 dias (os mais antigos saem). Foco encerrado antes conta o tempo real. Pausa não conta.

### 6.4 A fala dos avisos

`SpeechOutput.speak(text)` chama `stop()` e corta o que estiver tocando. Por isso toda fala que nasce sozinha (lembrete, fim do foco, fim da pausa) passa por uma única porta na janela — `_speak_when_free(text)` — que enfileira e só chama `speak` quando o Therion está livre (§5.4). Os avisos de agenda e do vigia, hoje falados direto, passam a usar a mesma porta (corrige de quebra o mesmo risco que eles já têm).

## 7. Visual — modelo E nas duas orbes

Fora do foco e da pausa: nada muda.

Durante foco ou pausa, por cima da Orbe HUD atual (esfera de pontos, órbitas, moldura, marquinhas, tracejado e arcos **intactos**):

- **Número no centro**: minutos que faltam (`ceil(restante/60)`), fonte Space Grotesk/sistema 600, tamanho ≈ 0,9·R (ajustar no print), centrado no núcleo. Atrás dele um disco escuro suave (preto com alfa ≈ 0,5, raio ≈ 0,55·R) para ler sobre o núcleo brilhante. No último minuto mostra os segundos ("45") — escolha do desenho, ver §10.
- **Arco de progresso por fora da moldura**: círculo fino, começa cheio no topo (12h) e esvazia no sentido do relógio conforme o tempo passa. Raio ≈ 1,30·Rf (as marcas fixas da moldura vão até 1,22·Rf). Traço 1,5 px na mini, 2 px na grande (em `unit`), ponta redonda, com uma trilha apagada (alfa 0,12) mostrando o caminho todo.
- **Cores**: foco = ciano da moldura (`FRAME`, 120,215,232); últimos 5 min = âmbar (`AMBER`) com pulso lento (0,6–1,0 de alfa, ~1,1 s); pausa = verde (≈ 140,230,170); a pausa esvazia igual.
- **Fim**: ao zerar, o número some e o arco dá um brilho curto (~600 ms) e se apaga. Sem som novo.
- **Orbe grande**: o rótulo de estado embaixo continua mostrando o estado ("EM REPOUSO", "OUVINDO"…). O número e o arco convivem com qualquer estado.
- **Mini orbe** (110 px, sem rótulo): o arco não pode ser cortado nas bordas. Hoje `hud_layout` põe o centro em 0,44·altura e as marcas já chegam a ~1,7 px da borda de cima; o arco por fora não cabe. O construtor escolhe entre centralizar o desenho na mini (cy = metade) ou crescer a mini só o necessário, conferindo no print que nada encosta na borda.
- **Modo reduzido / tela cheia** (`renderer.reduced`): o número atualiza; o pulso âmbar fica fixo (sem animação).
- **Custo**: o número muda 1 vez por minuto e o arco é um `drawArc`; a mini orbe continua a 10 quadros/s parada. Medir a CPU da mini orbe com foco (hoje 4,2% de um núcleo) — não pode passar de ~5%.

Onde mexe:
- `interface/hud_frame.py`: nova função `paint_focus(painter, layout, focus, unit)` (dados puros: `FocusLook(fraction, label, color, pulse)`), chamada logo depois de `paint_hud_frame` no `OrbGL`.
- `interface/orb_renderer.py`: `OrbGL.set_focus(look | None)`; a imagem da moldura (`reach = 1.25*lay.Rf`) cresce para caber o arco quando houver foco.
- `interface/mini_orb.py` e `interface/constellation.py`: repassam o foco ao renderizador.
- Prints para o usuário conferir: `scripts/orb_snapshot.py` com foco em 50, 3 e 0,7 min e na pausa, nas duas orbes (prints ficam em `F:\Therion\tmp\`, nunca no repositório).

## 8. Onde cada parte mora

| Peça | Arquivo | Thread |
|---|---|---|
| Entender frases de lembrete e de foco, calcular próxima data, montar respostas | `core/voice_reminders.py`, `core/focus.py` (novos, sem Qt) | qualquer |
| Depósito de lembretes, estado e histórico do foco | os mesmos módulos (`ReminderStore`, `FocusStore`) | trava própria |
| Gancho do comando | `core/orchestrator.py`, no mesmo bloco do modo jogo/`local_reports` (~linha 2417), devolvendo `ui_action='reminders'` ou `ui_action='focus'` com `ui_payload` | worker |
| Não deixar o agente engolir a frase | `agent/host.py`, mesma lista de `report_request`/`cleanup_wanted` (~linha 401) | worker |
| Perguntas curtas pendentes ("Quando?", "Qual deles?", "sim" da pausa, "sim" do cancelar todos) | estado no host com prazo de 2 min, como `_pc_cleanup_offer` | worker |
| Disparo na hora, fila de fala, segurar avisos, resumo, e-mails em thread | `interface/desktop.py` (`QTimer.singleShot` até o próximo vencimento + tique de 30 s existente como reserva; `_speak_when_free`) | Qt |
| Visual | `hud_frame.py`, `orb_renderer.py`, `mini_orb.py`, `constellation.py` | Qt |
| Configuração | `focus.minutes` (50), `focus.pause` (10) em `config.json`; sem chave para ligar/desligar (só acontece quando o usuário pede) | — |

**Só com a janela**: lembretes e foco existem só quando o orchestrator roda dentro da janela (`interface/desktop.py`). Pelo terminal (`interface/cli.py`, que ignora `ui_action`) essas frases respondem "Lembretes e foco funcionam com a janela do Therion aberta." e não gravam nada. Assim a trava de processo basta. Como reserva barata, o tique de 30 s confere a data de modificação de `lembretes.json` e relê se mudou.

O `ui_action='reminders'` avisa a janela para reler o depósito e rearmar o relógio; o `ui_action='focus'` leva `{"phase": "focus"|"pause"|"off", "minutes": n, "start": iso}`.

## 9. Testes

- `tests/test_voice_reminders.py`: cada frase de §5.1/§5.3 (uma vez, relativo, dia, repetição, ordem livre, sem quando, sem o quê, ambígua), regra "às 6", hora passada, próxima ocorrência de cada repetição (inclusive virada de semana e de mês), atrasados ao abrir (uma vez, repetido, > 7 dias), adiar, cancelar (um, vários, todos), limite de 50, arquivo corrompido. Relógio sempre injetado.
- `tests/test_focus.py`: começar/esticar/encerrar/limites, segurar e soltar avisos, montagem da fala do fim (cada parte presente ou ausente), oferta de pausa e de novo foco, histórico do dia e corte de 30 dias, retomada depois de fechar.
- Janela (com relógio falso, padrão de `test_reminders`/`test_pc_watch`): lembrete espera fala/escuta/pedido e depois fala; fura o foco; fala com tela cheia e modo jogo; vigia e agenda seguram durante o foco; vários juntos numa fala; atraso ao abrir; e-mails do fim com caixa falsa (conectado, desconectado, erro, prazo).
- Visual: `paint_focus` em imagem (pixels do arco dentro da área, nada nas bordas da mini), `set_focus(None)` não desenha nada.
- `tests/frases_reais.txt`: frases novas com a rota, e frases de memória que não podem mudar.
- Suíte inteira por `scripts/test-v4.py` (isolada). Comparar com a última: 3569 ok, 2 skip, 1 warning.

## 10. Decisões minhas (o usuário pode trocar)

- Duração padrão 50 min de foco e 10 de pausa; limites 5–180.
- "daqui a pouco" = 10 min.
- Respostas por extenso com dia e hora para o usuário pegar erro de entendimento na hora, em vez de pedir confirmação.
- Só "cancela todos" pede "sim".
- Último minuto do foco mostra segundos.
- Avisos de agenda e do vigia passam pela mesma porta de fala (`_speak_when_free`), o que muda um pouco o comportamento atual deles: esperam a fala em andamento acabar em vez de cortá-la.
- Nada do vigia fura o foco, nem a temperatura alta da placa (é aviso, não emergência; fica na lista do fim).
- Lembrete atrasado há mais de 7 dias entra só na contagem.
- Oferta de limpeza do vigia segurada no foco não é rearmada; o "sim" do fim do foco é da pausa.
- Lembretes e foco só pela janela; o terminal responde que precisa dela.

## 11. Deixado para o construtor

- Formato exato das expressões regulares e ordem dos ganchos no orchestrator (respeitando a fronteira com a memória de §5.1).
- Centralizar o desenho da mini orbe ou crescer o widget (§7), conferindo no print.
- Tamanho final da fonte e do disco escuro do número, conferido no print das duas orbes.
- Como detectar "fala tocando / microfone ativo" para `_speak_when_free` com o que `SpeechOutput` e o pipeline de voz já expõem (`is_quiescent`, estado da orbe).
- Detalhe de como acordar de suspensão é percebido (diferença entre relógio de parede e o tique).
