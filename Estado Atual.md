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

**Integrar aliases de forma incremental e controlada, começando por aliases simples de aplicativos já autorizados, sem alterar ainda `allowed_apps`** conforme Roadmap e decisões aprovadas (DEC-025 a DEC-029).

Ainda NÃO integrados:
- `allowed_apps`
- geometria da janela (posição/tamanho)
- outras preferências de UI
- calendário
- Skills

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