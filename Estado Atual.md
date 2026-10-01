# Therion — Estado Atual

> Resumo operacional do estado real do projeto Therion.

Esta nota deve refletir apenas o estado atual do projeto.

Planos futuros ficam em [[Roadmap]].
Decisões importantes ficam em [[Decisões]].
Detalhes conceituais ficam em [[Arquivo Mestre do Projeto]].
Detalhes técnicos ficam em [[Arquitetura]].

---

## Status geral

**Fase atual:** V1 — Concluída (fase pós-V1)

O conceito do Therion teve seu ciclo básico implementado e validado com sucesso no Windows através do teste simbólico de abertura do Obsidian de ponta a ponta (V0 concluída).

As decisões técnicas principais da V1 foram aprovadas (interface PySide6, processo persistente, configuração JSON, Skills híbridas, calendário Google). A implementação da V1 segue de forma incremental.

### Progresso da V1
- ✅ Interface conversacional (UI-1 desktop concluída)
- ✅ Memória de sessão + contexto operacional
- ✅ Calendário — consulta/leitura
- ✅ Calendário — criação com confirmação
- ✅ IA central local-first (Marco A2 concluído)
- 🧪 SKILL-002 — Planejar meu dia integrada, validada manualmente e Em teste (panorama read-only da agenda)
- ✅ E1 — Planos conversacionais efêmeros na sessão (DEC-034): M9 validada, M10 aprovada manualmente para planos de tamanho normal e M11 auditada; checkpoints `fe0f1e4`, `6c78343` e `001e2d4`. Planos muito extensos seguem adiados em nota própria.
- ✅ Interface responsiva durante comandos demorados: checkpoint `3333cc2`; envio e confirmação usam workers Qt, sem segundo envio durante o processamento. Validada manualmente; 206 testes focados passaram na validação anterior ao commit.
- 🧪 V2.1 — Voz: piloto isolado de transcrição local em andamento, ainda sem integração ao Therion.

### Prioridade arquitetural atual

A auditoria read-only do bootstrap dos agentes e do custo de contexto foi concluída (5.1-B e 5.1-C aprovados, G1–G8 = 8/8 PASSA). O checkpoint Git principal da E1 foi realizado em `fe0f1e4`.

Ressalva de integridade da baseline: o repositório ainda possui falha preexistente em `read_scope`, portanto NÃO deve ser declarado globalmente verde.

A V2 — Voz entrou em avaliação prática isolada. `Planejamento da V2 - Voz.md` registra a política conceitual; nenhum caminho de voz foi integrado ao Therion. O piloto com microfone teve boa latência, mas precisão parcial em verbos de comando, exigindo transcrição editável e envio manual antes de qualquer execução.

O próximo passo da V2.1 é testar revisão e cancelamento no piloto isolado e então decidir o menor escopo de integração. Em frente separada, o usuário ainda precisa escolher explicitamente uma pasta ou nota pessoal como fonte autorizada de tarefas para a SKILL-002.

### Progresso da V1 validado até o momento

