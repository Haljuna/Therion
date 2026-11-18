# Modo foco e lembretes por voz — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** lembretes falados (de uma vez e que repetem) e modo foco com tempo na orbe, resumo no fim e oferta de pausa, tudo por rota local sem o modelo.

**Architecture:** dois módulos puros novos em `therion/core/` (entendimento das frases, depósitos JSON, cálculo de datas, textos das respostas) chamados pelo gancho local do `orchestrator.py`; a janela (`interface/desktop.py`) dispara na hora com `QTimer`, segura os avisos do foco, fala por uma porta única que nunca corta outra fala, e repassa o tempo para as duas orbes, que desenham o modelo E por cima da moldura HUD.

**Tech Stack:** Python 3.14, PySide6 (QTimer, QPainter sobre `OrbGL`), pytest via `scripts/test-v4.py`; sem dependência nova.

**Spec:** `docs/superpowers/specs/2026-11-18-modo-foco-e-lembretes-design.md` (ler inteiro antes de qualquer tarefa; as seções citadas abaixo como §N são dele).

## Global Constraints

- Árvore `F:\Therion\foco-wt`, branch `foco-lembretes`. Nunca commitar no master, nunca `git push`.
- Rodar testes só por `.venv\Scripts\python.exe scripts\test-v4.py <arquivos> -q` (isola APPDATA/LOCALAPPDATA). Python do venv: `F:\Therion\app\.venv\Scripts\python.exe` se a árvore não tiver `.venv` próprio.
- Editar arquivos existentes só com a ferramenta Edit (o repo mistura LF e CRLF; `Path.write_text` gera diff gigante).
- Repositório **público**: nenhum texto pessoal real em teste, frase ou commit; exemplos inventados ("tirar a roupa da máquina", "Fulano").
- Textos ao usuário em português, tratando por "você" nas frases novas, exatamente como no spec (§5.2, §5.3, §5.4, §5.5, §6.1, §6.3).
- Arquivos de dados: `%LOCALAPPDATA%\Therion\lembretes.json` e `%LOCALAPPDATA%\Therion\foco.json`, gravação atômica (temporário + `fsync` + `os.replace`).
- Limites: lembrete ≤ 200 caracteres, ≤ 50 ativos; foco 5–180 min; padrões `focus.minutes=50`, `focus.pause=10`; ofertas/perguntas pendentes valem 120 s e só para a próxima frase; "daqui a pouco" = 10 min; adiar vale até 5 min após o toque; atrasado > 2 min = "passou da hora"; > 7 dias = só contagem; histórico 30 dias.
- O nome `focus` já existe no `OrbGL` (`focus_rect`, `_focus()` = área de desenho). O tempo na orbe se chama **timer**: `TimerLook`, `paint_timer`, `OrbGL.set_timer`.
- Commits terminam com `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **"Me lembra que eu tenho prova amanhã"** (memória, sem hora de lembrete) não pode virar lembrete, e "lembre que…" continua indo para a memória — teste na Tarefa 3.
2. **Lembrete vencendo enquanto o Therion fala ou ouve** não pode cortar a fala nem a escuta; sai logo depois — teste na Tarefa 5.
3. **"às 12"/"meio-dia"/"às 0"** e "às 6" perto da meia-noite (23h50 → 6h de amanhã) — testes na Tarefa 1.
4. **PC dormiu 3 h com lembrete de 18h e um diário de 8h** ao acordar: uma frase "passou da hora" por lembrete, o diário reagendado para o próximo dia, nunca repetido — teste na Tarefa 2.
5. **Foco terminando com o Gmail desconectado ou lento** (> 10 s): o resto do resumo sai normal — teste na Tarefa 6.

---

### Task 1: Entender quando e o quê (parser de lembrete)

**Files:**
- Create: `therion/core/voice_reminders.py`
- Test: `tests/test_voice_reminders.py`

**Interfaces:**
- Consumes: `therion.context.language.control`; `therion.calendar.dialogue.parse_day(raw, now) -> date`, `parse_time(raw) -> (hour, minute)` (levanta `CalendarError`); `therion.calendar.dialogue.normalize_spoken_fields`.
- Produces:
  - `@dataclass(frozen=True) class Repeat: days: tuple[int, ...]; time: str  # "HH:MM", days = weekday() 0=segunda`
  - `@dataclass(frozen=True) class Parsed: kind: str; text: str | None = None; due: datetime | None = None; repeat: Repeat | None = None; hour: int | None = None; question: str | None = None`
    `kind` ∈ `'create' | 'need_when' | 'need_what' | 'need_period' | 'invalid'`. `need_period` guarda `text`, `repeat.days` e `hour` (1–11) para a pergunta "Seis da manhã ou da tarde?". `invalid` traz em `question` a mensagem do `CalendarError`.
  - `parse_reminder(command: str, now: datetime) -> Parsed | None` — `None` quando a frase não tem gatilho de lembrete (§5.1) ou é memória ("me lembra que X" sem expressão de tempo).
  - `next_due(repeat: Repeat, after: datetime) -> datetime` — primeira ocorrência estritamente depois de `after`.

