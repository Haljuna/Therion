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

### Status: **Fase ativa — Em andamento**

### Objetivo

Transformar a prova de conceito em uma aplicação útil no cotidiano.

### Funcionalidades previstas

- interface própria por texto;
- execução em segundo plano no Windows;
- ícone na bandeja do sistema;
- janela compacta;
- interface expandida para conversas;
- memória de trabalho persistente durante sessões;
- acesso seletivo ao Segundo Cérebro;
- recuperação de contexto autorizado;
- sistema inicial de Skills;
- múltiplas ações controladas;
- abertura de aplicativos;
- integração básica com calendário:
  - consulta/leitura de eventos (CONCLUÍDO);
  - criação de eventos mediante confirmação (PRÓXIMA ETAPA);
- logs básicos;
- configuração local.

### Critério de conclusão

A Therion consegue ser utilizada regularmente para tarefas simples sem depender de ambiente de desenvolvimento aberto.

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

**Concluir e validar as funcionalidades restantes da V1.**

Primeiro marco técnico (V0 concluída):

```text
Therion recebe um comando de texto e consegue abrir o Obsidian após confirmação, verificar o resultado e responder corretamente.
```

Próxima etapa funcional:
- **Calendário — criação de eventos com confirmação explícita.**

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