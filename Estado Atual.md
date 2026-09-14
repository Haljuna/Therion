# Therion — Estado Atual

> Resumo operacional do estado real do projeto Therion.

Esta nota deve refletir apenas o estado atual do projeto.

Planos futuros ficam em [[Roadmap]].
Decisões importantes ficam em [[Decisões]].
Detalhes conceituais ficam em [[Arquivo Mestre do Projeto]].
Detalhes técnicos ficam em [[Arquitetura]].

---

## Status geral

**Fase atual:** V1 — Em andamento

O conceito do Therion teve seu ciclo básico implementado e validado com sucesso no Windows através do teste simbólico de abertura do Obsidian de ponta a ponta (V0 concluída).

As decisões técnicas principais da V1 foram aprovadas (interface PySide6, processo persistente, configuração JSON, Skills híbridas, calendário Google). A implementação da V1 foi iniciada de forma incremental.

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

Componentes básicos já validados no teste simbólico da V0:

- núcleo/orquestrador básico de fluxo;
- executor controlado de ações (allowlist restrita ao Obsidian);
- verificador de processos ativos no Windows;
- sistema técnico de permissões (allowlist);
- sistema técnico de confirmação obrigatória;
- interface CLI textual simples.

Até que exista evidência técnica adicional, considerar como não implementado:

- execução contínua em segundo plano;
- ícone na bandeja;
- modelos de IA / LLMs integrados;
- Skills executáveis reutilizáveis;
- integração com calendário;
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

### Próxima meta principal

**Integrar entrada e resposta de comandos na interface desktop PySide6, reutilizando o Orchestrator existente.**

Objetivo conceitual futuro:

campo de entrada → usuário envia comando → Orchestrator.process_command() → resposta → exibição na própria janela

Contexto:
- A interface PySide6 faz parte da V1
- A janela e o system tray já foram implementados e validados
- Porém a interface ainda não oferece uma forma funcional de enviar comandos ao Therion
- Atualmente o CLI continua sendo o meio funcional de interação

Essa etapa será usada para validar na prática:
- Integração entre interface desktop e Orchestrator
- Experiência de uso do Therion como aplicação real

Ainda NÃO implementados:
- campo de entrada de comandos na janela
- exibição de respostas na janela
- tratamento de erros na interface
- models de IA / LLMs integrados
- Skills executáveis reutilizáveis
- integração com calendário
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

**Implementar e validar a V1.**

Marco da V1 alcançado: fluxo de alvo desconhecido implementado e validado com 212 testes automatizados (212/212 passando). SKILL-001 aplicada e avaliada positivamente em seu primeiro uso prático formal; permanece em estado Em teste.

Marco da V1 alcançado: consulta explícita ao Segundo Cérebro por caminho implementada e validada com 223 testes automatizados (223/223 passando). API existente de SecondBrainReader foi suficiente sem alterações.

Marco da V1 alcançado: busca textual simples e explícita no Segundo Cérebro implementada e validada com 242 testes automatizados (242/242 passando). Método search_notes() adicionado ao SecondBrainReader. Teste manual aprovado no CLI.

Marco da V1 alcançado: melhoria da apresentação dos snippets da busca textual implementada e validada com 253 testes automatizados (253/253 passando). Função _build_snippet() adicionada. Testes manuais aprovados no CLI.