- [ ] **Step 1: Escrever os testes que falham** — `now = datetime(2026, 11, 18, 14, 0)` (quarta). Cada linha é um `assert` num teste parametrizado `test_parses(phrase, kind, text, due)`:
  - `"me lembra de tirar a roupa da máquina em 40 minutos"` → create, `"tirar a roupa da máquina"`, 14:40
  - `"me lembre às 18h de ligar pro João"` → create, `"ligar pro João"`, 18:00
  - `"me avisa daqui a uma hora e meia para sair"` → create, `"sair"`, 15:30
  - `"me lembra de beber água daqui a pouco"` → 14:10
  - `"me lembra amanhã às 9 de levar o carregador"` → 2026-11-19 09:00
  - `"me lembra às 6 de ligar"` → 18:00 hoje; com `now=23:50` → 06:00 amanhã
  - `"me lembra às 13 de ligar"` com `now=14:00` → amanhã 13:00
  - `"me lembra ao meio-dia de almoçar"` → amanhã 12:00; `"à meia-noite"` → 2026-11-19 00:00
  - `"lembrete: pagar o boleto sexta às 10"` → 2026-11-20 10:00
  - `"me lembra de pagar o boleto"` → need_when; `"me lembra em 10 minutos"` → need_what
  - `"me lembra que eu tenho prova amanhã"` → `None`; `"lembre que meu carro é prata"` → `None`
  - `"me lembra às dez seis de sair"` → invalid com a mensagem do `CalendarError`
  - `"me lembra de " + "x"*201 + " em 5 minutos"` → invalid, `question == 'O lembrete pode ter até 200 caracteres.'`
  - Repetição (`test_repeats`): `"me lembra todo dia às 8h de tomar remédio"` → `Repeat((0,…,6), '08:00')`, due 2026-11-19 08:00; `"toda segunda e quarta às 19h"` → `(0, 2)`; `"às terças e quintas às 19h"` → `(1, 3)`; `"dias úteis às 9h"` e `"de segunda a sexta às 9h"` → `(0,1,2,3,4)`; `"fim de semana às 10h"` → `(5, 6)`; `"todo dia de tomar remédio"` → need_when; `"todo dia às 6 de tomar remédio"` → need_period com `hour == 6`; `"todo dia às 6 da manhã…"` → create `'06:00'`.
  - `test_next_due`: diário depois de 23:59 vira o dia seguinte; `(0,)` numa quarta → próxima segunda; virada de mês (2026-11-30 → 2026-12-01).

- [ ] **Step 2: Rodar e ver falhar** — `scripts/test-v4.py tests/test_voice_reminders.py -q` → ImportError.

- [ ] **Step 3: Implementar `parse_reminder` e `next_due`** em `therion/core/voice_reminders.py`. Normalizar com `control()`; achar o gatilho; extrair primeiro a repetição, depois o tempo relativo (`em|daqui a` + número falado ou dígito + `minutos|horas` + `e meia|e N`), depois `[dia] às H`. Hora 1–11 sem período: uma vez → a mais próxima no futuro entre H e H+12 (§5.1); repete → `need_period`. O texto é o que sobra, sem `de|para|pra|que` iniciais e sem pontuação final, com a capitalização original da frase.

- [ ] **Step 4: Rodar e ver passar** — mesmo comando, PASS.

- [ ] **Step 5: Commit** — `feat(lembretes): entende quando e o quê das frases de lembrete`.

---

### Task 2: Depósito de lembretes, vencidos e atrasados

**Files:**
- Modify: `therion/core/voice_reminders.py`
- Test: `tests/test_voice_reminders.py`

