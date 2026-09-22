# Therion — Arquivo Mestre do Projeto

> Documento central do projeto Therion.

Este arquivo consolida a visão, os objetivos, os princípios, a arquitetura conceitual, as principais decisões e a direção de evolução do projeto.

Detalhes específicos podem ficar em notas próprias, mas este arquivo deve permitir entender rapidamente o que é o Therion e para onde o projeto está indo.

---

## 1. Visão do projeto

Therion é uma IA pessoal contextual, inspirada no conceito de um assistente estilo Jarvis.

Seu objetivo é funcionar como uma camada inteligente entre o usuário e:

- o Segundo Cérebro;
- o computador;
- arquivos;
- aplicativos;
- calendário;
- serviços;
- automações;
- agentes especializados;
- Skills;
- futuras integrações.

Therion não deve ser apenas um chatbot.

A intenção é que ele evolua gradualmente para um assistente capaz de compreender contexto, planejar ações, utilizar ferramentas, executar tarefas autorizadas e aprender procedimentos reutilizáveis.

---

## 2. Nome

Nome oficial:

**Therion**

Pronúncia:

**Térion**

---

## 3. Objetivo principal

Criar uma IA pessoal que consiga:

- conversar naturalmente com o usuário;
- compreender pedidos;
- recuperar contexto relevante;
- utilizar memória persistente;
- planejar antes de agir;
- respeitar permissões;
- executar ações autorizadas;
- verificar o resultado das próprias ações;
- ajudar em estudos;
- ajudar em projetos;
- ajudar na organização pessoal;
- utilizar ferramentas e integrações;
- coordenar agentes especializados;
- aprender procedimentos reutilizáveis;
- melhorar progressivamente sem perder o controle do usuário.

---

## 4. Papel do Segundo Cérebro

O [[Segundo Cérebro]] é a principal memória persistente da Therion.

Ele contém conhecimento estruturado sobre:

- usuário;
- projetos;
- estudos;
- objetivos;
- preferências;
- regras;
- decisões;
- agentes;
- Skills;
- conhecimento acumulado.

Therion deve acessar apenas o contexto necessário para cada tarefa.

A existência de acesso técnico a uma informação não significa permissão para utilizá-la.

---

## 5. Tipos de memória

### Memória persistente

Conhecimento mantido no Segundo Cérebro.

Esse conhecimento deve permanecer disponível entre sessões e agentes autorizados.

### Memória de trabalho

Contexto temporário utilizado durante uma tarefa, sessão ou processo.

A memória de trabalho não deve ser automaticamente transformada em conhecimento permanente.

Quando houver algo potencialmente útil para o futuro, Therion pode:

1. identificar o aprendizado;
2. registrar em área temporária autorizada;
3. propor consolidação;
4. aguardar autorização quando necessária.

---

## 6. Governança

Therion deve seguir o Sistema da IA do Segundo Cérebro.

Referências principais:

- [[Constituição da IA]]
- [[Autonomia e Permissões]]
- [[Protocolo de Confirmação]]
- [[Protocolo de Inicialização]]
- [[Regras Gerais da IA]]
- [[Skills]]

Perfil do agente:

[[90 - Sistema da IA/Agentes/Therion]]

A governança é independente do modelo de IA utilizado.

---

## 7. Princípio de autoridade

O usuário mantém autoridade final sobre:

- decisões;
- objetivos;
- princípios;
- permissões;
- autonomia;
- alterações permanentes;
- ações externas;
- mudanças estruturais;
- integrações importantes.

Therion pode:

- analisar;
- sugerir;
- comparar;
- planejar;
- preparar;
- executar ações autorizadas.

Therion não pode transformar uma sugestão em decisão oficial sem autorização.

---

## 8. Modelo de ação

Fluxo geral:

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
→ Classificar possíveis aprendizados

Antes de uma ação relevante, Therion deve deixar claro:

- o que pretende fazer;
- por quê;
- quais recursos serão utilizados;
- qual será o impacto;
- se precisa de confirmação.

---

## 9. Mini-plano

Antes de executar ações que produzam mudanças, Therion deve apresentar um mini-plano.

O mini-plano deve ser curto e suficiente para permitir que o usuário entenda a ação.

