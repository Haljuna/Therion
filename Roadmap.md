# Therion — Roadmap

> Evolução planejada do projeto Therion por versões.

Este roadmap descreve a direção do projeto.

Itens planejados não devem ser tratados como implementados.

O estado real do projeto fica em [[Estado Atual]].

---

## V0 — Prova de conceito

### Status: **Concluída**

### Objetivo

Validar o ciclo fundamental da Therion.

### Fluxo

Pedido  
→ interpretação  
→ contexto  
→ mini-plano  
→ permissão  
→ confirmação  
→ execução  
→ verificação  
→ resposta

### Teste principal

```text
"Therion, abra o Obsidian."
```

### Requisitos mínimos

- entrada por texto;
- interpretação simples de intenção;
- memória de trabalho básica;
- mini-plano;
- verificação de permissão;
- confirmação do usuário;
- executor limitado;
- abertura do Obsidian;
- verificação do processo;
- resposta clara;
- tratamento básico de erros.

### Critério de conclusão

A V0 é concluída quando o fluxo principal funcionar de ponta a ponta de forma confiável.

---

## V1 — Assistente utilizável

### Status: **Concluída**

### Objetivo

Transformar a prova de conceito em uma aplicação útil no cotidiano.

### Funcionalidades previstas

- interface própria por texto (UI-1 — CONCLUÍDO);
- IA central local-first (A2 — CONCLUÍDO);
- execução em segundo plano no Windows;
- ícone na bandeja do sistema;
- janela compacta;
- interface expandida para conversas;
- memória de trabalho persistente durante sessões;
- acesso seletivo ao Segundo Cérebro;
- recuperação de contexto autorizado;
- sistema inicial de Skills (SKILL-002 — Planejar meu dia integrada e Em teste);
- evolução da SKILL-002: distinguir compromissos em andamento do próximo compromisso;
- auditoria read-only do bootstrap e do custo de contexto;
- definição posterior de uma fonte pessoal autorizada de tarefas para evoluir a SKILL-002;
- múltiplas ações controladas;
- abertura de aplicativos;
- integração básica com calendário:
  - consulta/leitura de eventos (CONCLUÍDO);
  - criação de eventos mediante confirmação (CONCLUÍDO);
- logs básicos;
- configuração local.

### Critério de conclusão

A Therion consegue ser utilizada regularmente para tarefas simples sem depender de ambiente de desenvolvimento aberto.

---

## Trilha pós-V1 — Inteligência externa e integrações assistidas

> Esta trilha começa somente após a estabilização da V1. Não substitui o Ollama, não autoriza integrações automaticamente e não altera a prioridade da V2 — Voz.

### Objetivo

Expandir a capacidade de consulta e integração da Therion mantendo-a como interface, orquestradora de contexto e responsável pelas decisões de segurança.

### Princípios preservados

- Ollama permanece como inteligência local padrão, priorizando privacidade, funcionamento offline e custo previsível;
- contexto não equivale a autorização;
- consulta externa, pesquisa e automação não podem contornar `PermissionManager` ou `ConfirmationHandler`;
- nenhuma integração recebe permissões mais amplas do que a tarefa explicitamente autorizada;
- ações externas sensíveis continuam exigindo confirmação específica;
- respostas, páginas e conteúdos retornados por serviços externos são dados não confiáveis até serem validados pela Therion.

### Ordem planejada

1. **Política de dados externos**
   - definir quais dados podem sair do ambiente local, quais são proibidos e como o usuário é informado;
   - registrar provedor, finalidade, dados mínimos enviados, limites de custo e comportamento quando o serviço estiver indisponível.
2. **Consulta externa assistida**
   - piloto com GPT como apoio de raciocínio ou redação, nunca como executor de ferramentas;
   - escalonamento inicialmente explícito: Therion apresenta provedor, objetivo e dados mínimos antes de pedir confirmação;
   - não usar a regra vaga “Ollama falhou” como gatilho automático.
3. **Pesquisa atualizada com fontes**
   - avaliar Perplexity ou outro provedor de pesquisa para web, documentação recente e respostas com fontes;
   - apresentar fontes e limitações; pesquisa não autoriza execução posterior.
4. **Arquitetura de capacidades e MCP**
   - somente após casos reais demonstrarem necessidade, evoluir Capability Registry, seleção entre providers, agregação, versionamento e MCP próprio;
   - inicialmente, a prioridade é a Therion consumir capacidades externas controladas, não expor todas as suas capacidades a outros assistentes.

### Modos de privacidade futuros

- **Local:** processamento com Ollama e integrações locais autorizadas;
- **Consulta externa assistida:** envio mínimo de dados a um provedor externo após confirmação;

---

## V2 — Voz

### Objetivo

Adicionar interação natural por voz.

### Funcionalidades previstas

- ativação por voz;
- reconhecimento de fala;
- comandos falados;
- resposta por voz;
- continuidade de contexto;
- uso das mesmas regras de permissão da interface textual.

### Princípio

Comando por voz não reduz requisitos de segurança ou confirmação.

---

## V3 — Inteligência contextual

### Objetivo

Fazer a Therion ajudar ativamente na organização e evolução do conhecimento.