**Interfaces:**
- Consumes: `Repeat`, `next_due` (Task 1).
- Produces:
  - `@dataclass(frozen=True) class Reminder: id: str; text: str; due: datetime; repeat: Repeat | None; created: datetime`
  - `class ReminderStore(path: Path | None = None)` — padrão `Path(os.environ['LOCALAPPDATA'])/'Therion'/'lembretes.json'`; trava `threading.Lock` por instância e uma instância compartilhada `store()` (módulo) para orchestrator e janela.
    - `items() -> list[Reminder]` ordenado por `due`
    - `add(text, due, repeat, now) -> Reminder` (levanta `ValueError('Você já tem 50 lembretes; cancele algum antes.')`)
    - `remove(ids: Iterable[str]) -> list[Reminder]`
    - `take_due(now) -> tuple[list[Reminder], list[Reminder], int]` = (na hora, atrasados > 2 min e ≤ 7 dias, quantos > 7 dias); remove os de uma vez, reagenda os que repetem com `next_due(repeat, now)`; um que repete conta uma vez só.
    - `next_time() -> datetime | None`
    - `mtime() -> float | None`; `reload()`
    - `broken_notice: str | None` — preenchido uma vez quando o arquivo estava corrompido (renomeado para `lembretes.json.bad-AAAAMMDD-HHMMSS`), lido e zerado pela janela.
  - `due_message(reminders: list[Reminder]) -> str` — `"Lembrete: X."` / `"Dois lembretes: X; Y."` (números por extenso até dez, depois dígitos).
  - `late_message(late: list[Reminder], old: int) -> str | None` — §5.5: 1 a 3 com hora `HH:MM`; mais de 3 → `"Passaram N lembretes enquanto eu estava fechado: A, B, C e mais K."`; `old` > 0 soma `"e mais N antigos"`.

- [ ] **Step 1: Testes que falham** — `tmp_path` como depósito, relógio injetado:
  - `test_roundtrip_and_atomic_write`: add 2, nova instância lê os 2 com os mesmos campos; nenhum `*.tmp` sobra.
  - `test_limit_50`: o 51º levanta `ValueError` com o texto exato.
  - `test_take_due_on_time_removes_once_and_reschedules_repeat`: de uma vez às 18:00 + diário 08:00; `take_due(18:00:30)` → (`[18h]`, `[]`, 0); diário com due 2026-11-19 08:00 intocado.
  - `test_sleep_three_hours` (Review Focus 4): itens 18:00 de uma vez e diário 08:00 com due 18/11 08:00; `take_due(2026-11-18 21:00)` → atrasados = os dois, cada um uma vez; diário com due 2026-11-19 08:00.
  - `test_week_closed_daily_said_once_old_counted`: diário perdido 7 vezes → aparece 1 vez; de uma vez vencido há 8 dias → conta em `old`.
  - `test_corrupt_file_is_kept_and_reported`: arquivo com `{x` → `items() == []`, existe `lembretes.json.bad-*`, `broken_notice` começa com `"Não consegui ler seus lembretes antigos"`.
  - `test_messages`: `due_message` de 1 e 2; `late_message` de 1, 4 e com `old=2`, textos exatos do §5.5.

- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar** o depósito e as duas mensagens; JSON no formato exato do §5.6 (`version: 1`, datas ISO locais sem fuso, `id` = `'r-' + secrets.token_hex(2)` único).
- [ ] **Step 4: Rodar e ver passar.**
- [ ] **Step 5: Commit** — `feat(lembretes): depósito local com vencidos, atrasados e repetição`.

---

### Task 3: Frases de lembrete no Therion (criar, perguntar, listar, cancelar, adiar)

**Files:**
- Modify: `therion/core/voice_reminders.py`
- Modify: `therion/core/orchestrator.py:2416-2431` (bloco do `local_report`/modo jogo)
- Modify: `therion/agent/host.py:400-410` (lista que devolve `None` para rotas locais)
- Modify: `tests/frases_reais.txt` (fora do git) e `tests/test_frases_reais.py:24` (`route()` ganha `'lembrete'` e `'foco'` antes do `IntentRecognizer`)
- Test: `tests/test_voice_reminders.py`, `tests/test_frases_reais.py`