- Ambiente virtual criado (`.venv/`)
- PySide6 6.11.2 instalado e validado
- Primeira janela desktop criada (`therion/interface/desktop.py`)
- Teste manual da janela aprovado: título "Therion", tamanho 800x600, fechamento normal pelo botão X
- 69 testes totais passando (55 V0 + 9 config + 5 integração desktop, regressão zero)
- `QSystemTrayIcon` implementado e validado
- Ícone na bandeja do Windows funcionando
- Menu do tray com "Abrir Therion" e "Encerrar Therion" operacionais
- Persistência na bandeja implementada e validada manualmente
- Fechar pelo X oculta a janela; processo permanece ativo
- Reabertura via "Abrir Therion" validada
- Encerramento explícito via "Encerrar Therion" validado (remove tray, encerra processo)
- Módulo `therion/config` criado (`__init__.py`, `local.py`)
- Configuração padrão definida: `ui.start_minimized`, `aliases`, `allowed_apps`
- Caminho padrão: `%APPDATA%\Therion\config.json`
- Fallbacks validados: arquivo inexistente, JSON inválido, campos inválidos → defaults seguros
- Campos desconhecidos preservados (não interpretados)
- Persistência atômica (tempfile + os.replace); falha mantém original intacto
- 9 testes de configuração adicionados
- Integração de `ui.start_minimized` concluída e validada manualmente
- `start_minimized=false` → janela visível + tray
- `start_minimized=true` → inicia no tray, janela oculta
- Reabertura via "Abrir Therion" validada
- 5 testes de integração desktop adicionados
- AliasManager implementado e testado (CRUD seguro com proteção interna)
- Fluxo IntentRecognizer → AliasManager → PermissionManager → Orchestrator validado
- Comando conversacional de listagem de aliases implementado: "Therion, liste meus aliases"
- IntentRecognizer reconhece o comando e variações (liste, lista, mostre, exiba, apelidos)
- Orchestrator consulta AliasManager.list_aliases() e formata resposta
- Operação é somente leitura: nenhum alias é criado, removido ou alterado
- config.json não é modificado pelo comando de listagem
- Lista vazia tratada com mensagem clara "Nenhum alias cadastrado."
- Lista com um ou múltiplos aliases formatada corretamente
- Comandos anteriores (abrir aplicativo) continuam funcionando
- 16 novos testes adicionados para o comando de listagem
- Total atual: 130 testes passando (114 anteriores + 16 novos)
- Comando conversacional de adicionar alias implementado: "Therion, adicione um alias"
- Fluxo conversacional validado: inicia → pergunta palavra-chave → pergunta alvo → valida alvo autorizado → pede confirmação → persiste somente após "sim"
- AliasManager.add_alias() reutilizado para persistência segura
- Resposta "não" cancela sem escrever no config.json
- Resposta ambígua pede confirmação novamente
- Alias existente não é sobrescrito (proteção interna do AliasManager)
- Chave vazia e alvo vazio rejeitados
- Alvo não autorizado (ex: Notepad) rejeitado — validação via ALLOWED_TARGETS existente
- Nenhuma persistência ocorre antes da confirmação explícita
- 19 novos testes adicionados para o comando de adicionar
- Total atual: 149 testes passando (130 anteriores + 19 novos)
- Comando conversacional de excluir/remover alias implementado: "Therion, exclua um alias" / "Therion, remova um alias"
- Fluxo conversacional validado: inicia → pergunta qual alias → verifica existência → mostra alias e alvo → pede confirmação → remove somente após "sim"
- AliasManager.remove_alias(..., confirm=True) reutilizado para remoção segura
- Resposta "não" cancela sem escrever no config.json
- Resposta ambígua pede confirmação novamente
- Alias inexistente informado claramente sem alteração no config.json
- Nenhuma persistência ocorre antes da confirmação explícita
- Somente o alias escolhido é removido
- 18 novos testes adicionados para o comando de excluir
- Total atual: 167 testes passando (149 anteriores + 18 novos)
- Comando conversacional de substituir alias implementado: "Therion, substitua um alias" / "Therion, altere um alias" / "Therion, troque um alias"
- Fluxo conversacional validado: inicia → pergunta qual alias → verifica existência → mostra alvo atual → pergunta novo alvo → valida autorização → pede confirmação → substitui somente após "sim"
- AliasManager.replace_alias(..., confirm=True) reutilizado para substituição segura
- Resposta "não" cancela sem escrever no config.json
- Resposta ambígua pede confirmação novamente
- Alias inexistente informado claramente sem alteração no config.json
- Novo alvo não autorizado bloqueado — validação via ALLOWED_TARGETS existente
- Estado temporário limpo em todos os caminhos (sucesso, cancelamento, erro)
- Nenhuma persistência ocorre antes da confirmação explícita
- 26 novos testes adicionados para o comando de substituir
- Marco anterior: 193 testes passando (167 anteriores + 26 novos)
- Fluxo de alvo desconhecido implementado: "Therion, abra o [alvo não autorizado]"
- Quando o usuário pede para abrir um alvo sem alias e não autorizado, o Therion inicia um fluxo de esclarecimento
- Pergunta ao usuário o que o alvo significa
- Valida a explicação usando a allowlist/permissão existente
- Se o alvo explicado for autorizado, mostra a associação proposta e pede confirmação explícita
- Somente após "sim" chama AliasManager.add_alias() — sem parâmetro confirm
- "não" cancela sem persistência
- Resposta ambígua mantém o estado e solicita confirmação novamente
- Alvo explicado não autorizado é rejeitado
- O fluxo limpa todo estado temporário após sucesso, cancelamento ou erro
- Nenhum alias concede nova autorização
- Nenhum catálogo de aplicativos, fuzzy matching ou nova allowlist foi criado
- Testes antigos que esperavam "forbidden" no Orchestrator foram atualizados para o novo comportamento de esclarecimento
- PermissionManager continua bloqueando diretamente alvos não autorizados
- Nenhum alvo não autorizado gera plano executável antes do esclarecimento/autorização
- 19 novos testes adicionados para o fluxo de alvo desconhecido
- Total atual: 212 testes passando (193 anteriores + 19 novos)
- SKILL-001 usada formalmente pela primeira vez desde que entrou em estado "Em teste"
- Procedimento da SKILL-001 seguido sem necessidade de desvio
- Quebra de governança registrada: agente alterou 2 testes sem aguardar autorização durante regressão; alterações foram auditadas, eram tecnicamente coerentes e foram revisadas; falha de processo, não de lógica da SKILL-001
- Consulta explícita ao Segundo Cérebro por caminho implementada: "Therion, leia no Segundo Cérebro [caminho]"
- Nova intenção "consultar segundo cérebro" adicionada ao IntentRecognizer
- Orchestrator trata diretamente a consulta usando read_context() e SecondBrainReader.read_note()
- Leitura somente de arquivos .md dentro das raízes já autorizadas
- Path traversal continua bloqueado
- Arquivo inexistente retorna erro controlado
- Extensão inválida retorna erro controlado
- Caminho fora das raízes retorna erro de permissão controlado
- Consulta é registrada na memória de trabalho
- Não passa por resolução de alias, não cria plano, não tenta executar aplicativo
- Nenhuma escrita no Segundo Cérebro
- Nenhuma expansão de allowed_roots
- Nenhuma busca automática, semântica, embedding, banco de dados ou LLM
- therion/context/second_brain.py precisou receber o novo método search_notes() — API existente de read_note() foi suficiente para leitura por caminho, mas busca textual exigiu extensão mínima
- SKILL-001 não foi utilizada — fluxo somente leitura sem confirmação/persistência
- 11 novos testes adicionados para a consulta ao Segundo Cérebro
- Total atual: 223 testes passando (212 anteriores + 11 novos)
- Busca textual simples e explícita no Segundo Cérebro implementada: "Therion, procure no Segundo Cérebro [termo]"
- Nova intenção "buscar segundo cérebro" adicionada ao IntentRecognizer
- Comandos suportados: "Therion, procure no Segundo Cérebro Aetherion", "Therion, busque no Segundo Cérebro Aetherion", "Therion, pesquise no Segundo Cérebro Aetherion"
- Busca somente dentro de allowed_roots
- Somente arquivos .md
- Busca literal e case-insensitive
- Procura termo no nome do arquivo e no conteúdo
- Máximo de 5 resultados por busca
- Snippet de até 200 caracteres por resultado
- Se termo está apenas no nome: retorna indicação "[Correspondência no nome do arquivo]"
- Se termo está no conteúdo: retorna trecho ao redor da primeira ocorrência
- Erro de leitura em um arquivo não aborta a busca inteira
- Symlinks não permitem escape das raízes autorizadas (followlinks=False)
- Consulta por caminho existente continua funcionando normalmente
- Busca não passa por alias/planner/executor
- Sem fuzzy matching, sem regex fornecida pelo usuário, sem stemming
- Sem embeddings, sem LLM, sem banco vetorial, sem indexação persistente
- Sem escrita no Segundo Cérebro, sem expansão de allowed_roots
- 19 novos testes adicionados para a busca textual
- Total atual: 242 testes passando (223 anteriores + 19 novos)
- Teste manual 1 aprovado: "Therion, procure no Segundo Cérebro Aetherion" retornou 4 resultados com caminhos e snippets corretos
- Teste manual 2 aprovado: leitura direta de Estado Atual.md por caminho retornou conteúdo correto
- Melhoria da apresentação dos snippets da busca textual implementada
- Função auxiliar privada _build_snippet() adicionada em therion/context/second_brain.py
- Snippets agora evitam, quando possível, começar ou terminar no meio de palavras
- Quebras de linha, tabs e múltiplos espaços são normalizados com " ".join(snippet.split())
- "..." é adicionado no início/fim quando há conteúdo anterior/posterior omitido
- O termo encontrado permanece dentro do snippet
- Conteúdo curto não recebe "..." desnecessário
- Se o termo aparecer no conteúdo, snippet do conteúdo tem prioridade sobre match no nome
- "[Correspondencia no nome do arquivo]" é usada somente quando há match no nome e não no conteúdo
- Lógica de busca, allowed_roots, máximo de 5 resultados e IntentRecognizer não foram alterados
- Nenhuma mudança arquitetural; sem ranking, embeddings, LLM ou busca semântica
- 11 novos testes de apresentação de snippets adicionados
- 15 testes existentes de busca também revalidados
- Total atual: 253 testes passando (242 anteriores + 11 novos)
- Teste manual 3 aprovado: "Therion, procure no Segundo Cérebro Therion" retornou 5 resultados com prioridade de conteúdo validada
- Teste manual 4 aprovado: "Therion, procure no Segundo Cérebro Codex.md" retornou 1 resultado com match somente no nome
- Alguns snippets ainda exibem elementos de Markdown bruto (crases, marcadores) — isso não é bug deste incremento; limpeza/renderização de Markdown deve ser tratada separadamente se necessário
- Integração da interface desktop PySide6 com o Orchestrator implementada
- Interface agora possui: área de histórico/respostas, campo de entrada de comandos, botão "Enviar", Enter envia comando
- Comandos são enviados para Orchestrator.process_command() e respostas aparecem na própria janela
- Histórico permanece visível durante a sessão; campo de entrada é limpo após envio
- Interface continua com system tray e comportamento existente de ocultar/reabrir
- Confirmação externa da UI implementada com estado temporário _pending_plan
- ConfirmationHandler.evaluate_response() reutilizado para interpretação de "sim"/"não"
- Resposta ambígua mantém a confirmação pendente e pede "sim" ou "não"
- Enquanto houver _pending_plan, nova entrada não é interpretada como novo comando
- Confirmação ou cancelamento limpa _pending_plan; exceção durante confirm_and_execute() também limpa
- SKILL-001 aplicada ao fluxo de _pending_plan da interface desktop (estado, confirmação, execução/cancelamento, limpeza)
- Fluxos conversacionais internos do Orchestrator não foram duplicados pela UI
- Interface usa Orchestrator(simulate=True); nenhuma aplicação real é aberta pela UI nesta etapa
- Execução real pela UI ainda NÃO foi habilitada
- Threading/workers ainda NÃO foram implementados (limitação conhecida)
- Testes de desktop ampliados; suíte completa: 274 testes
- 274/274 passando; 0 falhas; nenhuma regressão
- Warning conhecido/controlado: teste que simula falha no log de auditoria ("Disk full")
- Testes manuais da interface aprovados:
  - Teste 1: "Therion, liste meus aliases" → "Nenhum alias cadastrado." (comando normal)
  - Teste 2: "Therion, procure no Segundo Cérebro Aetherion" → busca retornou 4 resultados
  - Teste 3: "Therion, abra o Obsidian" → confirmação → "s" → execução simulada concluída
  - Teste 4: "Therion, abra o Obsidian" → "talvez" → confirmação permaneceu pendente
  - Teste 5: após "talvez", "não" → operação cancelada corretamente
  - Teste 6: após cancelamento, "liste meus aliases" → voltou ao fluxo normal
  - Mensagens permaneceram no histórico; campo de entrada foi limpo corretamente
