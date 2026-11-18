# Palavra de ativação "Therion"

Data: 17/11/2026 · Depende de: `2026-11-17-mini-orbe-design.md` (a mini orbe mostra o Therion acordando)

## Por quê

O usuário conversa com amigos, joga e fala de tudo perto do PC. Ele quer que o Therion não ouça nada disso e só
acorde quando ouvir o próprio nome, sem precisar clicar em botão ou trocar de janela. Vale sempre que o Therion
estiver aberto, não só no modo de jogo.

## Objetivos

- Microfone analisado o tempo todo dentro do PC por um detector que só reconhece "Therion". Nada é gravado, salvo
  ou enviado antes da palavra; o áudio do detector é descartado continuamente.
- Numa frase só: "Therion, abre o Discord" — ele acorda no nome e pega o resto, sem pausa.
- Com pausa: "Therion…" (acende e espera até 5 s) "…que horas são?". Sem fala em 5 s, volta a dormir.
- Ao acordar: as duas orbes vão para "ouvindo" e toca um som curto.
- Depois da resposta, 8 s ouvindo sem precisar do nome (continuação, "sim" à oferta de limpeza do vigia etc.).
- Enquanto o Therion fala, "Therion, para" interrompe e ele escuta.
- O botão e o atalho de hoje continuam iguais.
- `ui.wake_word` (padrão `True`) e "Therion, para de me ouvir" desliga até o próximo início.
- Falsos alarmes não fazem nada sozinhos (sem pedido, ele volta a dormir) e ficam no registro de conversa com a
  pontuação do detector, para ajustar a sensibilidade.

## Não objetivos

- Outras palavras ou apelidos, reconhecer quem está falando, funcionar com o Therion fechado.
- Trocar o transcritor (continua o faster-whisper atual) ou o fluxo de conversa por voz.

## Antiobjetivos

- Acordar com conversa do Discord ou com o som do jogo a ponto de incomodar (meta: no máximo 1 falso alarme por
  hora de conversa normal; medir no uso real).
- Pesar no jogo (meta: detector abaixo de ~3% de um núcleo de CPU; medir).
- Acordar com a própria voz do Therion dizendo "Therion".
- Gravar ou guardar áudio sem a palavra.

## Restrições

- Mesmo processo do Therion; repositório público (o modelo treinado e os caminhos pessoais ficam fora dele).
- Instalar dependência nova no `.venv` do Therion só depois de ler o código do pacote (rede, comandos executados).
- Baixar arquivos (modelos base do openWakeWord) pede o ok do usuário na hora.
- Memória apertada no PC (commit já esgotou antes): nada de deixar o Whisper transcrevendo o tempo todo.

## Abordagens consideradas

1. **openWakeWord com modelo "Therion" próprio** — escolhida pelo usuário. Código aberto, sem conta, roda com o
   `onnxruntime` que já está instalado, ~1–2% de CPU. Exige treinar a palavra uma vez num notebook Colab
   (~1 h, voz sintética do Piper). O notebook oficial está quebrado desde 2023; usar um da comunidade, lido antes.
2. Porcupine (Picovoice): preciso e treina em segundos, mas exige conta, chave de acesso e depende da empresa;
   não confirmado se o plano grátis cobre palavra própria em português.
3. Whisper procurando "Therion" em tudo: descartado, transcreveria o Discord sem parar e pesaria no jogo.

## Como funciona

**Treino (uma vez, precisa do usuário)**
- Eu preparo o notebook (lido e conferido) com a frase "Therion" e variações de pronúncia em português ("Térion",
  "Tirion"), vozes Piper em inglês e português do Brasil para os positivos, e frases parecidas como negativos
  ("terreno", "teria", "Tereza").
- O usuário abre o Colab com a conta Google dele e aperta o play; o resultado é `therion.onnx`.
- O modelo fica em `%LOCALAPPDATA%\Therion\wake\therion.onnx` (fora do repositório).
- Se errar muito com a voz dele: reforçar com 20–30 gravações próprias (positivos) e alguns minutos de conversa
  normal dele (negativos).