**Interfaces:**
- Consumes: Tasks 1–2.
- Produces:
  - `reminder_request(command: str, host) -> bool` — sem efeito; a frase é desta rota? (gatilho de criar/listar/cancelar/adiar, ou resposta a uma pergunta pendente válida).
  - `answer(command: str, host, now: datetime | None = None) -> str | None` — resposta pronta ou `None`. Lê e consome as pendências de `host._reminder_pending = (deadline_monotonic, kind, data)`, `kind` ∈ `'when' | 'what' | 'period' | 'pick' | 'cancel_all'`. Depois de criar/cancelar/adiar marca `host._reminders_changed = True`.
  - `snooze_window(host, reminder_text: str)` — chamada pela janela quando um lembrete toca; guarda `host._reminder_snooze = (deadline_monotonic_5min, text)`.
  - `host.desktop_timers: bool` — a janela põe `True` em `MainWindow.__init__`; sem isso `answer` devolve `'Lembretes e foco funcionam com a janela do Therion aberta.'` e não grava nada.

- [ ] **Step 1: Testes que falham** (host = `SimpleNamespace(desktop_timers=True)` e depósito em `tmp_path`):
  - criar → texto exato `"Combinado: hoje às 18h, tirar a roupa da máquina."`, relativo `"Combinado: em 40 minutos, às 14h40, tirar a roupa da máquina."`, repetição `"Combinado: todo dia às 8h, tomar remédio. O próximo é amanhã."`
  - pergunta e resposta: `"me lembra de pagar o boleto"` → `"Quando eu te lembro?"`; `"às 18h"` → cria; depois de 121 s o `"às 18h"` não é desta rota.
  - `"me lembra em 10 minutos"` → `"Te lembro do quê?"`; `"pegar a encomenda"` → cria.
  - `"todo dia às 6 tomar remédio"` → `"Seis da manhã ou da tarde?"`; `"da manhã"` → `'06:00'`; `"tarde"` → `'18:00'`; `"18"` → `'18:00'`.
  - listar: nenhum → `"Nenhum lembrete marcado."`; três → começa `"Você tem 3 lembretes: "`.
  - cancelar: um candidato (`"cancela o lembrete da roupa"`) → `"Cancelei: tirar a roupa da máquina (hoje às 18h)."`; dois → `"Qual deles? 1) … 2) …"` e `"2"` cancela o segundo; nenhum → `"Não achei esse lembrete."`; `"cancela todos os lembretes"` → `"Cancelo os 3 lembretes?"`, `"sim"` → `"Cancelei os 3 lembretes."`, `"não"` → `"Tudo bem."`.
  - adiar: com `snooze_window(host, 'sair')`, `"adia 10 minutos"` → cria de uma vez +10 min; depois de 5 min não é desta rota.
  - `desktop_timers=False` → mensagem exata do terminal, depósito vazio.
  - Review Focus 1: `reminder_request("me lembra que eu tenho prova amanhã", host) is False`; `"lembre que meu carro é prata"` → False.
  - `test_frases_reais.py`: `route()` devolve `'lembrete'` quando `reminder_request` é True (host falso com `desktop_timers=True`). Acrescentar ao banco local: as frases de criação da Task 1 `=> lembrete` e `me lembra que eu tenho prova amanhã => <rota atual dela>` (rodar `route()` antes da mudança para saber a rota atual).

- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar `reminder_request`, `answer`, `snooze_window`.** Cancelar por texto: maior quantidade de palavras de ≥ 4 letras em comum (sem acento) ou mesma `HH:MM`. Fala com `spoken_time` só nos campos `speech_message` se o orchestrator já separa tela e fala; senão a mesma string.
- [ ] **Step 4: Ligar no orchestrator e no host.** No bloco de `orchestrator.py:2417`, antes do `pc_cleanup`: `reminder = voice_reminders.answer(command, self)`; com resposta → `OrchestrationResult(status='success', message=reminder, ui_action='reminders' if self.__dict__.pop('_reminders_changed', False) else None)`. Em `host.py:401` somar `or reminder_request(syntax.command, self)` na lista que devolve `None`. Uma pendência de outra rota (`_pc_cleanup_offer`) fica intacta.
- [ ] **Step 5: Rodar e ver passar** — `tests/test_voice_reminders.py tests/test_frases_reais.py tests/test_local_reports.py tests/test_pc_cleanup.py -q`.
- [ ] **Step 6: Commit** — `feat(lembretes): criar, perguntar, listar, cancelar e adiar por voz` (sem `frases_reais.txt`, que fica fora do git).

---

### Task 4: Núcleo do modo foco

**Files:**
- Create: `therion/core/focus.py`
- Modify: `therion/core/orchestrator.py` (mesmo bloco da Task 3), `therion/agent/host.py` (mesma lista)
- Modify: `therion/config/local.py` (`_validate_config` aceita `focus: {minutes: int 5–180, pause: int 1–60}`)
- Test: `tests/test_focus.py`

