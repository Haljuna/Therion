# Palavra de ativação "Therion" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O Therion escuta o microfone o tempo todo com um detector local que só reconhece "Therion"; ao ouvir o nome, acorda, pega o pedido (inclusive o que veio na mesma frase) e volta a dormir depois.

**Architecture:** `voice/wake.py` tem a lógica pura (portão de disparo e buffer circular) e o `WakeListener` (thread com `sounddevice` + openWakeWord em ONNX). A captura e o pipeline de voz passam a aceitar áudio inicial e prazo sem fala. `MainWindow` recebe o disparo, abre um turno pelo modo de conversa já existente e encerra por silêncio. O transcritor fica carregado, mas descarrega na tela cheia/modo jogo.

**Tech Stack:** Python 3.14, PySide6, `sounddevice`, `onnxruntime` (já instalados), `openwakeword` (novo), faster-whisper (atual), pytest via `scripts/test-v4.py`.

**Spec:** `docs/superpowers/specs/2026-11-17-palavra-de-ativacao-design.md`

**Depende de:** `docs/superpowers/plans/2026-11-17-mini-orbe.md` (a mini orbe recebe os estados; sem ela, só a orbe grande muda).

Rodar testes: `F:/Therion/app/.venv/Scripts/python.exe scripts/test-v4.py <arquivos> -q` (raiz `F:\Therion\vigia-wt`).

## Global Constraints

- Nada de áudio gravado, salvo ou enviado antes da palavra; o buffer circular vive só na memória.
- Áudio do detector: 16 kHz, mono, int16, blocos de 1280 amostras (80 ms); buffer de ~3 s.
- Disparo: pontuação ≥ `wake.threshold` (padrão 0,5) e no mínimo 2 s desde o último disparo.
- 5 s sem fala depois do nome: volta a dormir. 8 s de continuação sem o nome depois de cada resposta.
- Durante a fala do Therion, o nome interrompe; se o texto falado contém "Therion", disparos são ignorados até o fim dessa fala.
- Pedido em andamento (pensando/executando): disparo ignorado.
- `ui.wake_word` padrão `True`; "Therion, para de me ouvir" desliga até reiniciar.
- Modelo em `%LOCALAPPDATA%\Therion\wake\therion.onnx`, nunca no repositório. Sem o arquivo, o detector não liga e o Therion segue igual a hoje.
- Transcritor: carregado com `ui.wake_word` ligado; descarregado em tela cheia/modo jogo; nome com ele descarregado = captura normal enquanto carrega.
- Botão e atalho de voz atuais não mudam.
- Instalar `openwakeword` só depois de ler o código do pacote; baixar os modelos base pede o ok do usuário.

## Review Focus

- Microfone desconectado ou trocado com o Therion aberto: o detector não pode travar nem derrubar o app; deve tentar reabrir a cada 10 s e registrar uma vez (Task 2).
- Discord ou outro app abrindo o microfone em modo exclusivo: `InputStream` falha ao abrir; esperado é seguir sem detector e dizer isso uma vez na janela, não repetir a cada tentativa (Task 2).
- Duas pessoas falando "Therion" seguidas (o usuário e um amigo na chamada): o segundo disparo dentro do turno já aberto não pode abrir outro turno (Task 4).
- Dizer "Therion" enquanto o transcritor está carregando de novo depois do jogo: o pedido não pode se perder (Task 5).
- O Therion fechando no meio de um disparo: a thread do detector precisa parar antes de a janela sumir, sem `access violation` (Task 4).

---

### Task 0: Preparar o detector (precisa do usuário)

Sem código do Therion. Cada item termina com algo verificável.

