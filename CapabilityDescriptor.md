# Therion — CapabilityDescriptor

> Inventário documental mínimo das capabilities atuais do Therion.
> Registro estático derivado de auditoria read-only ao código.
> Esta nota não é um Registry, não contém código executável e não tem autoridade de decisão.

---

## Princípio

CAPABILITYDESCRIPTOR:

- DESCREVE
- NÃO AUTORIZA
- NÃO EXECUTA
- NÃO AMPLIA PERMISSÃO

Este descriptor é um retrato do código existente. Nenhuma decisão de permissão,
autonomia ou confirmação nasce aqui. Toda autorização continua vindo das fontes
citadas em `origem_autorizacao` (Decisões, allowlists técnicas, configuração
local e notas de Skill oficiais).

---

## Contrato mínimo

Campos obrigatórios de cada entrada:

1. `id`
2. `tipo`
3. `acionador`
4. `efeito`
5. `exige_confirmacao`
6. `dependencias`
7. `executor`
8. `limitacoes`
9. `origem_autorizacao`
10. `status`

Campos que não existem neste contrato, por misturar rota com permissão:

- `allowed_roots` como grant;
- `autorizado=true/false`;
- nível de autonomia;
- `pode_pular_confirmacao`;
- código executável.

---

## Entradas (9)

### 1. capability — ler_nota_segundo_cerebro

- **id:** `ler_nota_segundo_cerebro`
- **tipo:** capability
- **acionador:** intent `consultar segundo cérebro` (IntentRecognizer, `therion/core/intent.py`)
- **efeito:** leitura
- **exige_confirmacao:** não
- **dependencias:** SecondBrainReader; WorkingMemory (registro da consulta)
- **executor:** `Orchestrator.read_context()` → `SecondBrainReader.read_note()`
- **limitacoes:** somente arquivos `.md`; somente as raízes fixas declaradas no Reader; sem escrita; path traversal bloqueado
- **origem_autorizacao:** DEC-003; DEC-008 (leitura no escopo); raízes fixas declaradas em `SecondBrainReader`
- **status:** ativa

### 2. capability — buscar_segundo_cerebro

- **id:** `buscar_segundo_cerebro`
- **tipo:** capability
- **acionador:** intent `buscar segundo cérebro` (IntentRecognizer)
- **efeito:** leitura
- **exige_confirmacao:** não
- **dependencias:** SecondBrainReader
- **executor:** `Orchestrator.process_command` → `SecondBrainReader.search_notes()`
- **limitacoes:** busca literal e case-insensitive; máximo de 5 resultados; snippet de até 200 caracteres; sem embeddings, sem LLM, sem regex fornecida pelo usuário; somente `.md` nas raízes fixas
- **origem_autorizacao:** DEC-003; DEC-008; raízes fixas do Reader
- **status:** ativa

### 3. capability — consultar_calendario_hoje

- **id:** `consultar_calendario_hoje`
- **tipo:** capability
- **acionador:** intent `calendário hoje` (IntentRecognizer)
- **efeito:** leitura
- **exige_confirmacao:** não
- **dependencias:** GoogleCalendarAdapter; OAuth2 local; tzdata; configuração `calendar.*`
- **executor:** `Orchestrator._handle_calendar_today()` → `CalendarAdapter.list_events_for_day()`
- **limitacoes:** somente calendário `primary`; falha retorna `CalendarError` controlado sem derrubar o Therion
- **origem_autorizacao:** DEC-029 (consulta sem confirmação); credencial OAuth do usuário
- **status:** ativa

### 4. capability — criar_evento_calendario

- **id:** `criar_evento_calendario`
- **tipo:** capability
- **acionador:** intent `criar evento calendário` (IntentRecognizer) + fluxo conversacional
- **efeito:** escrita
- **exige_confirmacao:** sim
- **dependencias:** GoogleCalendarAdapter; OAuth2 local; ConfirmationHandler; configuração `calendar.*`
- **executor:** `Orchestrator._handle_calendar_create_flow()` → `CalendarAdapter.create_event()`
- **limitacoes:** somente criação, sem edição, exclusão, convites ou anexos; estado temporário limpo em sucesso, erro e cancelamento; persistência somente após confirmação explícita
- **origem_autorizacao:** DEC-029 (escopo de criação); DEC-008 e DEC-009 (confirmação e mini-plano); credencial OAuth do usuário
- **status:** ativa

### 5. capability — abrir_aplicativo