**Interfaces:**
- Consumes: `control`; `reminder_request`/padrão de pendência da Task 3 (`host._focus_offer = (deadline, kind)`, `kind` ∈ `'pause' | 'again'`).
- Produces:
  - `@dataclass class FocusState: phase: str  # 'focus' | 'pause' | 'off'; start: datetime | None; minutes: int; held: list[str]`
  - `class FocusStore(path=None)` — `%LOCALAPPDATA%\Therion\foco.json` = `{"version": 1, "state": {...}, "days": {"AAAA-MM-DD": minutos}}`; `state() -> FocusState`, `save(state)`, `add_minutes(day: date, minutes: int)`, `today(day) -> int`; corta dias > 30.
  - `focus_request(command) -> tuple | None` — `('start', minutos|None)`, `('extend', minutos)`, `('stop',)`, `('left',)`, `('pause', minutos|None)`, `('stop_pause',)`.
  - `answer(command, host, now=None) -> tuple[str, dict] | None` — texto + `ui_payload` `{"phase": ..., "minutes": n, "start": iso, "ended": bool}`; resolve também o "sim/não" das ofertas (`offer(host, kind)`).
  - `offer(host, kind: str)` — guarda a oferta por 120 s; só uma pendência dona do "sim": zera `host._pc_cleanup_offer` e `host._reminder_pending`.
  - `ended_text(minutes_done: int, today_total: int, mail: dict | None, held: list[str], suggest_pause: int | None) -> str` — monta §6.3 na ordem fixa; `mail` = `{'count': int, 'important': [(remetente, assunto)]}` ou `{'error': True}` ou `None` (Gmail desconectado → parte omitida).
  - `remaining(state, now) -> float` (segundos, ≥ 0) e `end_at(state) -> datetime`.

- [ ] **Step 1: Testes que falham:**
  - `"foco"` → start 50; `"foco de uma hora e meia"` → 90; `"vou focar 30 minutos"` → 30; `"foco 200 minutos"` → `"Dá para focar de 5 a 180 minutos."`
  - resposta ao começar às 14:50 → `"Foco de 50 minutos, até as 15h40. Seguro meus avisos até lá; seus lembretes continuam valendo."`
  - `"foco"` com foco ligado → `"Você já está em foco; faltam 32 minutos."`; `"quanto falta do foco?"` → `"Faltam 32 minutos de foco."`; `"mais 10 minutos"` estica e respeita 180.
  - `ended_text` com todas as partes e cada parte ausente; textos exatos do §6.3 (`"Foco de 50 minutos concluído. Hoje são 1 hora e 40 de foco."`, `"Chegaram 6 e-mails, 2 importantes: Fulano, sobre Prova; Sicrano, sobre Entrega."`, `"Nenhum e-mail novo."`, `"Não consegui contar os e-mails agora."`, `"Enquanto você focava: …"`, `"e mais 2 avisos"`, `"Que tal 10 minutos de pausa?"`).
  - ofertas: `offer(host,'pause')` + `"sim"` → pausa de 10; `"não"` → `"Tudo bem."`; outra frase → oferta some; depois de 121 s o "sim" não é desta rota; `offer` zera `_pc_cleanup_offer`.
  - histórico: dois focos no dia somam; dia de 31 dias atrás sai.
  - `desktop_timers=False` → mensagem do terminal da Task 3.
- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar** `focus.py` e ligar no orchestrator (`ui_action='focus'`, `ui_payload` do `answer`) e no host.
- [ ] **Step 4: Rodar e ver passar** — `tests/test_focus.py tests/test_voice_reminders.py tests/test_frases_reais.py tests/test_config.py -q` (com um caso novo em `test_config.py`: `focus.minutes=200` é recusado, `focus` ausente é aceito).
- [ ] **Step 5: Commit** — `feat(foco): comandos, estado salvo e texto do fim do foco`.

---

### Task 5: Janela — porta de fala e disparo dos lembretes

**Files:**
- Modify: `therion/interface/desktop.py` (`__init__` ~linha 338-365, `_poll_reminders` ~1081, `_poll_pc_watch` ~1104, `_apply_command_result` ~1330, mudança de estado da orbe ~1890)
- Test: `tests/test_desktop_reminders.py` (novo; reaproveitar `make_window`/`close` de `tests/test_reminders.py`, importando)