- Governança: Regra 13 "Transição entre análise e execução" criada e auditada cruzadamente
- Princípios: aprovação de plano ≠ autorização; AGUARDANDO AUTORIZAÇÃO é estado bloqueado; respostas vagas não autorizam; ausência de proibição não é autorização; autorização vale somente para o escopo
- Regra 13 classificada como CONSISTENTE — nenhuma correção necessária
- Configuração `runtime.real_actions_enabled` implementada em `therion/config/local.py`
- Default continua `False`; ações reais não ficam habilitadas automaticamente
- Validação robusta: config inexistente, runtime ausente, tipo inválido → False seguro
- Somente boolean `True` explícito preserva `True`
- Interface desktop (`therion/interface/desktop.py`) agora usa `real_actions_enabled` para configurar `Orchestrator(simulate=not real_actions_enabled)`
- Verifier (`therion/actions/verifier.py`) agora usa `timeout=5` em `subprocess.run` para `tasklist`
- `subprocess.TimeoutExpired` tratado como falha controlada; exceção não escapa; `VerificationResult(success=False, ...)` retornado
- `shell=False` preservado em todas as chamadas de subprocess
- 290 testes passando (274 anteriores + 16 novos); 0 failures; 0 errors
- Testes específicos para `timeout=5` e `TimeoutExpired` adicionados em `tests/test_real_actions.py`
- Testes de config cobrem `runtime.real_actions_enabled` (default, ausente, inválido, True/False)
- Testes de desktop cobrem `simulate` baseado na config
- Teste manual controlado realizado com `real_actions_enabled=true`:
  - Therion apresentou o plano de abrir Obsidian
  - Exigiu confirmação
  - Após confirmação "sim", abriu Obsidian de verdade
  - ActionVerifier confirmou `Obsidian.exe` ativo via `tasklist`
  - Teste real concluído com sucesso
  - Após o teste, `real_actions_enabled` foi devolvido para `False`