- [ ] **Step 1:** Baixar o código do `openwakeword` (versão mais recente do PyPI) numa pasta própria em `F:\Therion\tmp\wake-review\`, ler `openwakeword/model.py`, `utils.py` e o `setup.py`/`pyproject.toml`: anotar toda chamada de rede (download de modelos) e dependências. Reportar ao usuário antes de instalar. Expected: lista de dependências e de URLs que o pacote acessa.
- [ ] **Step 2:** Com o ok do usuário, `F:/Therion/app/.venv/Scripts/python.exe -m pip install openwakeword` e baixar os modelos base (`melspectrogram.onnx`, `embedding_model.onnx`) para `%LOCALAPPDATA%\Therion\wake\`. Expected: `python -c "import openwakeword"` sem erro e os dois arquivos presentes.
- [ ] **Step 3:** Escolher e ler o notebook Colab de treino (ver fontes na spec); conferir que não envia nada além do Colab. Preparar a configuração: frase `therion`, variações `térion` e `tirion`, vozes Piper en-US e pt-BR para positivos, negativos `terreno`, `teria`, `tereza`, `território`. Entregar ao usuário o link e o passo a passo em 3 linhas.
- [ ] **Step 4 (usuário):** rodar o notebook e baixar `therion.onnx` para `%LOCALAPPDATA%\Therion\wake\therion.onnx`. Expected: arquivo presente; `openwakeword.Model(wakeword_models=[<caminho>], inference_framework='onnx')` carrega.
- [ ] **Step 5:** Medir à mão com um script de uma vez no scratchpad: 30 s falando "Therion" de vez em quando e 2 min de conversa normal; imprimir as pontuações máximas. Expected: "Therion" acima de 0,5 e conversa abaixo; senão, ajustar o limite inicial antes da Task 2.

---

### Task 1: Portão de disparo e buffer circular

**Files:**
- Create: `therion/voice/wake.py`
- Test: `tests/test_wake.py`

**Interfaces:**
- Produces:
  - `class WakeGate: __init__(self, threshold=0.5, refractory=2.0, clock=time.monotonic)`; `feed(self, score: float) -> bool` (True só no disparo); `muted: bool` (True ignora tudo).
  - `class RingBuffer: __init__(self, seconds=3.0, rate=16000)`; `push(self, block: np.ndarray) -> None` (int16); `mark(self) -> int` (posição atual em amostras totais); `since(self, mark: int) -> np.ndarray` (float32 em [-1, 1], do `mark` até agora; vazio se o `mark` já saiu do buffer).

- [ ] **Step 1: Write the failing tests**

```python
def test_fires_once_above_the_threshold_and_respects_two_seconds():
    clock = Clock(); gate = WakeGate(0.5, 2.0, clock)
    assert [gate.feed(s) for s in (.1, .6, .9)] == [False, True, False]
    clock.now = 1.9; assert gate.feed(.9) is False
    clock.now = 2.1; assert gate.feed(.9) is True

def test_a_muted_gate_never_fires():
    gate = WakeGate(); gate.muted = True; assert gate.feed(.99) is False

def test_ring_buffer_hands_over_only_the_audio_after_the_mark():
    ring = RingBuffer(seconds=1.0, rate=10)
    ring.push(np.full(4, 1000, np.int16)); mark = ring.mark(); ring.push(np.full(3, -1000, np.int16))
    assert np.allclose(ring.since(mark), -1000 / 32768)
    ring.push(np.zeros(20, np.int16)); assert ring.since(mark).size == 0   # já saiu do buffer
```

- [ ] **Step 2: Run** `... tests/test_wake.py -q` — Expected: FAIL (import).
- [ ] **Step 3: Implement** `WakeGate` e `RingBuffer` (numpy, sem openwakeword).
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** `feat(voz): portão de disparo e buffer circular da palavra de ativação`

---

### Task 2: `WakeListener`

**Files:**
- Modify: `therion/voice/wake.py`
- Test: `tests/test_wake.py`

**Interfaces:**
- Consumes: Task 1.
- Produces: `class WakeListener: __init__(self, model_path: str, on_wake: Callable[[np.ndarray, float], None], *, threshold=0.5, model_factory=None, stream_factory=None, on_problem: Callable[[str], None] | None = None)`
  - `start() -> bool` (False sem o arquivo do modelo ou sem `openwakeword`, sem exceção), `stop()` (para o stream e junta a thread em até 2 s; idempotente), `pause()`/`resume()` (enquanto a captura normal grava), `gate` (o `WakeGate`, para `muted`).
  - `on_wake(audio_depois_do_nome: float32, score)` é chamado na thread do detector; quem recebe repassa para a thread Qt.
  - Falha ao abrir o microfone ou erro no meio: chama `on_problem` uma vez por tipo de falha e tenta reabrir a cada 10 s.
  - `model_factory` padrão: `openwakeword.Model(wakeword_models=[model_path], inference_framework='onnx')`; pontuação de `model.predict(block)` pelo nome do modelo.

- [ ] **Step 1: Write the failing tests** (stream e modelo falsos; nada de microfone real)

```python
def test_listener_calls_back_with_the_audio_after_the_wake_word(): ...
    # stream falso empurra 5 blocos; modelo falso dá score .9 no 3º → on_wake chamado 1 vez, áudio = blocos 4 e 5