**Interfaces:**
- Consumes: `voice_reminders.store()`, `take_due`, `next_time`, `mtime`, `reload`, `due_message`, `late_message`, `broken_notice`, `snooze_window` (Tasks 2–3).
- Produces (usados pela Task 6):
  - `MainWindow._speak_when_free(text: str, *, write: bool = True) -> None` — escreve (`_append('Therion', text)`) na hora e fala só quando livre; fila `self._spoken_queue`.
  - `MainWindow._therion_free() -> bool` = `not self._processing and self._pending_plan is None and not self._voice_jobs_pending() and self._orbe_state not in ('listening','transcribing','awaiting_confirmation','clarification')`.
  - `MainWindow._drain_speech()` — chamado no tique de 30 s, ao fim de cada comando e em cada mudança de estado da orbe.
  - `MainWindow._arm_reminder_timer()` — `QTimer` `singleShot` (`self._reminder_shot`) até `next_time()`; rearmado depois de `ui_action == 'reminders'`, de cada disparo e do tique.

- [ ] **Step 1: Testes que falham** (relógio por `monkeypatch` de `voice_reminders`/`desktop` `datetime.now` ou parâmetro `now` injetável no método `_fire_reminders(now)`):
  - `test_reminder_waits_for_speech_then_speaks` (Review Focus 2): `_voice_jobs_pending` → True; `_fire_reminders(18:00)` escreve mas `speak` não é chamado; vira False, `_drain_speech()` → `speak('Lembrete: tirar a roupa da máquina.')`.
  - `test_reminder_speaks_in_full_screen_and_game_mode`: `do_not_disturb` → True e `_game_forced = True` → fala.
  - `test_two_due_together_one_sentence`.
  - `test_late_on_open`: depósito com item de ontem antes de abrir a janela → primeira fala é o `late_message`.
  - `test_shot_timer_armed_to_next_due`: após `ui_action='reminders'`, `_reminder_shot.remainingTime()` ≈ ms até o próximo.
  - `test_tick_rereads_file_when_mtime_changes`.
  - `test_broken_file_notice_said_once`.
  - `test_fire_opens_snooze_window` (`host._reminder_snooze` preenchido).
  - `test_event_warning_no_longer_cuts_speech`: o aviso de agenda existente, com fala tocando, espera (atualizar `tests/test_reminders.py::test_window_speaks_the_warning_only_when_free` se ele quebrar só por passar pela porta — o comportamento de segurar em tela cheia continua igual).
- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar.** `MainWindow.__init__`: `self._orchestrator.desktop_timers = True`; `_reminder_timer` passa a rodar sempre (lembretes e foco não têm chave de config); ao fim do `__init__`, `QTimer.singleShot(0, self._fire_reminders)` para os atrasados. O vigia (`_poll_pc_watch`) e a agenda (`_poll_reminders`) trocam `self._speech_output.speak(message)` por `_speak_when_free(message, write=False)` mantendo a regra de "quieto" do vigia (no jogo só escreve).
- [ ] **Step 4: Rodar e ver passar** — `tests/test_desktop_reminders.py tests/test_reminders.py tests/test_pc_watch.py tests/test_mini_orb.py -q`.
- [ ] **Step 5: Commit** — `feat(lembretes): a janela avisa na hora sem cortar a fala`.

---

### Task 6: Janela — ciclo do foco, avisos segurados, e-mails e pausa

**Files:**
- Modify: `therion/interface/desktop.py`
- Modify: `therion/core/focus.py` (`focus_mail`)
- Test: `tests/test_desktop_focus.py` (novo), `tests/test_focus.py`

**Interfaces:**
- Consumes: Task 4 (`FocusStore`, `answer` payload, `ended_text`, `offer`, `remaining`, `end_at`), Task 5 (`_speak_when_free`, `_drain_speech`).
- Produces:
  - `focus_mail(host, start: datetime, token, timeout: float = 10.) -> dict | None` em `core/focus.py` — `None` sem conta (`host._mailbox.identity() is None`); `{'count', 'important'}` com `in:inbox after:<s>` (só ids, `limit=500`, como o miolo de `briefing.mail_since`) e `in:inbox is:important after:<s>` com `adapter.metadata` de até 3 (remetente e assunto); `{'error': True}` em `OSError/ValueError/TimeoutError/KeyError/Cancelled` ou prazo. Usa `box.io_lock`. Não toca no `BriefingMarker`.
  - `MainWindow._focus_hold(message: str) -> bool` — True e guarda quando foco ligado (só os avisos do vigia, da agenda, do resumo pós-jogo e do modo jogo automático; nunca lembrete); a oferta de limpeza do vigia segurada **não** chama `pc_cleanup.offer`.
  - `MainWindow._apply_focus(payload: dict)` e `MainWindow._timer_look() -> TimerLook | None` (consumido pela Task 7; antes da Task 7 retorna `None` sem desenhar).
  - `MainWindow._focus_shot` — `QTimer` `singleShot` até `end_at(state)`.