- Inicialização desktop independente do terminal validada manualmente:
  - `.venv\Scripts\pythonw.exe -m therion.interface.desktop` inicia sem CMD/terminal visível
  - Pode iniciar diretamente na bandeja quando `start_minimized=true`
  - Fechar a janela mantém Therion ativo na bandeja
  - Ícone da bandeja restaura a janela
  - "Encerrar Therion" encerra o aplicativo
  - Não é necessário manter CMD aberto
- `opencode.json` adicionado e versionado com política fail-closed de permissões
- Leitura e `git status`/`diff`/`log` permanecem fluidos sem prompt
- Edição e comandos protegidos exigem autorização técnica
- `git push` é bloqueado pela política
- Isso complementa a Regra 13 com uma barreira técnica adicional
- Atalho do Windows `Therion.lnk` criado e validado na Área de Trabalho visível:
  - Local: `C:\Users\marcu\OneDrive\Área de Trabalho\Therion.lnk`
  - Target: `C:\Users\marcu\Downloads\Segundo-Cerebro\10 - Projetos\Therion\.venv\Scripts\pythonw.exe`
  - Arguments: `-m therion.interface.desktop`
  - WorkingDirectory: `C:\Users\marcu\Downloads\Segundo-Cerebro\10 - Projetos\Therion`
- Teste manual do atalho concluído com sucesso:
  - Therion abre pelo atalho
  - Nenhum CMD/terminal fica visível
  - Therion permanece ativo na bandeja
  - Janela pode ser restaurada pelo ícone da bandeja
  - Fechar a janela não encerra o Therion
  - "Encerrar Therion" encerra corretamente
  - Não é mais necessário usar terminal para iniciar o Therion no uso normal
- Limitações conhecidas do atalho:
  - Depende do caminho atual do projeto
  - Depende da .venv existente nesse caminho
  - Se o projeto ou .venv forem movidos, o atalho precisará ser atualizado
  - Empacotamento em executável próprio ainda não foi feito e não é necessário nesta etapa
- Memória de sessão + contexto operacional implementada e validada:
  - `Turn` dataclass com `role: Literal["user", "therion"]` e `text: str`
  - Memória de turnos em RAM via `deque(maxlen=50)`
  - Campos `last_intent`, `last_target`, `last_result`, `last_status` na `WorkingMemory`
  - API: `add_turn()`, `recent_turns(n)`, `clear_session()`
  - Orchestrator é a fonte de verdade: registra turnos em `process_command()` e `confirm_and_execute()`
  - UI não escreve diretamente na WorkingMemory
  - CLI e desktop compartilham a mesma memória via Orchestrator
  - Memória de sessão não substitui `_pending_plan`, alias flows ou unknown target flow
  - Nenhum `SessionContext` dataclass; nenhum `build_context_prompt()`
  - Memória permanece somente em RAM; sem persistência em disco; sem cloud; sem LLM
  - Nenhum novo logging de Turn/last_* adicionado
  - 326 testes passando (326/326); 0 failures; 0 errors; warning controlado de "Disk full" continua esperado
  - Testes específicos de WorkingMemory (8 testes), integração Orchestrator ↔ memória (10 testes), ordem/quantidade de turns, prevenção de duplicação, preservação de contexto
  - Testes manuais aprovados:
    - Teste 1: primeira interação atualiza turns e last_* corretamente
    - Teste 2: segunda interação acumula contexto na mesma sessão
    - Teste 3: clear_session limpa turns + last_* e preserva history/current_task
    - Teste 4: novo processo começa com memória vazia (volatilidade confirmada)