**Escuta** (`voice/wake.py`, novo)
- Thread própria com um `sounddevice.InputStream` 16 kHz, mono, int16, blocos de 1280 amostras (80 ms), no mesmo
  microfone escolhido pelo Therion. O Windows compartilha o microfone com o Discord e com a captura do Therion.
- openWakeWord com `inference_framework='onnx'`; disparo quando a pontuação passar do limite (`wake.threshold`,
  começar em 0,5 e ajustar com o registro) e respeitando um intervalo mínimo de 2 s entre disparos.
- Guarda os últimos ~3 s num buffer circular só na memória; ao disparar, entrega o áudio desde o fim da palavra
  para a captura, para não perder o "abre o Discord" falado logo depois (a abertura do microfone já foi lenta antes;
  ver a correção do "microfone parado" em `voice/capture.py`).
- Pausa sozinha enquanto a captura normal do Therion está gravando (não precisa ouvir o nome no meio de um pedido).
- Funciona com a janela minimizada ou na bandeja: vale enquanto o processo do Therion estiver aberto.
- O Windows mostra o ícone de microfone em uso na bandeja o tempo todo enquanto o detector escuta. É esperado.

**Ao acordar** (`interface/desktop.py`)
- Sinal Qt para a thread principal. Se não houver pedido em andamento: estado "ouvindo" nas duas orbes, som curto
  e captura de um turno pelo mesmo caminho do botão de voz (`_on_voice_clicked` e o `AudioCaptureService`),
  começando pelo áudio entregue pelo detector. Sem fala em 5 s, cancela e volta a dormir.
- Durante a fala do Therion: para a fala e escuta (interrupção). Para não acordar com a própria voz: se o texto
  sendo falado contém "Therion", ignora disparos até o fim dessa fala.
- Durante um pedido em andamento (pensando/executando): ignora o disparo.
- Depois da resposta: 8 s de escuta automática sem o nome; depois volta a dormir.
- "Therion, para de me ouvir": frase local (sem modelo, como os outros pedidos locais em `core/local_reports.py`)
  que desliga o detector até reiniciar.

**Transcritor pronto (decisão do usuário: meio-termo)**
- Com `ui.wake_word` ligado, o faster-whisper fica carregado enquanto o Therion está aberto, para o pedido depois do
  nome sair na hora.
- No modo jogo e em tela cheia (os mesmos sinais que já descarregam o modelo de IA em `_poll_game_mode`), ele é
  descarregado para devolver a RAM. Ao sair, volta a carregar em segundo plano.
- Se o nome vier com o transcritor descarregado, a captura grava normalmente enquanto ele carrega e só a resposta
  atrasa; nada do que foi falado se perde. A mini orbe mostra "preparando" nesse intervalo.

**Registro**
- Cada disparo vai para o registro de conversa (`ui.conversation_log`) com a pontuação e se virou pedido ou não,
  sem áudio.

## Testes

- Detector falso alimentando pontuações: dispara uma vez acima do limite, respeita os 2 s, não dispara durante a
  captura normal, ignora durante a fala quando o texto contém "Therion".
- Buffer circular entrega exatamente o áudio depois do disparo.
- Janela: disparo em repouso abre a escuta com o áudio entregue; 5 s sem fala volta a dormir; disparo durante a fala
  para a fala; disparo com pedido em andamento é ignorado; janela de 8 s depois da resposta; `ui.wake_word=false`
  não abre o microfone.
- Frase "para de me ouvir" no banco de frases reais (`tests/frases_reais.txt`).

## Verificação no PC real

- CPU do detector em repouso e com jogo aberto.
- 1 hora de conversa no Discord com o Therion aberto: contar falsos alarmes no registro.
- O usuário diz "Therion, abre o Discord" e "Therion… que horas são?" 10 vezes cada: contar acertos.

## Decisões minhas (o usuário pode trocar)

Prazos de 5 s e 8 s, o som curto, o limite inicial de 0,5, o intervalo de 2 s, ignorar durante pedido em andamento,
o modelo fora do repositório, e "para de me ouvir" valendo só até reiniciar.

## Fica para o construtor

Integração exata com o `VoicePipeline` e o `AudioCaptureService` (aceitar áudio inicial), escolha do notebook Colab
depois de lê-lo, o arquivo de som, e como compartilhar a escolha de microfone com a captura atual.