def test_paused_listener_feeds_nothing_to_the_model(): ...
def test_missing_model_file_means_no_listener_and_no_error(tmp_path):
    assert WakeListener(str(tmp_path / 'nao.onnx'), lambda a, s: None).start() is False
def test_a_microphone_that_fails_to_open_is_reported_once_and_retried(): ...
    # stream_factory levanta OSError 3 vezes e depois funciona; relógio falso; on_problem chamado 1 vez; abriu na 4ª
def test_stop_is_safe_twice_and_joins_the_thread(): ...
```

- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement.** O callback do `InputStream` só empurra blocos numa `queue.Queue`; a thread do detector faz `predict`, alimenta o `RingBuffer` e o `WakeGate` (no disparo, `mark()` logo após o bloco que disparou e espera ~300 ms de blocos antes de chamar `on_wake` com `since(mark)`).
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** `feat(voz): WakeListener com openWakeWord em ONNX`

---

### Task 3: Captura com áudio inicial e prazo sem fala

**Files:**
- Modify: `therion/voice/capture.py` (`AudioCaptureService.start`, ~linha 76)
- Modify: `therion/voice/endpointing.py` (`SpeechEndpoint.__init__`/`feed`)
- Modify: `therion/voice/pipeline.py` (`VoicePipeline.start`, ~linha 89)
- Test: `tests/test_voice_capture.py`, `tests/test_voice_endpointing.py`, `tests/test_voice_pipeline.py` (os existentes; acrescentar)

**Interfaces:**
- Produces:
  - `AudioCaptureService.start(self, *, automatic=False, preroll: np.ndarray | None = None, no_speech_seconds: float | None = None) -> bool` — `preroll` (float32) entra primeiro em `_chunks` e no endpoint.
  - `SpeechEndpoint(..., no_speech_seconds=None)` — completa com `reason='no_speech'` quando `elapsed >= no_speech_seconds` e ainda não houve voz.
  - `VoicePipeline.start(self, *, automatic=False, preroll=None, no_speech_seconds=None) -> bool` — repassa à captura.

- [ ] **Step 1: Write the failing tests**

```python
def test_preroll_audio_comes_first_in_the_capture(): ...
    # stream falso; start(automatic=True, preroll=np.full(1600, .2, np.float32)); 1 bloco de .0; stop() começa com 1600 amostras de .2
def test_endpoint_gives_up_when_nobody_speaks():
    end = SpeechEndpoint(16000, no_speech_seconds=5.0, activity=lambda s: False)
    for _ in range(62): end.feed(np.zeros(1280, np.float32))   # 4,96 s
    assert not end.complete
    end.feed(np.zeros(1280, np.float32)); assert end.complete and end.reason == 'no_speech'