- Integração de leitura com Google Calendar implementada e validada:
  - `GoogleCalendarAdapter` (`therion/calendar/google_adapter.py`) usando `calendarId="primary"`
  - Autenticação OAuth2 (`therion/calendar/auth.py`) implementada e validada com sucesso; `credentials.json` e `token.json` armazenados com segurança fora do repositório em `%APPDATA%\Therion\`
  - Configuração do usuário validada: `calendar.enabled=true`, `calendar.time_zone=America/Sao_Paulo`
  - Consulta real validada pela interface desktop; diagnóstico técnico real também validado diretamente via GoogleCalendarAdapter
  - Comando conversacional validado: "Therion, o que tenho hoje?"
  - Eventos reais retornados corretamente pela interface desktop
  - Operação estritamente de leitura (somente consulta); nenhuma criação, edição ou exclusão de evento nesta etapa
  - Correção de fuso horário no Windows:
    - `ZoneInfo("America/Sao_Paulo")` inicialmente falhava no Windows por falta de banco de dados de fuso horário no sistema;
    - `tzdata` (2026.4) foi instalado no `.venv` e registrado como dependência no `requirements.txt` (encoding UTF-16 LE preservado);
    - Fallback silencioso para UTC foi completamente removido;
    - Fuso horário inválido agora gera `CalendarError` controlado;
    - Janela de busca real validada: `00:00:00-03:00` (início do dia) até `00:00:00-03:00` (início do dia seguinte);
  - Política de segurança do OpenCode (`opencode.json`) refinada para permitir permanentemente leitura e organização (`read`, `glob`, `grep`, `todowrite`, `git status*`, `git diff*`, `git log*`), mantendo escrita/execução protegidas (`ask`) e `git push*` bloqueado (`deny`);
  - Suíte de testes automatizados: 394/394 testes passando (0 failures, 0 errors; warning controlado de "Disk full" continua esperado).
- Interface desktop UI-1 concluída e validada visual e tecnicamente:
  - Interface desktop própria em PySide6 com identidade visual preto (`#0d0d0d`) + laranja (`#ff6a00`);
  - Orbe com estados visuais (`idle`, `thinking`, `executing`, `awaiting_confirmation`, `completed`, `error`, `cancelled`) e rótulo de estado integrado na barra superior;
  - Histórico de mensagens estruturado em balões (usuário à direita com fundo escuro alaranjado; Therion à esquerda com fundo escuro neutro);
  - Painel compacto de confirmação com botões "Confirmar" e "Cancelar" integrados, reutilizando o fluxo seguro existente de confirmação;
  - Status inferior redundante removido (estado consolidado junto ao orbe);
  - Entrada de texto com `Enter` para envio e `Shift+Enter` para quebra de linha;
  - Arquitetura funcional preservada sem nenhuma execução direta na UI (Orchestrator, AICore, Planner, Executor, PermissionManager, calendário, memória e system tray intactos);
  - Regressão final: 504/504 testes passando, 0 failures, 0 errors (incluindo 82 testes de interface/integração desktop).
- IA central local-first (Marco A2) implementada e validada de ponta a ponta:
  - `OllamaProvider` concreto (`therion/core/ai_provider_ollama.py`) utilizando API HTTP local (`http://127.0.0.1:11434/api/chat`) via `urllib.request` da biblioteca padrão;
  - Proxy desabilitado explicitamente com `ProxyHandler({})`;
  - Bloco de configuração `ai` em `therion/config/local.py` com `enabled: false` por padrão, timeout padrão de 90 segundos e modelo inicial/candidato validado `qwen3:4b-instruct`;
  - Request estruturada com format schema rígido (`type`, `message`, `intent`, `arguments`), `temperature: 0` e `num_ctx: 2048`, sem streaming ou uso de `think`;
  - Endurecimento semântico do `AICore`: validação universal de `message` não vazia, rejeição de respostas híbridas para `chat` e `clarification` (`intent is None` e `arguments == {}`) e validação estrita de schemas fechados para as 5 actions canônicas da allowlist;
  - Fallback determinístico preservado: qualquer falha de transporte, HTTP não-200 ou rejeição de validação faz `AICore.classify()` retornar `None`, acionando o fluxo determinístico existente no `Orchestrator`;
  - Injeção na interface desktop (`MainWindow._build_ai_core`) sem nenhuma inferência durante a inicialização (inicialização limpa);
  - Regressão técnica final: 547/547 testes passando (0 failures, 0 errors);
  - Validação manual de ponta a ponta concluída: chat local informativo, clarification para comando ambíguo, action com apresentação de plano e confirmação explícita, e cancelamento seguro sem ação externa;
  - Configuração local ativa restaurada com segurança para `ai.enabled=false`.

---

## O que já está definido

### Visão

- Therion será uma IA pessoal contextual.
- Funcionará inicialmente no Windows.
- O Segundo Cérebro será sua principal memória persistente.
- A arquitetura será modular.
- A interação inicial será por texto.
- Voz está planejada para a V2.
- Therion poderá futuramente utilizar ferramentas, integrações, Skills e agentes especializados.

### Governança

Já existem regras universais para:

- autonomia;
- permissões;
- confirmação;
- inicialização;
- privacidade;
- mínimo contexto necessário;
- escrita permanente;
- aprendizado com erros;
- Skills;
- agentes;
- conhecimento temporário;
- evolução gradual de autonomia.