- **id:** `abrir_aplicativo`
- **tipo:** capability
- **acionador:** intent `abrir aplicativo` (IntentRecognizer)
- **efeito:** ação externa
- **exige_confirmacao:** sim
- **dependencias:** PermissionManager; ActionExecutor; ActionVerifier; configuração `runtime.real_actions_enabled`
- **executor:** `ActionExecutor.execute_real()` (`shell=False`, allowlist de caminhos) + verificação via `tasklist` com `timeout=5`
- **limitacoes:** somente alvo Obsidian (allowlist estrita); simulação por padrão; sem comandos arbitrários; alvo desconhecido passa por fluxo de esclarecimento sem criar plano executável
- **origem_autorizacao:** allowlist da V0 (`PermissionManager.ALLOWED_ACTIONS` / `ALLOWED_TARGETS`); DEC-008; `runtime.real_actions_enabled` (default `false`)
- **status:** ativa (execução real condicionada à configuração local)

### 6. capability — listar_aliases

- **id:** `listar_aliases`
- **tipo:** capability
- **acionador:** intent `listar aliases` (IntentRecognizer)
- **efeito:** leitura
- **exige_confirmacao:** não
- **dependencias:** AliasManager; configuração local `config.json`
- **executor:** `Orchestrator` → `AliasManager.list_aliases()`
- **limitacoes:** não modifica `config.json`; lista vazia retorna mensagem padrão
- **origem_autorizacao:** DEC-008 (leitura no escopo); allowlist `ALLOWED_TARGETS` do PermissionManager para as operações de escrita irmãs
- **status:** ativa

### 7. capability — adicionar/excluir/substituir_alias

- **id:** `gerenciar_alias`
- **tipo:** capability
- **acionador:** intents `adicionar alias` / `excluir alias` / `substituir alias` (IntentRecognizer) + fluxo conversacional multi-turno
- **efeito:** escrita
- **exige_confirmacao:** sim (por etapa; persistência somente após “sim”)
- **dependencias:** AliasManager; ConfirmationHandler; PermissionManager (validação de alvo autorizado)
- **executor:** `Orchestrator._handle_alias_flow()` / `_handle_delete_alias_flow()` / `_handle_replace_alias_flow()` → `AliasManager.add_alias()` / `remove_alias()` / `replace_alias()`
- **limitacoes:** sem fuzzy matching; sem nova allowlist; alias não concede autorização; estado temporário limpo em todos os caminhos; alvo não autorizado rejeitado
- **origem_autorizacao:** allowlist `ALLOWED_TARGETS` (PermissionManager); DEC-008; padrão de fluxo da SKILL-001
- **status:** ativa

### 8. interpretação — classificar_intencao_ia

- **id:** `classificar_intencao_ia`
- **tipo:** interpretação
- **acionador:** `AICore.classify()` antes do IntentRecognizer, quando `ai.enabled=true`
- **efeito:** n/a
- **exige_confirmacao:** n/a
- **dependencias:** OllamaProvider (loopback `127.0.0.1:11434`, timeout 90s, sem proxy); configuração `ai.*`
- **executor:** `AICore` (fronteira de validação de schema); falha ou rejeição retorna `None` e aciona o fallback determinístico do IntentRecognizer
- **limitacoes:** desabilitada por padrão (`ai.enabled=false`); schemas fechados; sem tools/function calling; sem streaming; sem retry; sem inferência na inicialização
- **origem_autorizacao:** DEC-030 (provider local-first Ollama)
- **status:** implementada, inativa em runtime (configuração padrão)

### 9. skill — SKILL-002 planejar_dia

- **id:** `SKILL-002 planejar_dia`
- **tipo:** skill
- **acionador:** intent `planejar dia` (IntentRecognizer) → `Orchestrator` → `get_skill("SKILL-002")`
- **efeito:** leitura
- **exige_confirmacao:** não
- **dependencias:** CalendarAdapter; SecondBrainReader injetado, não utilizado nesta versão
- **executor:** `PlanDaySkill.execute()` (`therion/skills/plan_day.py`)
- **limitacoes:** estado Em teste, não Ativa; consulta somente o calendário; sem notas pessoais de tarefas; sem LLM; `search_notes` nunca chamado; toda saída termina com aviso read-only
- **origem_autorizacao:** DEC-028 (arquitetura híbrida); autorização do usuário para estado Em teste; definição oficial na nota `SKILL-002 — Planejar meu dia`
- **status:** em_teste (não bloqueia o fechamento da V1)

---

## Relação Skill → capabilities por apontamento

Relação factual atual. A Skill consome a capability; a capability não
referencia Skills. Esta relação não cria nova rota, não cria Registry,
não concede permissão e não altera o estado da Skill.

- **SKILL-002 planejar_dia** → capability de consulta de calendário usada
  para o planejamento do dia (`consultar_calendario_hoje`, via
  `CalendarAdapter.list_events_for_day`).