def test_pipeline_passes_preroll_and_timeout_to_the_capture(): ...
```

- [ ] **Step 2: Run** — Expected: FAIL (`unexpected keyword argument 'preroll'`).
- [ ] **Step 3: Implement.** Sem os parâmetros, o comportamento atual não muda (os testes existentes continuam passando sem edição).
- [ ] **Step 4: Run** os arquivos de voz: `... tests/test_voice_capture.py tests/test_voice_endpointing.py tests/test_voice_noise_endpoint.py tests/test_voice_pipeline.py -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(voz): captura aceita áudio inicial e desiste sem fala`

---

### Task 4: Acordar na janela principal

**Files:**
- Modify: `therion/config/local.py` (`ui.wake_word` padrão `True`; `wake.threshold` float 0,05–0,99, padrão 0,5)
- Modify: `therion/interface/desktop.py` (`__init__`; novo `_on_wake`; `_on_voice_pipeline_state_changed` para `pause/resume`; `_quit_application` e `closeEvent` param o listener antes de `self._app.quit()`/`super().closeEvent`)
- Modify: `therion/core/local_reports.py` (frase "para de me ouvir" → `ui_action='wake_off'`, como `game_mode`)
- Modify: `therion/core/orchestrator.py` (a resposta "Tudo bem, parei de ouvir pelo nome até o senhor me abrir de novo." com `ui_action='wake_off'`)
- Modify: `tests/frases_reais.txt` (`para de me ouvir => wake_off`)
- Test: `tests/test_wake_window.py`, `tests/test_local_reports.py`

**Interfaces:**
- Consumes: Task 2 (`WakeListener`), Task 3 (`VoicePipeline.start(..., preroll, no_speech_seconds)`), mini orbe (`MainWindow._mini_orb.set_state`), `_toggle_conversation`, `_end_conversation`, `_stop_speech`, `_speech_text`, `ConversationLog`.
- Produces:
  - `MainWindow._wake: WakeListener | None`, sinal Qt `_wake_heard = Signal(object, float)` (áudio, pontuação) conectado a `_on_wake`.
  - `MainWindow._on_wake(self, audio, score) -> None`:
    - `_processing` → ignora (registra "ignorado: pedido em andamento").
    - fala em andamento → se `'therion' in control(self._speech_text or '')`, ignora; senão `_stop_speech()` e segue.
    - turno de voz já aberto (pipeline gravando) → ignora.
    - caso normal: estado "listening" nas orbes, som curto (`QSoundEffect` com um wav curto em `therion/assets/`), abre o modo conversa se fechado e inicia a captura com `preroll=audio, no_speech_seconds=5.0`.
  - Continuação: no modo conversa aberto pelo nome, cada escuta automática depois de resposta usa `no_speech_seconds=8.0`; `reason == 'no_speech'` encerra o modo conversa (`_end_conversation`) e volta a dormir.
  - `ui_action == 'wake_off'` → `self._wake.gate.muted = True` até reiniciar.
  - Cada disparo vai ao registro de conversa: `acordou pelo nome · pontuação 0.83 · virou pedido | sem fala | ignorado: <motivo>` (sem áudio).

- [ ] **Step 1: Write the failing tests** (listener falso; pipeline falso gravando `start(**kwargs)`)

```python
def test_waking_in_idle_listens_with_the_audio_after_the_name(app, tmp_path, monkeypatch): ...
    # _on_wake(np.ones(800, np.float32), .8) → pipeline.start chamado com preroll de 800 e no_speech_seconds=5.0; orbe 'listening'
def test_the_name_is_ignored_while_a_request_is_running(app, tmp_path, monkeypatch): ...
def test_the_name_stops_the_speech_unless_the_speech_says_therion(app, tmp_path, monkeypatch): ...
def test_a_second_name_inside_an_open_turn_does_not_open_another(app, tmp_path, monkeypatch): ...
def test_silence_after_the_name_goes_back_to_sleep(app, tmp_path, monkeypatch): ...  # reason 'no_speech' → _end_conversation
def test_follow_up_listening_waits_eight_seconds(app, tmp_path, monkeypatch): ...
def test_stop_listening_phrase_mutes_the_wake_word_without_the_model(case): ...  # _CommandWorker('Therion, para de me ouvir') → ui_action 'wake_off'
def test_wake_word_is_on_by_default_and_off_means_no_microphone(app, tmp_path, monkeypatch):
    assert _validate_config({})['ui']['wake_word'] is True
    # ui {'wake_word': False} → window._wake is None