Therion deve obedecer ao Sistema da IA localizado em:

`90 - Sistema da IA/`

Perfil do agente:

[[90 - Sistema da IA/Agentes/Therion]]

### Fluxo principal

O fluxo conceitual aprovado é:

Receber
→ Entender
→ Buscar contexto
→ Planejar
→ Mostrar mini-plano
→ Verificar permissões
→ Executar
→ Verificar resultado
→ Interpretar
→ Responder

### Memória

Estão definidos dois tipos principais:

- memória persistente: Segundo Cérebro;
- memória de trabalho: contexto temporário da tarefa.

Conhecimento temporário não deve ser automaticamente promovido para conhecimento oficial.

### Skills

O sistema de Skills já está definido conceitualmente no Sistema da IA.

Skills serão utilizadas para procedimentos recorrentes e reutilizáveis.

### Agentes

Já existem perfis para:

- Codex;
- Gemini (Estado oficial: "Em teste" — atuando como agente de apoio ao desenvolvimento do Therion);
- Therion.

### Linguagem da V0

- Python foi aprovado como linguagem principal da V0 (ver [[Decisões#DEC-023 — Linguagem principal da V0|DEC-023]]). Frameworks e bibliotecas permanecem em aberto.

---

## Primeiro objetivo técnico

Construir a **V0 — Prova de Conceito**.

A V0 deve validar o ciclo básico:

pedido
→ interpretação
→ contexto
→ plano
→ permissão
→ execução
→ verificação
→ resposta

Teste simbólico principal:

> "Therion, abra o Obsidian."

### Status do teste simbólico: Validado com sucesso

O teste simbólico principal foi executado e aprovado com evidências reais no Windows:

- **Execução real controlada:** Obsidian iniciado a partir de allowlist restrita de caminhos seguros, sem comandos arbitrários e com `shell=False`.
- **Verificação comprovada:** Processo `Obsidian.exe` detectado e verificado como ativo via utilitário nativo de processos (`tasklist`).
- **Ciclo completo validado:** Recepção do comando → interpretação da intenção ("abrir aplicativo") → identificação do alvo ("Obsidian") → geração de mini-plano de 2 etapas → verificação de permissão e governança → solicitação de confirmação (`[s/n]`) → execução real após confirmação positiva → verificação do processo → resposta informativa.
- **Cancelamento seguro:** Confirmação negativa testada com cancelamento imediato sem efeitos no sistema.
- **Bloqueio de alvos não autorizados:** Tentativas de abertura de outros aplicativos bloqueadas sumariamente como não autorizadas pela governança.
- **Bateria de testes automatizados:** 55 testes unitários aprovados (100% OK), cobrindo importações, fluxo lógico, ações simuladas/mockadas, memória de trabalho, leitura do Segundo Cérebro e auditoria técnica.

---

## Ainda não implementado ou não validado

Componentes já validados na V0 e V1:

- núcleo/orquestrador básico de fluxo;
- executor controlado de ações (allowlist restrita ao Obsidian);
- verificador de processos ativos no Windows (com `timeout=5`);
- sistema técnico de permissões (allowlist);
- sistema técnico de confirmação obrigatória;
- interface CLI textual simples;
- interface desktop PySide6 com system tray;
- configuração local JSON com validação robusta;
- `runtime.real_actions_enabled` com default False;
- inicialização independente do terminal via `pythonw.exe`;
- inicialização prática via atalho do Windows (`Therion.lnk`);
- política fail-closed de permissões via `opencode.json` (com leitura/organização fluidas autorizadas);
- memória de sessão + contexto operacional (Turn, last_*, recent_turns, clear_session);
- integração básica com Google Calendar (consulta/leitura de eventos de hoje via comando conversacional com OAuth e fuso horário estrito);
- IA central local-first (OllamaProvider via loopback, modelo qwen3:4b-instruct, format schema e AICore endurecido).

Até que exista evidência técnica adicional, considerar como não implementado:

- Skills executáveis reutilizáveis;
- delegação automática para outros agentes;
- voz;
- automações avançadas;
- controle de computador além da prova de conceito do Obsidian.

Não marcar uma funcionalidade como implementada apenas porque ela está planejada.

---

## Próximos passos

Etapas concluídas da V0:

- [x] definir a arquitetura técnica mínima da V0;
- [x] escolher stack e linguagem principal (Python — DEC-023);
- [x] inicializar repositório Git e criar estrutura modular do código;
- [x] implementar entrada de texto simples;
- [x] implementar interpretação inicial determinística de comandos;
- [x] implementar mini-plano;
- [x] implementar confirmação obrigatória;
- [x] implementar primeira ação real controlada no Windows (Obsidian);
- [x] implementar verificação real da ação;
- [x] validar o comando "Therion, abra o Obsidian" (teste manual e 55 testes automatizados);
- [x] estruturar a memória de trabalho técnica da sessão;
- [x] implementar camada de leitura seletiva do Segundo Cérebro;
- [x] implementar logs e auditoria técnica mínima (formato JSONL, pasta logs/).

Próximas etapas para avanço da V0:

Todas as etapas previstas da V0 foram concluídas.

---

### Próximas etapas para avanço da V1

- [x] implementar `runtime.real_actions_enabled` com default False
- [x] adicionar `timeout=5` ao Verifier com tratamento de `TimeoutExpired`
- [x] validar execução real controlada via interface desktop
- [x] validar inicialização independente do terminal via `pythonw.exe`
- [x] adicionar `opencode.json` com política fail-closed de permissões
- [x] criar forma prática de iniciar o Therion no Windows sem terminal
- [x] implementar memória de sessão + contexto operacional (Turn, last_*, recent_turns, clear_session)
- [x] implementar integração básica com calendário (consulta/leitura de eventos via Google Calendar)
- [x] corrigir tratamento de timezone e adicionar `tzdata`
- [x] refinar permissões de leitura no `opencode.json`
- [x] implementar criação de eventos no calendário mediante confirmação explícita
- [x] implementar interface visual UI-1 (PySide6, tema preto + laranja, orbe de estados, balões, confirmação compacta)
- [x] implementar IA central local-first com provider real (Marco A2 concluído)

---

### Próxima meta principal

**Iniciar a V2 — Voz.**

Próxima etapa funcional principal:
- **V2 — Voz.**

Funcionalidade da V1 encerrada como pendência controlada:
- SKILL-002 — Planejar meu dia: integrada, estado Em teste e não bloqueia o fechamento.

Ainda NÃO implementados:

- Skills executáveis reutilizáveis
- delegação automática para outros agentes
- voz
- automações avançadas

---

## Pendências de decisão

As seguintes decisões foram tomadas durante a implementação da V0 (marcadas como resolvidas):

- [x] framework/interface inicial → CLI textual simples
- [x] modelo/API de IA utilizado → não integrado na V0 (decisão explícita)
- [x] estratégia de acesso ao Segundo Cérebro → leitura seletiva autorizada
- [x] formato da memória de trabalho → estrutura técnica de sessão implementada
- [x] mecanismo de execução de ações no Windows → executor controlado com allowlist
- [x] mecanismo de verificação → verificação de processo via tasklist
- [x] armazenamento de configurações → configuração local simples
- [x] estrutura do repositório → estrutura modular Python definida
- [x] forma de integração entre Therion e agentes externos → delegação com contexto/permissões mínimos

Esses itens não são mais pendências ativas. Novas decisões para a V1 serão registradas conforme necessário.

---

## Regra de atualização

Esta nota deve ser atualizada quando ocorrer mudança relevante no estado real do projeto.

Ao atualizar:

- registrar somente o estado atual;
- não transformar plano em implementação;
- não declarar sucesso sem validação;
- mover histórico relevante para local apropriado;
- evitar acumular registros antigos nesta nota.

---

## Última referência de estado

Projeto conceitualmente estruturado.

Governança universal definida.

Segundo Cérebro preparado.

Gemini oficializado com estado "Em teste" como agente de apoio.

Python aprovado como linguagem principal da V0 (DEC-023).

Marco da V0 alcançado: ciclo completo do teste simbólico "Therion, abra o Obsidian" validado no Windows com 55 testes automatizados e teste manual bem-sucedido.

Teste final de aceitação da V0 concluído com sucesso: comando "Therion, abra o Obsidian" executado em ambiente real no Windows, com abertura e verificação do processo confirmadas.

Decisões técnicas principais da V1 aprovadas: Interface (PySide6), Processo persistente (mesmo processo, system tray), Configuração local (JSON), Skills (arquitetura híbrida), Calendário (Google Calendar API com adapter).

Próxima etapa principal:

**V1 encerrada. Próxima etapa principal: V2 — Voz.**

Marco da V1 alcançado: fluxo de alvo desconhecido implementado e validado com 212 testes automatizados (212/212 passando). SKILL-001 aplicada e avaliada positivamente em seu primeiro uso prático formal; permanece em estado Em teste.

Marco da V1 alcançado: consulta explícita ao Segundo Cérebro por caminho implementada e validada com 223 testes automatizados (223/223 passando). API existente de SecondBrainReader foi suficiente sem alterações.

Marco da V1 alcançado: busca textual simples e explícita no Segundo Cérebro implementada e validada com 242 testes automatizados (242/242 passando). Método search_notes() adicionado ao SecondBrainReader. Teste manual aprovado no CLI.

Marco da V1 alcançado: melhoria da apresentação dos snippets da busca textual implementada e validada com 253 testes automatizados (253/253 passando). Função _build_snippet() adicionada. Testes manuais aprovados no CLI.

Marco da V1 alcançado: integração da interface desktop PySide6 com o Orchestrator implementada e validada com 274 testes automatizados (274/274 passando). Interface funcional para entrada e resposta de comandos. Testes manuais aprovados. Execução ainda simulada (simulate=True).

Marco da V1 alcançado: configuração `runtime.real_actions_enabled` implementada e validada com 290 testes automatizados (290/290 passando). Execução real controlada validada via teste manual. Verifier com `timeout=5` e tratamento de `TimeoutExpired`. Inicialização via `pythonw.exe` validada. `opencode.json` com política fail-closed adicionado.

Marco da V1 alcançado: atalho do Windows `Therion.lnk` criado e validado na Área de Trabalho visível. Therion inicia sem terminal, permanece na bandeja, pode ser restaurado e encerrado corretamente. Não é mais necessário usar terminal para iniciar o Therion no uso normal.

Marco da V1 alcançado: integração de leitura do Google Calendar implementada e validada de ponta a ponta com 394 testes automatizados (394/394 passando, 0 failures, 0 errors). Fluxo OAuth funcional armazenando `credentials.json` e `token.json` em `%APPDATA%\Therion\`. Comando "Therion, o que tenho hoje?" retorna eventos reais na interface desktop. Correção do fuso `America/Sao_Paulo` validada com dependência `tzdata` e limites de busca `00:00:00-03:00`.

Marco de governança alcançado: `opencode.json` refinado para permitir permanentemente leitura e organização (`read`, `glob`, `grep`, `todowrite`, `git status*`, `git diff*`, `git log*`), mantendo segurança fail-closed contra escrita/execução arbitrária e bloqueio de `git push*`.

Marco da V1 alcançado: criação de eventos no calendário com confirmação explícita implementada e validada de ponta a ponta (449 testes, 0 failures). Fluxo completo: Usuário → IntentRecognizer → Orchestrator → confirmação explícita → CalendarAdapter → GoogleCalendarAdapter → Google Calendar. OAuth real atualizado para `calendar.events.owned`. Primeiro evento real criado com sucesso ("Teste do therion", 15/09/2026 23:30–00:30, event_id retornado, consulta posterior confirma presença). Token antigo preservado como `token.json.bak.readonly`.

Marco da V1 alcançado: interface desktop UI-1 concluída e validada visual e tecnicamente de ponta a ponta (504 testes passando, 0 failures, 0 errors; 82 testes de interface/integração desktop). Nova interface PySide6 com tema preto e laranja, orbe de estados visuais, histórico em balões, painel compacto de confirmação com Confirmar/Cancelar, remoção do status inferior redundante e atalhos Enter/Shift+Enter. Arquitetura funcional e governança preservadas sem execução direta pela UI.

Marco da V1 alcançado: IA central local-first (Marco A2) implementada e validada de ponta a ponta (685 testes passando, 0 failures, 0 errors). Provider local Ollama em loopback com proxy desabilitado, modelo candidato `qwen3:4b-instruct`, format schema estruturado e schemas fechados com endurecimento no AICore com fallback determinístico, configuração `ai.enabled=false` por padrão e injeção desktop sem inferência na inicialização. Validação manual concluída para chat, clarification e action confirmada.

Marco de governança alcançado: Camada Zero implementada e validada (5.1-B e 5.1-C aprovados, G1–G8 = 8/8 PASSA). Checkpoint Git deliberadamente adiado porque o working tree contém alterações mistas e Roadmap.md não apresentou fronteira segura para checkpoint completo da Camada Zero.

Próxima etapa principal:

**V2.1 — entrada por voz segura, ainda em piloto isolado.** A E1 e a interface responsiva possuem checkpoints locais; planos extensos continuam adiados. SKILL-002 permanece Em teste e a trilha pós-V1 condicionada a decisão própria.

### Frentes fechadas nesta rodada

- evento/pontuação: fechado
- confirmação/cancelamento de calendário: fechado
- recent_turns → Ollama: fechado
- abre aquilo → obsidian: fechado
- respostas curtas contextuais: fechado
- tudo → aliases: fechado
- promessa sem entrega: fechado
- orçamento Pomodoro 4A/4B: fechado
- estudo/Pomodoro → unknown_intent: fechado
- warnings de "Disk full" e autenticação de calendário: simulados/controlados em testes

### Riscos residuais conhecidos

- Lógica `text == command` em `_extract_pomodoro_budget()` pode ignorar turnos idênticos (baixo impacto)
- `abra o obsidian` pode ocasionalmente retornar do Ollama com `arguments={}` (comportamento pré-existente do modelo, não causado por esta rodada)
- Baseline global ainda possui falha preexistente em `read_scope` (não declarar o repositório globalmente verde)
- `Estado Atual.md`, `Roadmap.md`, `.opencode/` e notas de retomada/referência ainda compõem trabalho local separado; não incluí-los automaticamente em um checkpoint de código
- Pedido de plano muito extenso continua sem solução integrada; bug de esclarecimento após nome de aplicativo digitado incorretamente e rascunho de calendário ao Limpar são pendências separadas
- Consumo de RAM do aplicativo Therion: usuário observou picos ao abrir e usar o app, enquanto o piloto isolado da V2 permaneceu quase estável durante horas. É uma hipótese de problema no app, não um vazamento ou causa confirmados. Ao retomar, medir por processo a RAM ao abrir, após comandos e após alguns minutos ocioso, registrando qual ação antecede cada aumento; investigar separadamente do piloto de voz.

---

## Checkpoints recentes

- `3333cc2` — `fix(desktop): keep interface responsive during processing`
- `001e2d4` — `fix(plans): stabilize generation and session references`
- `6c78343` — `fix(desktop): clear plan session with conversation`
- `fe0f1e4` — `feat: add session plan continuity and references`
- `f260bff` — `fix(v1): correct calendar date parsing`
- `97b595f` — `feat(v1): connect calendar confirmation to event creation`
- `c1cc4cd` — `feat(v1): add calendar event creation adapter`
- `f0a2f4d` — `feat(v1): add calendar creation confirmation flow`
- `48c053e` — `chore(security): refine OpenCode read permissions`
- `029500c` — `fix(v1): correct calendar timezone handling`
- `644e97b` — `feat(v1): wire calendar oauth and desktop integration`
- `e58973b` — `feat(v1): add google calendar read-only integration`
- `1570d91` — `feat(v1): add calendar read-only core`
- `1c5696c` — `feat(v1): add session memory and operational context`
- `b9b9783` — `chore(security): add OpenCode permission guardrails`
- `1a817bb` — `feat(v1): add controlled real action configuration`