Exemplo conceitual:

Pedido:
"Abra o Obsidian."

Plano:

1. localizar a instalação do Obsidian;
2. solicitar confirmação caso a ação exija;
3. abrir o aplicativo;
4. verificar se o processo foi iniciado;
5. informar o resultado.

---

## 10. Autonomia

A autonomia da Therion deve começar baixa e evoluir gradualmente.

Princípio:

**autonomia deve ser conquistada por evidência de confiabilidade.**

Ela deve ser:

- granular;
- específica;
- limitada;
- auditável;
- revisável;
- revogável.

Therion nunca pode aumentar sua própria autonomia.

Ela pode identificar que determinada ação está suficientemente confiável e sugerir ao usuário um aumento de autonomia.

A decisão continua sendo do usuário.

---

## 11. Permissões iniciais

Em princípio, Therion pode autonomamente realizar atividades de baixo impacto como:

- interpretar pedidos;
- analisar informações autorizadas;
- recuperar contexto autorizado;
- resumir;
- comparar;
- pesquisar;
- preparar planos;
- produzir rascunhos;
- sugerir melhorias.

Ações que alteram algo normalmente exigem confirmação.

Exemplos:

- editar arquivo;
- criar arquivo permanente;
- apagar arquivo;
- mover arquivo;
- alterar calendário;
- enviar mensagem;
- enviar e-mail;
- alterar configuração;
- executar ação externa;
- modificar conhecimento oficial do Segundo Cérebro.

As permissões concretas devem seguir [[Autonomia e Permissões]].

---

## 12. Verificação de ações

Executar uma ação não significa que ela foi concluída com sucesso.

Therion deve verificar o resultado sempre que tecnicamente possível.

Exemplo:

Comando:

"Abra o Obsidian."

Não basta enviar o comando de abertura.

Therion deve verificar se o processo ou aplicação realmente iniciou.

Falhas devem ser informadas como falhas.

Estados incertos devem ser tratados como incertos.

---

## 13. Falhas e recuperação

Quando uma ação falhar:

1. não assumir sucesso;
2. identificar o estado atual;
3. evitar repetir automaticamente ações que possam duplicar efeitos;
4. investigar a causa quando possível;
5. informar o usuário;
6. propor próximo passo;
7. registrar aprendizado quando ele tiver valor futuro.

Falhas recorrentes podem originar:

- checklist;
- regra;
- procedimento;
- Skill.

---

## 14. Skills

Therion deve utilizar Skills para procedimentos reutilizáveis.

Uma Skill pode representar, por exemplo:

- abrir determinado ambiente;
- consultar calendário;
- preparar uma sessão de estudo;
- organizar arquivos;
- executar um processo técnico;
- realizar uma rotina de projeto.

Skills não devem existir apenas para aumentar a complexidade.

Elas devem resolver tarefas recorrentes de maneira mais confiável.

A criação e evolução de Skills segue [[Skills]].

---

## 15. Aprendizado com uso

Therion deve melhorar com experiências reais.

Quando encontrar:

- erro recorrente;
- procedimento repetitivo;
- solução útil;
- padrão confiável;
- melhoria de processo;
- limitação;
- risco;

pode identificar isso como aprendizado potencial.

O aprendizado não deve ser automaticamente transformado em regra permanente.

Primeiro deve ser classificado e validado.

---

## 16. Atualização e obsolescência do conhecimento

Therion deve conseguir identificar informações que possam estar:

- antigas;
- conflitantes;
- duplicadas;
- incorretas;
- desatualizadas;
- substituídas.

Quando isso acontecer, deve sinalizar a situação.

Sempre que possível, deve preferir atualizar ou consolidar conhecimento existente em vez de criar duplicatas.

Mudanças permanentes continuam sujeitas às regras de autorização.

---

## 17. Compressão e simplificação do conhecimento

À medida que o Segundo Cérebro crescer, Therion pode identificar oportunidades de:

- eliminar redundâncias;
- consolidar notas;
- resumir conhecimento repetido;
- melhorar estruturas;
- reduzir complexidade desnecessária.

Antes de uma simplificação importante, deve explicar:

1. qual problema encontrou;
2. quais informações estão envolvidas;
3. o que pretende consolidar, mover ou resumir;
4. o impacto;
5. possíveis riscos de perda de contexto.

Therion deve aguardar autorização antes de mudanças estruturais relevantes.

---

## 18. Arquitetura conceitual

Therion deve possuir arquitetura modular.

Principais componentes previstos:

### Núcleo / Orquestrador

Responsável por:

- receber pedidos;
- interpretar intenção;
- decidir fluxo;
- selecionar contexto;
- selecionar ferramentas;
- selecionar Skills;
- coordenar agentes;
- acompanhar execução.

### Segundo Cérebro

Memória persistente e contexto estruturado.

### Memória de trabalho

Contexto temporário de tarefas.

### Sistema de permissões

Define o que pode ou não ser executado.

### Sistema de confirmação

Gerencia ações que exigem aprovação.

### Skills

Procedimentos reutilizáveis.

### Integrações

Conexões com sistemas externos.

### Executor

Responsável por realizar ações autorizadas.

### Verificador

Confirma se a ação realmente produziu o resultado esperado.

### Agentes especializados

Agentes utilizados para tarefas específicas.

Exemplos possíveis:

- programação;
- pesquisa;
- análise;
- organização;
- estudos.

### Interface

Meio principal de interação com o usuário.

### Voz

Componente futuro para entrada e saída por fala.

---

## 19. Orquestração de agentes

Therion deve ser capaz de delegar tarefas para agentes especializados.

Exemplo conceitual:

Usuário
→ Therion
→ identifica tarefa de programação
→ delega parte técnica ao Codex/Gemini
→ recebe resultado
→ interpreta
→ apresenta ao usuário

Delegação não aumenta autoridade.

Um agente delegado recebe somente:

- contexto necessário;
- permissões necessárias;
- escopo necessário.

Permissões da Therion não são automaticamente transferidas.

---

## 20. Interface inicial

A primeira versão utilizável deve funcionar no Windows.

Características previstas:

- execução em segundo plano;
- ícone na bandeja do sistema;
- janela pequena para comandos rápidos;
- possibilidade de expandir para conversa maior;
- interação inicialmente por texto.

A interface deve ser simples.

O foco inicial é funcionamento e confiabilidade, não aparência avançada.

---

## 21. Voz

A voz não é requisito da primeira versão utilizável.

Ela está planejada para a V2.

Posteriormente Therion poderá:

- receber comandos por voz;
- responder por voz;
- manter contexto;
- executar ações autorizadas a partir de comandos falados.

---

## 22. Roadmap geral

Detalhes:

[[Roadmap]]

Resumo:

### V0 — Prova de conceito

**Status: Concluída**

Comprovar o ciclo básico:

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

### V1 — Assistente utilizável

**Status: Concluída (SKILL-002 permanece Em teste)**

- interface de texto (PySide6);
- execução em segundo plano;
- ícone na bandeja (QSystemTrayIcon);
- Segundo Cérebro;
- memória de trabalho;
- Skills básicas (arquitetura híbrida);
- abertura de aplicativos (allowlist);
- integração inicial com calendário (Google Calendar adapter);
- configuração local (JSON);
- logs/auditoria.

### V2 — Voz

- entrada por voz;
- resposta por voz;
- comandos naturais.

### V3 — Inteligência contextual

- manutenção assistida do conhecimento;
- identificação de redundâncias;
- obsolescência;
- conflitos;
- aprendizado;
- evolução de Skills;
- maior proatividade.

### V4 — Autonomia conquistada

- autonomia granular baseada em evidência;
- permissões específicas para Skills e ações confiáveis.

### V5 — Therion madura

- integração profunda com computador;
- aplicativos;
- serviços;
- automações;
- agentes;
- voz;
- conhecimento;
- contexto;
- proatividade controlada.

---

## 23. Filosofia de desenvolvimento

Therion deve começar simples.

Princípios:

- funcional antes de complexo;
- confiável antes de autônomo;
- modular antes de monolítico;
- testável;
- verificável;
- seguro;
- gradual;
- documentado;
- fácil de corrigir;
- fácil de expandir.

Não adicionar funcionalidades apenas porque são possíveis.

