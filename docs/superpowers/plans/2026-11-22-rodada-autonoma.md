# Rodada autônoma 22/11 — achados dos testes falados e itens adiados

**Goal:** corrigir os achados 2 e 5 dos testes falados de 22/11 e os itens menores adiados do modo foco/lembretes, sem mudar nada visual.

**Ramo:** `auto-22-11` em `F:\Therion\auto-wt` (base `orbe-modo-jogo` 66d7f0f). O Therion do usuário roda de `F:\Therion\app`: nunca tocar lá.

Rodar testes (raiz `F:\Therion\auto-wt`): `F:/Therion/app/.venv/Scripts/python.exe scripts/test-v4.py <arquivos> -q`. Nunca `pytest` direto.

## Global Constraints

- Repositório público: nada de conversa pessoal, e-mail, nome de pessoa real ou chave em teste/commit.
- Não mexer em visual (orbe, cores, layout, textos de tela), nem em arquivos da voz Edge (`scripts/Start-Therion.ps1`, `scripts/VoiceStartup.ps1`, `therion/voice/edge_worker.py`).
- Toda mudança de comportamento tem teste que falha antes e passa depois. Frases novas reconhecidas entram em `tests/frases_reais.txt` (fora do git) no formato existente.
- Sem dependência nova. Sem rede real nos testes.
- Respostas faladas em pt-BR, curtas, no tom das respostas vizinhas.

---

### Task 1: "Quantos e-mails eu tenho hoje?" responde pela regra local

Achado 2 de `Testes falados - 2026-11-22`: com "hoje" (ou "chegaram hoje", "recebi hoje"), a frase vai para a IA (7,7 s, respondeu "10", que parece ser o tamanho da página do Gmail). A regra fixa de contagem entende "quantos e-mails eu tenho" (não lidos), mas não "hoje".

- Ache a regra fixa de contagem (procure em `therion/agent/gmail_queries.py`, `therion/agent/mailbox.py`, `therion/core/routes.py`, `therion/agent/host.py` e no banco `tests/frases_reais.txt`).
- Ruling já tomado: com "hoje" a resposta dá os dois números numa frase: quantos chegaram hoje e quantos deles (ou no total) estão sem ler, ex. "Chegaram 12 e-mails hoje; 5 ainda não foram lidos." Reaproveite a contagem por data que a saudação usa (`mail_since` com `limit=500` em `therion/agent/briefing.py`) e a de não lidos que já existe. Nada de página de 10.
- Variações que precisam cair na regra: "quantos e-mails eu tenho hoje", "quantos e-mails chegaram hoje", "quantos e-mails eu recebi hoje", "quantos emails tenho hoje". Sem "hoje", nada muda.
- Testes com caixa falsa (padrão dos testes `tests/test_gmail_*`), incluindo um que prova que a contagem não para em 10.

### Task 2: A Groq não inventa fala no silêncio

Achado 5: mandando silêncio para a Groq, ela devolve "Tchau." com confiança alta, passando pelo filtro `_reliable` em `therion/voice/transcription.py` (que olha avg_logprob, no_speech_prob e compression_ratio). Hoje só o VAD da captura protege.

- Em `therion/voice/groq_model.py` (`GroqVoiceModel`), antes de mandar para a Groq: se o áudio for praticamente silêncio (RMS muito baixo; escolha o limite olhando o que `therion/voice/activity.py`/`endpointing.py` já usam para "tem voz"), não envie e devolva lista vazia de segmentos (o mesmo formato de "não ouvi nada").
- Depois da resposta: descarte o resultado inteiro quando o texto completo, normalizado, for uma das alucinações clássicas do Whisper em pt ("tchau", "obrigado", "obrigada", "legendas pela comunidade amara.org", "legenda por ...", "inscreva-se", "e aí") E o áudio tiver pouca energia (abaixo de um limite maior que o do silêncio). Um "Tchau." falado de verdade, com energia normal, continua passando. Comente o porquê numa linha.
- Testes em `tests/` (arquivo da Groq que já existir, ex. `tests/test_groq_voice*.py`): silêncio não chama a rede; "Tchau." com áudio fraco é descartado; "Tchau." com voz forte passa; frase normal passa.

### Task 3: Itens menores adiados dos lembretes por voz

Do ledger `F:\Therion\tmp\foco-lembretes-ledger.md` (Tasks 1–3). Arquivos prováveis: `therion/core/voice_reminders.py`, `therion/memory/reminders*.py` ou equivalente (procure por `due_message`, `_quarantine`, `_classify`). Para cada item: teste que falha, correção mínima. Se um item já estiver resolvido no código, anote no relatório e pule.

1. "todo dia em 10 minutos": o tempo relativo é ignorado quando há dias de repetição. Comportamento esperado: primeira vez daqui a 10 min, repetindo todo dia nesse horário.
2. Um segundo "às N" fica dentro do texto do lembrete ("me lembra às 8 de ligar às 9"). Esperado: só o primeiro horário é o do lembrete; o texto mantém "ligar às 9" (não mudar isso), mas nada de dois horários sendo apagados/confundidos — escreva o teste que fixa isso.
3. "a meio-dia", "a 10 horas", "a N e meia" sem o "às": hoje caem em "pedir quando". Esperado: entendidos como horário, sem reabrir o bug "ligar a uma amiga" → 01:00 (teste dele tem de continuar passando).
4. Nome `.bad` da quarentena com resolução de 1 s pode sobrescrever um `.bad` anterior: use nome único (ex. sufixo incremental).
5. `due_message([])` devolve "Zero lembretes: ." — devolva "" (os chamadores já protegem; teste só da função).
6. Texto "e mais K e mais N antigos" estranho: reescreva numa frase natural.
7. Com o "o quê" pendente, um "sim"/"não" solto vira o texto do lembrete: não pode.
8. A remoção de vírgula em `_classify` altera decimais ("1,5 hora"): "daqui a 1,5 hora" = 90 min.
9. Erro de formatação `pending =getattr` em `voice_reminders.py`.
10. Falta teste de duas threads para o lock de `store()`: escreva.

### Task 4: Itens menores adiados do modo foco e das ofertas

Do mesmo ledger (Tasks 4, 6 e Final). Arquivos prováveis: `therion/core/focus.py`, `therion/core/orchestrator.py`, `therion/interface/desktop.py` (só lógica, nada visual). Mesmo método da Task 3.

1. "pausa" sem foco ativo começa algo: deve responder que não há foco ativo.
2. O orchestrator não passa o relógio (`_now_func`) para a resposta do foco: passe.
3. "foco em"/"foco de" sem duração é aceito como início: deve pedir a duração (ou usar o padrão já existente, se houver um — confira o código e siga o que o foco já faz para "modo foco" sem número).
4. Busca de e-mail importante do foco sem `token.check` antes: adicione.
5. Parar cedo credita `now.date()`, fim natural credita a data do fim (vira a meia-noite): use sempre a data de início do foco.
6. Token/thread do e-mail do foco sobrescrito quando dois focos se sobrepõem: cancele o anterior.
7. `process_session_command` cancelado/obsoleto retorna antes do snapshot e a próxima frase gasta as ofertas: corrija a ordem.
8. A rota local limpa ofertas por atribuição, não por identidade (uma oferta de foco armada no meio do turno é apagada): compare identidade.