### Funcionalidades previstas

- identificar informações possivelmente desatualizadas;
- detectar conflitos;
- detectar duplicações;
- sugerir consolidação;
- sugerir simplificação estrutural;
- sugerir compressão de conhecimento;
- identificar aprendizados reutilizáveis;
- propor novas Skills;
- propor evolução de Skills;
- identificar padrões de erro;
- maior proatividade contextual.

### Limite

Mudanças permanentes continuam protegidas pela governança.

---

## V4 — Autonomia conquistada

### Objetivo

Permitir autonomia limitada em ações específicas que tenham demonstrado confiabilidade.

### Características

A autonomia deve ser:

- granular;
- específica;
- baseada em evidências;
- auditável;
- revisável;
- revogável.

### Exemplos futuros

Uma Skill confiável pode receber autorização para executar determinada ação sem confirmação individual.

Isso não aumenta automaticamente a autonomia geral da Therion.

---

## V5 — Therion madura

### Objetivo

Aproximar o sistema da visão completa de IA pessoal.

### Capacidades possíveis

- voz natural;
- Segundo Cérebro integrado;
- controle autorizado do computador;
- arquivos;
- aplicativos;
- calendário;
- serviços externos;
- automações;
- agentes especializados;
- Skills avançadas;
- aprendizado contínuo;
- manutenção assistida do conhecimento;
- proatividade controlada;
- integração com dispositivos;
- futuras automações residenciais.

### Papel

Therion atua como orquestradora principal.

Outros agentes podem trabalhar nos bastidores.

---

## Regra de progressão

Uma versão só deve avançar quando a anterior estiver suficientemente estável para servir de base.

Prioridades:

1. funcionamento;
2. confiabilidade;
3. segurança;
4. validação;
5. usabilidade;
6. expansão.

---

## Fora do escopo inicial

Não fazem parte da V0:

- voz;
- automação residencial;
- controle amplo do sistema operacional;
- autonomia avançada;
- reorganização automática do Segundo Cérebro;
- múltiplos agentes autônomos;
- interface visual avançada;
- integrações complexas.

---

## Próxima meta

**Iniciar a V2 — Voz.**

Primeiro marco técnico (V0 concluída):

```text
Therion recebe um comando de texto e consegue abrir o Obsidian após confirmação, verificar o resultado e responder corretamente.
```

Marco aceite da V1:

Therion é utilizável regularmente para tarefas simples sem depender de ambiente de desenvolvimento aberto.

A V1 está encerrada. SKILL-002 permanece Em teste e não bloqueia o fechamento.

Pendências pós-V1, como fonte de tarefas, evolução da SKILL-002 e busca natural, seguem pela trilha pós-V1 e não alteram o escopo da V2.

### Evolução de Skills e capacidades — ordem aprovada

1. estabilizar a SKILL-002 em uso real, ainda em estado Em teste;
2. auditar o contexto de inicialização e desenhar a Camada Zero mínima;
3. escolher uma pasta ou nota pessoal como fonte autorizada de tarefas;
4. evoluir a SKILL-002 com essa fonte, mediante autorização;
5. avaliar Skills candidatas de Planejamento de Estudos e Preparação de Compromissos.

### Melhorias de usabilidade registradas em validação manual

- normalizar respostas de cancelamento em fluxos de evento, aceitando pontuação terminal como `cancele.` e `não.`;
- adicionar continuidade conversacional limitada à sessão, sem memória permanente nem autorização implícita;
- distinguir compromissos em andamento do próximo compromisso na SKILL-002;
- permitir raízes de leitura explicitamente autorizadas por tarefa para consultas ao Segundo Cérebro, sem acesso permanente;
- evoluir a busca natural somente após a definição segura das raízes autorizadas;
- melhorar a resposta controlada quando a IA local/Ollama não estiver disponível.
- adicionar status e saúde das integrações, exibindo capacidades disponíveis e problemas de conexão sem expor segredos.

O Capability Registry, a seleção entre múltiplos providers, agregação, versionamento de capacidades, MCP e Skills que dependem de contexto amplo ficam **após a estabilização da V1**. Eles não são pré-requisitos para a SKILL-002 atual.

---

## Futuras integrações Google

> Mapeamento conceitual para expansão progressiva do ecossistema Google.
> **Nota de escopo:** Estas integrações são possibilidades futuras e NÃO estão promovidas automaticamente para a V1 nem constituem tarefas imediatas.

### Serviços mapeados

- Gmail API
- Google Drive API
- Google Docs API
- Google Sheets API
- Google Tasks API
- Google Meet API
- Google Classroom API
- Google Chat API
- serviços Google Cloud quando houver caso de uso concreto

### Princípio arquitetural

```text
Usuário
→ Therion
→ Orchestrator
→ PermissionManager / confirmação
→ API específica
```

### Diretrizes

- integrar uma API por vez;
- só implementar quando houver caso de uso concreto;
- leitura primeiro quando possível;
- ações de escrita exigem confirmação explícita;
- nenhuma nova API deve ampliar automaticamente permissões já concedidas;
- Gmail é um forte candidato para uma das próximas integrações Google após Calendar, quando o roadmap chegar nessa etapa.