def test_quitting_stops_the_listener_first(app, tmp_path, monkeypatch): ...
```

- [ ] **Step 2: Run** `... tests/test_wake_window.py tests/test_local_reports.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement.** O listener só é criado se `ui.wake_word` e o arquivo do modelo existirem; `on_problem` escreve uma vez na janela ("Não consegui abrir o microfone para ouvir meu nome; tento de novo sozinho.").
- [ ] **Step 4: Run** — Expected: PASS. Depois a suíte inteira em segundo plano: `... scripts/test-v4.py tests -q -p no:cacheprovider` — Expected: 0 falhas.
- [ ] **Step 5: Commit** `feat(voz): acordar pelo nome, continuação de 8 s e "para de me ouvir"`

---

### Task 5: Transcritor no meio-termo

**Files:**
- Modify: `therion/voice/service.py` (`VoiceModelService.unload`)
- Modify: `therion/voice/transcription.py` (`VoiceTranscriptionService.swap_model`)
- Modify: `therion/interface/desktop.py` (`_poll_game_mode`/`_poll_pc_watch`: com `ui.wake_word`, descarregar ao entrar em tela cheia/modo jogo e recarregar ao sair; `_on_voice_model_loaded` religa o modelo no pipeline existente)
- Test: `tests/test_voice_service.py`, `tests/test_wake_window.py`

**Interfaces:**
- Produces:
  - `VoiceModelService.unload(self) -> bool` — só em `STATE_READY`: solta a referência do modelo e volta a `STATE_UNLOADED` (emite `state_changed`); `False` em outro estado.
  - `VoiceTranscriptionService.swap_model(self, model | None) -> None`; transcrever com `None` espera o próximo `swap_model` com modelo por até 60 s (`threading.Event`) e então falha como hoje.
  - Ao acordar com o serviço descarregado: `self._voice_service.load()` e a captura começa na hora; a mini orbe mostra `'preparing'` até o modelo voltar.

- [ ] **Step 1: Write the failing tests**

```python
def test_unload_frees_the_model_only_when_ready(): ...
def test_transcription_waits_for_the_model_to_come_back(): ...  # swap_model(None); thread transcreve; swap_model(fake) 0,2 s depois → texto do fake
def test_full_screen_unloads_the_transcriber_and_leaving_reloads_it(app, tmp_path, monkeypatch): ...
def test_the_name_during_reload_keeps_the_request(app, tmp_path, monkeypatch): ...
```

- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement.** Nada muda com `ui.wake_word` desligado (comportamento de hoje: carrega no primeiro clique).
- [ ] **Step 4: Run** `... tests/test_voice_service.py tests/test_wake_window.py -q` e depois a suíte inteira em segundo plano — Expected: 0 falhas.
- [ ] **Step 5: Commit** `feat(voz): transcritor descarrega no jogo e volta sozinho`

---

### Task 6: Verificação no PC real (com o usuário)

- [ ] **Step 1:** CPU do `pythonw.exe` com o detector ligado: 1 min parado e 1 min com um jogo aberto. Meta: detector abaixo de ~3% de um núcleo. Anotar.
- [ ] **Step 2:** 1 hora de Discord com o Therion aberto; contar no registro de conversa os disparos sem pedido. Meta: no máximo 1. Acima disso, subir `wake.threshold` em 0,1 e repetir.
- [ ] **Step 3:** O usuário diz "Therion, abre o Discord" 10 vezes e "Therion… que horas são?" 10 vezes. Anotar acertos. Abaixo de 8/10 em algum: reforçar o modelo com 20–30 gravações dele (Task 0, Step 4 de novo).
- [ ] **Step 4:** Entrar e sair de um jogo em tela cheia; conferir que a RAM do transcritor sai e volta (Gerenciador de Tarefas) e que o primeiro "Therion" depois do jogo ainda vira pedido.
- [ ] **Step 5:** Registrar os números na nota do projeto e commitar o que tiver mudado (limite, por exemplo) com `chore(voz): ajuste da palavra de ativação após uso real`.