- [ ] **Step 1: Testes que falham** (`focus_mail` com caixa falsa):
  - `test_focus_mail_counts_and_lists_three_important`; `test_focus_mail_without_account_is_none`; `test_focus_mail_timeout_is_error` (Review Focus 5: adapter que dorme 11 s com `timeout=0.2` → `{'error': True}` sem travar).
  - `test_watch_and_event_warnings_held_during_focus_reminder_not`.
  - `test_cleanup_offer_not_rearmed_when_held`: aviso com `cleanup=True` segurado → no fim `host._pc_cleanup_offer` continua `None` e o `"sim"` vai para a pausa.
  - `test_focus_end_speaks_summary_and_offers_pause`: fim com 2 avisos e caixa falsa → `speak` uma vez com o texto do `ended_text`, `host._focus_offer[1] == 'pause'`; com `do_not_disturb` True também fala.
  - `test_focus_end_while_busy_waits_but_orb_leaves_focus_on_time`.
  - `test_pause_end_offers_again`: `"Pausa acabou. Mais 50 minutos de foco?"`.
  - `test_reopen_during_focus_resumes` e `test_reopen_after_end_says_it_ended_while_closed` (`"Seu foco terminou às 15h40 enquanto eu estava fechado."` + total do dia; sem e-mails, sem oferta).
  - `test_stop_early_counts_real_minutes`.
- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar.** A contagem de e-mails roda numa `threading.Thread(daemon=True, name='therion-focus-mail')`; o resultado volta à thread do Qt por `QTimer.singleShot(0, …)` ou sinal, e só então `_speak_when_free(ended_text(...))`. A lista completa de avisos segurados vai escrita na conversa (`_append`) junto do resumo.
- [ ] **Step 4: Rodar e ver passar** — `tests/test_desktop_focus.py tests/test_focus.py tests/test_desktop_reminders.py tests/test_reminders.py tests/test_pc_watch.py -q`.
- [ ] **Step 5: Commit** — `feat(foco): segura avisos, resume no fim com e-mails e oferece pausa`.

---

### Task 7: Visual — modelo E nas duas orbes

**Files:**
- Modify: `therion/interface/hud_frame.py` (nova `TimerLook` e `paint_timer`)
- Modify: `therion/interface/orb_renderer.py` (`OrbGL.set_timer`, área da imagem da moldura em ~linha 256)
- Modify: `therion/interface/mini_orb.py` (`MiniOrb.set_timer`; layout centrado se preciso, §7)
- Modify: `therion/interface/constellation.py` (repasse para a orbe grande)
- Modify: `therion/interface/desktop.py` (`_timer_look` real; chama `set_timer` nas duas a cada tique de 1 s **só** durante foco/pausa — um `QTimer` de 1000 ms ligado e desligado com o foco)
- Modify: `scripts/orb_snapshot.py` (`--timer FRAÇÃO:RÓTULO:fase`, ex. `--timer 0.64:32:focus`, `--mini`)
- Test: `tests/test_hud_frame.py`, `tests/test_orb_renderer.py`, `tests/test_mini_orb.py`