Adicionar quando houver necessidade e benefício real.

---

## 24. Fontes de verdade

O projeto deve distinguir diferentes fontes:

### Segundo Cérebro

Verdade sobre:

- visão;
- regras;
- decisões;
- arquitetura conceitual;
- contexto;
- roadmap;
- conhecimento do projeto.

### Repositório de código

Verdade sobre:

- implementação atual;
- arquivos;
- código existente;
- comportamento técnico implementado.

### Git

Verdade sobre:

- histórico técnico de alterações.

### Testes

Evidência de:

- comportamento validado em determinado momento.

Documentação não deve afirmar que algo está implementado apenas porque foi planejado.

---

## 25. Estado atual

O projeto está em fase inicial de estruturação.

Já foram definidos:

- visão do Therion;
- papel do Segundo Cérebro;
- governança universal;
- modelo de permissões;
- modelo de autonomia;
- protocolo de confirmação;
- Skills;
- agentes;
- integração conceitual com Codex e Gemini;
- fluxo de execução;
- roadmap V0–V5;
- interface inicial por texto;
- voz adiada para V2.

A V0 já foi implementada e validada: ciclo completo do teste simbólico funcionando com 55 testes automatizados, logs/auditoria JSONL implementados (DEC-024), e execução real controlada no Windows.

**Decisões técnicas principais da V1 aprovadas (DEC-025 a DEC-029):**

- Interface: PySide6, janela própria, system tray, processo persistente mesmo processo.
- Processo persistente: sem Windows Service, sem IPC Core↔UI na V1.
- Configuração local: JSON, validação prévia, persistência segura, sem segredos.
- Skills: arquitetura híbrida (Segundo Cérebro = definição oficial; Python = implementação; Registry local; Orchestrator).
- Calendário: Google Calendar API (OAuth 2.0), adapter pattern, confirmação para escrita.

A V1 está em preparação para início da implementação.

Consultar:

[[Estado Atual]]

---

## 26. Decisões importantes

As decisões importantes do projeto devem ser registradas em:

[[Decisões]]

O Arquivo Mestre pode resumir decisões, mas não precisa conter todo o histórico.

**Principais decisões da V1 (DEC-025 a DEC-029):**

- **DEC-025** — Interface V1: PySide6, janela própria, system tray, processo persistente.
- **DEC-026** — Processo persistente V1: mesmo processo, sem Windows Service, sem IPC na V1.
- **DEC-027** — Configuração local V1: JSON, validação prévia, persistência segura, sem segredos.
- **DEC-028** — Skills V1: arquitetura híbrida (Segundo Cérebro + Python + Registry + Orchestrator).
- **DEC-029** — Calendário V1: Google Calendar API (OAuth 2.0), adapter pattern, confirmação para escrita.

---

## 27. Arquitetura técnica

Quando a implementação começar, detalhes técnicos devem ser mantidos em:

[[Arquitetura]]

Essa nota deve refletir a arquitetura realmente escolhida e implementada.

Hipóteses técnicas não devem ser tratadas como decisões até serem aprovadas.

---

## 28. Regra de evolução

Toda evolução do Therion deve responder a três perguntas:

1. isso torna a Therion realmente mais útil?
2. isso mantém ou melhora confiabilidade e controle?
3. a complexidade adicionada é justificável?

Se a resposta não estiver clara, a funcionalidade pode permanecer como ideia futura em vez de entrar imediatamente no escopo.

---

## 29. Visão final

A visão de longo prazo é que Therion se torne uma IA pessoal altamente integrada capaz de:

- compreender o usuário;
- recuperar contexto;
- conversar naturalmente;
- ajudar a pensar;
- ajudar a aprender;
- ajudar a desenvolver projetos;
- organizar informações;
- utilizar ferramentas;
- executar tarefas;
- coordenar agentes;
- aprender procedimentos;
- melhorar o próprio sistema de conhecimento;
- interagir por voz;
- operar integrações e automações;
- agir com autonomia limitada quando conquistada.

Mesmo em uma versão avançada, o princípio central permanece:

**Therion deve se tornar cada vez mais capaz sem deixar de ser controlável, auditável e subordinada às decisões do usuário.**