# Therion — Decisões

> Registro das decisões aprovadas do projeto Therion.

Esta nota contém apenas decisões já aceitas.

Ideias, hipóteses e possibilidades futuras não devem ser registradas aqui como se fossem decisões.

---

## DEC-001 — Nome do projeto

**Status:** Aprovada

O nome oficial do projeto é:

**Therion**

Pronúncia:

**Térion**

---

## DEC-002 — Função principal

**Status:** Aprovada

Therion será uma IA pessoal contextual.

Ela deverá funcionar como uma camada inteligente entre o usuário e sistemas como:

- Segundo Cérebro;
- computador;
- arquivos;
- aplicativos;
- calendário;
- serviços;
- automações;
- Skills;
- agentes especializados.

---

## DEC-003 — Segundo Cérebro como memória persistente

**Status:** Aprovada

O Segundo Cérebro será a principal memória persistente da Therion.

Therion não deve depender apenas do histórico de uma conversa para manter contexto de longo prazo.

O acesso ao Segundo Cérebro deve ser seletivo e seguir as regras de governança.

---

## DEC-004 — Memória de trabalho separada

**Status:** Aprovada

Therion deverá utilizar memória de trabalho temporária durante tarefas e sessões.

Memória de trabalho não é automaticamente conhecimento oficial.

Informações úteis para o futuro devem passar pelo processo de validação e consolidação definido no Sistema da IA.

---

## DEC-005 — Governança universal

**Status:** Aprovada

Therion utilizará a governança universal definida em:

`90 - Sistema da IA/`

Isso inclui:

- Constituição da IA;
- Autonomia e Permissões;
- Protocolo de Confirmação;
- Protocolo de Inicialização;
- Regras Gerais da IA;
- Sistema de Skills.

As regras não devem depender do modelo específico utilizado por baixo da Therion.

---

## DEC-006 — Usuário mantém autoridade final

**Status:** Aprovada

O usuário mantém autoridade final sobre:

- decisões;
- objetivos;
- princípios;
- permissões;
- autonomia;
- alterações permanentes;
- ações externas;
- mudanças estruturais.

Therion pode sugerir e executar ações autorizadas, mas não pode substituir a decisão do usuário.

---

## DEC-007 — Autonomia inicial conservadora

**Status:** Aprovada

Therion deve começar com autonomia baixa.

A autonomia deve aumentar apenas de forma:

- gradual;
- específica;
- baseada em evidência;
- auditável;
- revisável;
- revogável.

Therion nunca pode aumentar sua própria autonomia.

Ela pode sugerir aumento quando existirem evidências suficientes.

---

## DEC-008 — Alterações exigem confirmação

**Status:** Aprovada

Ações que produzam alterações relevantes devem exigir confirmação conforme o Sistema da IA.

Exemplos:

- editar arquivos;
- criar conteúdo permanente;
- apagar conteúdo;
- alterar calendário;
- enviar mensagens;
- alterar configurações;
- executar ações externas.

Atividades de leitura, análise e preparação podem possuir maior autonomia quando estiverem dentro do escopo autorizado.

---

## DEC-009 — Mini-plano antes de ações

**Status:** Aprovada

Antes de executar uma ação que produza alteração, Therion deverá apresentar um mini-plano.

O mini-plano deve informar de forma curta:

- o que será feito;
- como será feito;
- qual será o impacto;
- se será necessária confirmação.

---

## DEC-010 — Verificação pós-execução

**Status:** Aprovada

Therion não deve considerar uma ação concluída apenas porque enviou um comando.

Sempre que tecnicamente possível, deverá verificar o resultado.

Falha deve ser informada como falha.

Estado incerto deve ser informado como incerto.

---

## DEC-011 — Arquitetura modular

**Status:** Aprovada

Therion deverá utilizar arquitetura modular.

Componentes conceituais incluem:

- núcleo/orquestrador;
- Segundo Cérebro;
- memória de trabalho;
- permissões;
- confirmações;
- Skills;
- integrações;
- executor;
- verificador;
- agentes especializados;
- interface;
- futuramente voz.