**Interfaces:**
- Consumes: `FRAME`, `AMBER`, `HudLayout` de `hud_style.py`; `remaining`/`FocusState` (Task 4); `_timer_look` (Task 6).
- Produces:
  - `@dataclass(frozen=True) class TimerLook: fraction: float  # 1→0 restante; label: str  # "32" ou "45"; phase: str  # 'focus'|'pause'; warn: bool  # últimos 5 min`
  - `timer_look(state: FocusState, now: datetime) -> TimerLook | None` em `core/focus.py` (sem Qt): `label = str(ceil(restante/60))`, no último minuto os segundos; `warn = phase == 'focus' and restante <= 300`.
  - `paint_timer(painter, layout, look: TimerLook, unit: float, pulse: float) -> None` — arco em `1.30*layout.Rf`, trilha alfa 0,12, progresso do topo no sentido do relógio, traço `1.5*unit` (mini) / `2*unit` (grande) com `Qt.RoundCap`; cor `FRAME` (foco), `AMBER` (`warn`, alfa `pulse`), `(140,230,170)` (pausa); disco escuro alfa 0,5 de raio `0.55*layout.R` e o número centrado em `(cx, cy)`, fonte 600 com altura ≈ `0.9*layout.R`.
  - Ao zerar (`set_timer(None)` vindo de um foco/pausa ativo): o número some e o arco dá um brilho de 600 ms (alfa 1→0, largura ×2) antes de apagar; sem animação quando `reduced`.
  - `OrbGL.set_timer(look: TimerLook | None)` — guarda e pede `update()`; com `look`, `reach` da imagem da moldura vira `1.34*lay.Rf`; pulso âmbar `0.8 + 0.2*sin(2π·t/1.1)`, fixo em 1,0 quando `reduced`.
  - `MiniOrb.set_timer(look | None)`; `ConstellationPanel`/o dono do `OrbGL` grande ganha o mesmo método.

- [ ] **Step 1: Testes que falham:**
  - `test_paint_timer_draws_arc_inside_bounds_mini`: `QImage(110,110)` transparente com o layout que a mini usa → há pixels ciano no raio do arco e nenhum pixel não transparente na borda de 1 px.
  - `test_paint_timer_colors`: foco ciano, `warn` âmbar, pausa verde (amostra de um pixel do arco).
  - `test_set_timer_none_draws_nothing_new`: imagem da moldura igual à de antes do recurso.
  - `test_timer_look_last_minute_shows_seconds` e `test_timer_look_warn_last_five_minutes`.
  - `test_mini_orb_forwards_timer_to_renderer` (renderizador falso).
  - `test_timer_end_flash_lasts_600ms_and_skips_when_reduced`.
- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar.** Se o arco não couber nos 110 px com `hud_layout` (centro em 0,44·altura), a mini passa a desenhar com o centro na metade da altura (só quando `show_label=False`) — conferir que a orbe sem foco continua idêntica por comparação de imagem no teste.
- [ ] **Step 4: Rodar e ver passar** — `tests/test_hud_frame.py tests/test_orb_renderer.py tests/test_mini_orb.py tests/test_mini_orb_lifetime.py tests/test_desktop_focus.py -q`.
- [ ] **Step 5: Prints para o usuário** — `scripts/orb_snapshot.py --timer 1:50:focus`, `0.64:32:focus`, `0.06:3:focus` (âmbar), `0.012:45:focus`, `0.5:5:pause`, cada um com e sem `--mini`, saída em `F:\Therion\tmp\prints-foco\` (nunca no repositório). Olhar cada print: nada cortado, número legível sobre o núcleo.
- [ ] **Step 6: Medir CPU da mini orbe** com foco ligado por 60 s (mesmo método da medição de 18/11, `psutil` sobre o processo do snapshot ou do Therion): ≤ ~5% de um núcleo.
- [ ] **Step 7: Commit** — `feat(foco): minutos no centro e arco de progresso nas duas orbes`.

---

### Task 8: Conferência final

**Files:** nenhum novo.

- [ ] **Step 1: Suíte inteira** — `.venv\Scripts\python.exe scripts\test-v4.py tests -q`. Esperado: 0 falhas; comparar com 3569 ok, 2 skip, 1 warning (falha só no `test_startup_reuse` = instável conhecido: repetir sozinho).
- [ ] **Step 2: Conferir o diff** — `git diff master --stat`: nenhum dos 5 arquivos da voz Edge, nenhum texto pessoal, nenhum print.
- [ ] **Step 3: Revisão do branch inteiro** (superpowers:requesting-code-review).
- [ ] **Step 4: Parar e entregar ao usuário** com a lista do que ele confere no app real (merge no master só com o ok dele; depois do merge ele reinicia o Therion e reconcede a autonomia, porque o hash do código muda):
  1. "me lembra de beber água em 2 minutos" → resposta e aviso falado na hora.
  2. Lembrete tocando com o Therion falando → espera e fala depois.
  3. "todo dia às 6 tomar remédio" → pergunta manhã/tarde.
  4. Fechar e abrir com um lembrete vencido → "passou da hora".
  5. "foco 5 minutos" → número e arco nas duas orbes, âmbar no fim, resumo falado com e-mails, "sim" para a pausa verde.
  6. Lembrete e fim de foco durante um jogo em tela cheia → falam.
