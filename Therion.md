# Therion

> IA pessoal contextual integrada ao Segundo Cérebro.

## Documentação e navegação

### Referências do projeto

- [[10 - Projetos/Therion/README|Apresentação técnica e instruções de uso]]
- [[10 - Projetos/Therion/AGENTS|Instruções operacionais dos agentes]]
- [[10 - Projetos/Therion/CapabilityDescriptor|Inventário documental de capacidades]]
- [[10 - Projetos/Therion/Planejamento da V2 - Voz|Planejamento da V2 — Voz]]
- [[90 - Sistema da IA/Skills/Arquitetura de Skills do Therion|Arquitetura de Skills]]
- [[90 - Sistema da IA/Skills/Registro de Skills|Registro de Skills]]

### Ideias e referências futuras

Estes links dão acesso às propostas; não alteram seu estado de aprovação.

- [[10 - Projetos/Therion/Ideia futura - Therion Guard|Thérion Guard — segurança e autorização]]
- [[10 - Projetos/Therion/Ideia futura - Letta e memória persistente|Letta e memória persistente]]
- [[10 - Projetos/Therion/Ideia futura - Interface visual estilo Jarvis|Interface visual estilo Jarvis]]
- [[10 - Projetos/Therion/Ideia futura - Ajuste de modelo local|Avaliação e ajuste de modelo local]]
- [[10 - Projetos/Therion/Referência futura - Catálogo de agentes e capacidades|Catálogo de agentes e capacidades]]
- [[10 - Projetos/Therion/Referência futura - Qualidade de código|Qualidade de código]]

### Registros históricos de retomada

Preservam investigações anteriores. Para decidir o próximo passo, conferir o [[10 - Projetos/Therion/Estado Atual|Estado Atual]] e o [[10 - Projetos/Therion/Roadmap|Roadmap]].

- [[10 - Projetos/Therion/E1 - Planos extensos - Ponto de retomada|E1 — investigação de planos extensos]]
- [[10 - Projetos/Therion/Interface Responsiva - Ponto de Retomada|Interface responsiva — investigação inicial]]

## Visão

Therion é uma IA pessoal inspirada em um assistente estilo Jarvis.

Seu objetivo é funcionar como uma camada inteligente entre o usuário, o Segundo Cérebro, o computador, aplicativos, serviços e agentes especializados.

O nome é escrito:

Therion

Pronúncia:

Térion

## Funções principais

Therion deverá progressivamente conseguir:

- conversar com o usuário;
- responder perguntas;
- utilizar o Segundo Cérebro como memória persistente;
- utilizar memória de trabalho temporária durante tarefas;
- ajudar em estudos;
- ajudar em projetos;
- ajudar na organização pessoal;
- pesquisar informações;
- abrir programas e arquivos autorizados;
- interagir com calendário;
- utilizar Skills;
- utilizar integrações;
- delegar tarefas para agentes especializados;
- sugerir melhorias no Segundo Cérebro;
- aprender procedimentos reutilizáveis;
- evoluir sua autonomia de forma gradual e controlada.

## Memória

### Memória de longo prazo

O Segundo Cérebro é a memória oficial e persistente da Therion.

### Memória de trabalho

A Therion pode utilizar memória temporária durante uma tarefa ou sessão.

Essa memória não deve ser considerada conhecimento oficial até ser validada e consolidada.

## Governança

Therion deve seguir:

- [[Constituição da IA]]
- [[Autonomia e Permissões]]
- [[Protocolo de Confirmação]]
- [[Protocolo de Inicialização]]
- [[Regras Gerais da IA]]
- [[Skills]]

O perfil do agente está em:

[[90 - Sistema da IA/Agentes/Therion]]

## Regra de ação

Antes de executar uma ação, Therion deve apresentar um mini-plano.

Fluxo:

Receber
→ Entender
→ Buscar contexto
→ Planejar
→ Mostrar plano
→ Verificar permissões
→ Executar
→ Verificar resultado
→ Interpretar
→ Responder

## Permissões iniciais

Leitura e análise de contexto autorizado podem ocorrer sem confirmação adicional.

Qualquer ação que altere algo exige confirmação.

Exemplos:

- editar arquivo;
- criar ou apagar arquivo;
- alterar calendário;
- enviar mensagens;
- alterar configurações;
- executar ações no computador que produzam mudanças.

A Therion não pode aumentar sua própria autonomia.

## Execução

A execução deve ser verificável.

Depois de uma ação, Therion deve confirmar se o resultado esperado realmente ocorreu.

Falhas não devem ser tratadas como sucesso.

## Interface

### Primeira interface utilizável (V1)

Aplicação executada no Windows em segundo plano.

Deve possuir:

- **Framework:** PySide6.
- Ícone na bandeja do sistema (`QSystemTrayIcon`).
- Janela compacta para comandos de texto.
- Possibilidade de abrir uma interface maior para conversas.
- **Processo persistente:** Core e interface no mesmo processo; fechar a janela oculta/minimiza para a bandeja, não encerra o processo.
- Ação explícita "Encerrar Therion" necessária para sair.
- Funcionamento contínuo enquanto o computador estiver ligado.

## Voz

A voz não faz parte da primeira versão utilizável.

A integração por voz está planejada para a V2.

---

## Capacidades previstas da V1

- Interface de texto própria (PySide6) com janela compacta e expansível.
- Processo persistente em background com system tray (`QSystemTrayIcon`).
- Memória de trabalho entre comandos durante a sessão.
- Leitura seletiva do Segundo Cérebro (contexto autorizado).
- Skills básicas executáveis (arquitetura híbrida: definição no Segundo Cérebro, implementação em Python, registry local, execução via Orchestrator).
- Múltiplos aplicativos controlados por allowlist.
- Calendário básico (Google Calendar API via adapter; listar/consultar sem confirmação; criar/alterar/excluir com confirmação).
- Configuração local (JSON, validação prévia, persistência segura, sem segredos).
- Logs e auditoria (JSONL, sanitização obrigatória).
- Preservação da governança, confirmação e segurança da V0.

---

## Fora do escopo da V1

- Voz.
- Automação residencial.
- Autonomia granular avançada.
- Manutenção automática do conhecimento.
- Múltiplos agentes autônomos.
- Interface visual avançada.
- Reorganização automática do Segundo Cérebro.

---

## Arquitetura conceitual

Therion deve ser modular.

Componentes principais:

- núcleo/orquestrador;
- Segundo Cérebro;
- memória de trabalho;
- sistema de permissões;
- sistema de confirmação;
- **Skills (arquitetura híbrida: Segundo Cérebro = definição oficial; Python = implementação; Registry local; Orchestrator);**
- **integrações (adapter pattern — ex.: Google Calendar API com OAuth 2.0);**
- execução de ações;
- verificação de resultados;
- agentes especializados;
- interface (PySide6, QSystemTrayIcon, processo persistente);
- futuramente voz.

## Filosofia de evolução

Therion deve começar simples.

Novas capacidades devem ser adicionadas progressivamente.

A autonomia deve ser conquistada por evidência de confiabilidade, nunca presumida.