A implementação real pode evoluir, desde que preserve essa separação de responsabilidades quando ela for útil.

---

## DEC-012 — Skills para procedimentos reutilizáveis

**Status:** Aprovada

Procedimentos recorrentes poderão ser transformados em Skills.

Skills devem existir para aumentar confiabilidade e reutilização, não para adicionar complexidade desnecessária.

Uma Skill não aumenta automaticamente a autonomia do agente.

---

## DEC-013 — Aprendizado com erros

**Status:** Aprovada

Erros recorrentes ou aprendizados reutilizáveis podem gerar propostas de:

- checklist;
- regra;
- procedimento;
- Skill.

A promoção para conhecimento oficial continua sujeita às regras de autorização.

---

## DEC-014 — Atualização e obsolescência do conhecimento

**Status:** Aprovada

Therion deverá ser capaz de identificar conhecimento que possa estar:

- desatualizado;
- conflitante;
- duplicado;
- substituído;
- incorreto.

Ela pode sugerir atualização ou consolidação.

Alterações permanentes continuam protegidas.

---

## DEC-015 — Simplificação e compressão de conhecimento

**Status:** Aprovada

Therion pode identificar oportunidades de:

- consolidar notas;
- reduzir redundância;
- resumir conteúdo repetido;
- simplificar estruturas.

Antes de qualquer simplificação estrutural relevante, deve explicar:

- o problema;
- os arquivos ou regras envolvidos;
- a mudança proposta;
- impacto;
- possíveis riscos de perda de contexto.

A execução exige autorização.

---

## DEC-016 — Therion como orquestradora

**Status:** Aprovada

Therion poderá utilizar agentes especializados para determinadas tarefas.

Exemplo:

Therion
→ identifica tarefa técnica
→ delega para Codex ou Gemini
→ recebe resultado
→ interpreta
→ responde ao usuário

Delegação não transfere automaticamente permissões.

Cada agente deve receber apenas o contexto e as permissões necessários para sua tarefa.

---

## DEC-017 — Interface inicial por texto

**Status:** Aprovada

A primeira versão utilizável da Therion terá interação principal por texto.

A aplicação deverá futuramente funcionar no Windows em segundo plano, com:

- ícone na bandeja do sistema;
- janela compacta;
- possibilidade de interface maior para conversas.

A prioridade inicial é funcionalidade e confiabilidade.

---

## DEC-018 — Voz apenas na V2

**Status:** Aprovada

A voz não fará parte da primeira versão utilizável.

Entrada e saída por voz estão planejadas para a V2.

---

## DEC-019 — V0 como prova de conceito

**Status:** Aprovada

A primeira implementação será uma V0 de prova de conceito.

Ela deve validar o ciclo:

pedido
→ interpretação
→ contexto
→ plano
→ permissão
→ execução
→ verificação
→ resposta

Teste simbólico:

**"Therion, abra o Obsidian."**

---

## DEC-020 — Desenvolvimento progressivo

**Status:** Aprovada

Therion deve começar simples.

Princípios:

- funcional antes de complexo;
- confiável antes de autônomo;
- testável;
- verificável;
- modular;
- seguro;
- gradual.

Funcionalidades não devem ser adicionadas apenas porque são tecnicamente possíveis.

---

## DEC-021 — Separação entre projeto e agente

**Status:** Aprovada

A nota:

`90 - Sistema da IA/Agentes/Therion.md`

define o **agente Therion** dentro da governança universal.

A pasta:

`10 - Projetos/Therion/`

define o **projeto de desenvolvimento da Therion**.

Essas duas responsabilidades devem permanecer separadas.

---

## DEC-022 — Fontes de verdade

**Status:** Aprovada

As fontes devem ser interpretadas assim:

### Segundo Cérebro

Fonte para:

- visão;
- decisões;
- regras;
- contexto;
- arquitetura conceitual;
- roadmap.

### Repositório

Fonte para:

- implementação atual;
- código existente;
- comportamento efetivamente implementado.

### Git

Fonte para:

- histórico técnico.

### Testes

Fonte para:

- evidência de comportamento validado.

Uma funcionalidade planejada não deve ser tratada como implementada.

---

## DEC-023 — Linguagem principal da V0

**Status:** Aprovada

Python é a linguagem principal aprovada para o desenvolvimento da V0 (prova de conceito) do Therion.

Motivações e limites da decisão:

- Foco na validação rápida do ciclo básico da V0 ("Therion, abra o Obsidian");
- Simplicidade para automação, manipulação de texto e controle de processos no Windows;
- Esta decisão restringe-se exclusivamente à linguagem principal da V0;
- Não define bibliotecas, frameworks, modelos de IA ou arquitetura adicional neste momento.

---

## DEC-024 — Logs e auditoria técnica da V0

**Status:** Aprovada

Os logs técnicos da V0 são registrados em formato JSON Lines (.jsonl) como dados operacionais locais.

Decisões aprovadas:

- Formato: JSON Lines (.jsonl), um registro por linha;
- Local: pasta `logs/` na raiz do projeto, tratada como dado operacional local (incluída no `.gitignore`);
- Sanitização obrigatória: senhas, tokens, chaves de API e credenciais devem ser mascarados (`[REDACTED]`) antes de qualquer gravação;
- Resiliência: falha do sistema de logs não deve interromper o fluxo principal da tarefa;
- Restrição de conteúdo: não registrar conteúdo completo de notas do Segundo Cérebro nem credenciais;
- Implementação na V0: somente biblioteca padrão do Python, sem banco de dados e sem dependências externas.

Os campos do registro atual (`timestamp`, `task_id`, `command`, `intent`, `target`, `plan`, `confirmation_status`, `execution_mode`, `execution_result`, `verification_result`, `error`, `task_status`, `context_queries`) representam a implementação vigente e podem evoluir.

---

## DEC-025 — Interface V1

**Status:** Aprovada

A interface desktop da V1 utilizará **PySide6** (Qt para Python).

Decisões aprovadas:

- Framework: PySide6.
- O núcleo do Therion permanece em Python.
- Haverá janela própria de texto, sem depender do terminal.
- Interface compacta com possibilidade de interface expandida para conversas.
- System Tray com `QSystemTrayIcon`.
- Fechar a janela oculta/minimiza para a bandeja, não encerra o processo.
- Ação explícita "Encerrar Therion" necessária para sair.

---

## DEC-026 — Processo persistente V1

**Status:** Aprovada

O Therion será uma aplicação desktop persistente em Python/PySide6.

Decisões aprovadas:

- Core e interface permanecem no mesmo processo na V1.
- Fechar a janela deve ocultar/minimizar para a bandeja, não encerrar o processo.
- O Therion permanece ativo enquanto estiver na bandeja.
- Deve existir ação explícita "Encerrar Therion".
- **NÃO utilizar Windows Service na V1.**
- **NÃO utilizar IPC entre Core e UI na V1**, salvo necessidade técnica comprovada posteriormente.

---

## DEC-027 — Configuração local V1

**Status:** Aprovada

A configuração local da V1 utilizará formato **JSON** com leitura e escrita em Python.

Decisões aprovadas:

- Formato: JSON (biblioteca padrão `json`).
- Não armazenar segredos ou credenciais no arquivo comum.
- Configurações inválidas não devem derrubar o Therion (fallback para padrões seguros).
- Alterações devem ser validadas antes da persistência.
- Persistência deve ser segura (escrita atômica, backup opcional).
- Pode armazenar: paths, preferências, allowlist de aplicativos, aliases, configurações não sensíveis.
- Exemplo de alias futuro válido: `"segundo cérebro" → Obsidian`.

---

## DEC-028 — Skills V1

**Status:** Aprovada

A arquitetura de Skills da V1 será **híbrida**.

Decisões aprovadas:

- O Segundo Cérebro continua sendo a fonte oficial para definição, estado, regras, riscos, evidências e permissões das Skills.
- Implementações executáveis ficam em módulos Python controlados no repositório do Therion.
- Registry local associa Skill oficial à implementação executável.
- Toda execução passa por Orchestrator, permissões, confirmação aplicável, verificação e auditoria.
- **Não executar código arbitrário** vindo de notas Markdown.
- **Não baixar/executar Skills arbitrárias** externas.
- **Não permitir criação, ativação ou aumento de autonomia automaticamente.**
- Fluxo continua: RAS → candidato a Skill → proposta → autorização → implementação → teste → possível ativação.

---

## DEC-029 — Calendário V1

**Status:** Aprovada

A integração de calendário da V1 utilizará **Google Calendar API** com **adapter pattern**.

Decisões aprovadas:

- Primeiro provedor: Google Calendar API.
- Autenticação: OAuth 2.0.
- Arquitetura baseada em adapters para permitir outros provedores no futuro.
- Consultas autorizadas podem ocorrer sem confirmação adicional.
- Criar, alterar ou excluir eventos exige confirmação.
- Tokens e credenciais **não ficam no Segundo Cérebro nem no JSON comum**.
- Credenciais/tokens **não podem aparecer nos logs**.
- Falha da integração de calendário **não pode derrubar o Therion**.
- Escopo inicial:
  - listar próximos eventos;
  - consultar hoje/amanhã/data específica;
  - criar evento após confirmação;
  - escolher calendário autorizado;
  - verificar criação.
- Fora do escopo inicial:
  - aceitar/recusar convites;
  - anexos;
  - automações baseadas em calendário;
  - integração profunda com múltiplos provedores.

---

## DEC-030 — Provider local-first Ollama para V1

**Status:** Aprovada

A integração inicial de modelo de IA da V1 utilizará o runtime local **Ollama** com arquitetura local-first e fallback determinístico.

Decisões aprovadas:

- **Runtime local:** Ollama adotado como runtime local da V1.
- **Implementação do provider:** `OllamaProvider` conecta-se à API HTTP local (`/api/chat`) utilizando `urllib.request` da biblioteca padrão do Python (sem novas dependências).
- **Rede e isolamento:**
  - Endpoint fixo e restrito a loopback (`http://127.0.0.1:11434/api/chat`).
  - Sem endpoint configurável e sem configuração de proxy (proxy desabilitado explicitamente com `ProxyHandler({})`).
  - Sem chamadas a nuvem ou serviços externos.
- **Escopo operacional do provider:**
  - Sem uso de tools/function calling do modelo;
  - Sem download ou gerenciamento de processos pelo Therion;
  - Sem streaming e sem retry automático;
  - Timeout estrito configurável (padrão 90s).
- **Segurança e ativação:**
  - IA desabilitada por padrão na configuração local (`ai.enabled: false`);
  - Nenhuma requisição ou inferência é realizada durante a inicialização do aplicativo.
- **Modelo inicial:**
  - `qwen3:4b-instruct` adotado como modelo inicial validado, sem compromisso de permanência exclusiva.
- **Fronteira de validação e fallback:**
  - O `AICore` é a fronteira final e obrigatória de validação sintática e semântica;
  - Saídas com schemas inválidos, saídas híbridas (chat/clarification com intent ou arguments operacionais) ou intents fora da allowlist canônica retornam `None`;
  - Qualquer falha de inferência aciona obrigatoriamente o fallback determinístico do `Orchestrator` (`IntentRecognizer`).

---

## Regra de manutenção

Ao registrar uma nova decisão:

1. verificar se ela realmente foi aprovada;
2. não registrar hipótese como decisão;
3. evitar duplicar decisão já existente;
4. atualizar decisão anterior quando ela tiver sido substituída;
5. preservar histórico apenas quando ele tiver valor;
6. manter IDs sequenciais.

Formato recomendado:

`DEC-XXX — Nome da decisão`

Status possíveis:

- Proposta
- Aprovada
- Substituída
- Revogada