# Therion — Arquitetura

> Arquitetura conceitual e técnica do projeto Therion.

Esta nota descreve a estrutura do sistema.

Decisões de stack, bibliotecas ou serviços específicos só devem ser registradas aqui depois de aprovadas em [[Decisões]].

---

## Objetivo da arquitetura

Permitir que a Therion:

- receba um pedido;
- interprete a intenção;
- recupere contexto autorizado;
- monte um mini-plano;
- verifique permissões;
- execute uma ação;
- valide o resultado;
- responda ao usuário;
- registre aprendizado quando fizer sentido.

A arquitetura deve começar simples e ser expandida apenas conforme a necessidade.

---

## Arquitetura mínima da V0

A V0 deve conter apenas os componentes necessários para validar o ciclo principal.

Fluxo:

Usuário
→ Interface
→ Orquestrador
→ Contexto
→ Planejamento
→ Permissões
→ Confirmação
→ Executor
→ Verificador
→ Resposta

### Stack base da V0

- **Linguagem principal:** Python (aprovada em [[Decisões#DEC-023 — Linguagem principal da V0|DEC-023]]).
- **Framework de interface (V1):** PySide6 (aprovado em [[Decisões#DEC-025 — Interface V1|DEC-025]]).
- Bibliotecas adicionais, modelos de IA e outros frameworks permanecem em aberto para definição conforme a necessidade.

---

## 1. Interface

Responsável por receber comandos do usuário e exibir respostas.

### V0

Pode ser uma interface simples de texto.

Funções mínimas:

- receber comando;
- mostrar mini-plano;
- pedir confirmação;
- mostrar resultado;
- mostrar erros de forma clara.

A interface visual definitiva não precisa existir na V0.

### V1 — Decisões aprovadas (DEC-025, DEC-026)

- **Framework:** PySide6 (Qt para Python).
- **Janela própria de texto:** não depende do terminal; interface compacta com possibilidade de expandir para conversas maiores.
- **System Tray:** `QSystemTrayIcon` para ícone na bandeja do sistema.
- **Processo persistente:** Core e interface no mesmo processo; fechar a janela oculta/minimiza para a bandeja, não encerra o processo.
- **Ação explícita "Encerrar Therion"** necessária para sair.
- **Sem Windows Service na V1.**
- **Sem IPC entre Core e UI na V1** (salvo necessidade técnica comprovada posteriormente).

---

## 2. Orquestrador

É o núcleo lógico da Therion.

Responsabilidades:

- receber o pedido;
- identificar intenção;
- decidir quais módulos utilizar;
- selecionar contexto;
- coordenar execução;
- controlar o fluxo da tarefa.

O orquestrador não deve realizar diretamente todas as funções.

Ele coordena módulos especializados.

---

## 3. Interpretação de intenção

Responsável por transformar o pedido do usuário em uma intenção estruturada.

Exemplo:

Entrada:

"Therion, abra o Obsidian."

Interpretação esperada:

- tipo: ação
- ação: abrir aplicativo
- alvo: Obsidian
- impacto: baixo
- alteração externa: sim
- confirmação necessária: sim

A forma técnica dessa estrutura ainda será definida.

---

## 4. Contexto

Responsável por fornecer apenas o contexto necessário para a tarefa.

Fontes possíveis:

- Segundo Cérebro;
- memória de trabalho;
- configuração local;
- contexto da sessão.

Princípio:

**mínimo contexto necessário.**

O sistema não deve carregar o Segundo Cérebro inteiro para cada comando.

---

## 5. Memória de trabalho

Responsável por manter informações temporárias durante uma tarefa ou sessão.

Pode armazenar temporariamente:

- intenção atual;
- plano;
- contexto recuperado;
- resultado de ferramentas;
- estado da execução;
- erros;
- confirmações da tarefa.

Essa memória não é conhecimento permanente.

---

## 6. Planejador

Responsável por gerar o mini-plano da ação.

Exemplo:

1. localizar o Obsidian;
2. solicitar confirmação;
3. abrir o aplicativo;
4. verificar se iniciou;
5. informar resultado.

O plano deve ser proporcional à complexidade da tarefa.

---

## 7. Sistema de permissões

Responsável por determinar:

- se a ação é permitida;
- qual é o nível de autonomia;
- se é necessária confirmação;
- qual escopo está autorizado.

O sistema técnico deve refletir:

[[Autonomia e Permissões]]

Uma capacidade técnica nunca deve ser interpretada como autorização.

---

## 8. Sistema de confirmação

Responsável por bloquear ações protegidas até existir autorização válida.

Fluxo:

ação planejada
→ avaliar permissão
→ confirmação necessária
→ apresentar plano
→ aguardar usuário
→ executar somente após aprovação

A confirmação deve ser específica ao escopo da ação.

---

## 9. Executor

Responsável por executar ações autorizadas.

Na V0, o primeiro executor deve ser extremamente limitado.

Primeira ação prevista:

**abrir o Obsidian.**

O executor não deve aceitar qualquer comando arbitrário do sistema operacional.

Cada capacidade deve ser adicionada de forma explícita e controlada.

---

## 10. Verificador

Responsável por confirmar se a ação produziu o resultado esperado.

Exemplo:

Após solicitar abertura do Obsidian:

- verificar se o processo iniciou;
- retornar sucesso somente se houver evidência;
- retornar falha ou estado incerto quando necessário.

Execução e verificação devem permanecer separadas conceitualmente.

---

## 11. Resposta

Responsável por transformar o estado final da tarefa em uma resposta clara.

Exemplos:

Sucesso:

"Obsidian foi aberto com sucesso."

Falha:

"Não consegui abrir o Obsidian. O executável não foi localizado."

Estado incerto:

"O comando foi enviado, mas não consegui confirmar se o Obsidian iniciou."

---

## 12. Segundo Cérebro

O Segundo Cérebro funciona como memória persistente externa à aplicação.

A Therion deve possuir uma camada de acesso responsável por:

- localizar notas;
- ler contexto autorizado;
- limitar escopo;
- respeitar governança;
- futuramente propor atualizações.

A escrita permanente deve permanecer protegida pelas regras do Sistema da IA.

---

## 13. Skills

Skills não precisam estar plenamente implementadas na primeira prova de conceito.

A arquitetura, porém, deve permitir que futuramente uma ação possa ser encapsulada como procedimento reutilizável.

Exemplo futuro:

Skill:

`Abrir aplicativo`

Entrada:

`Obsidian`

Etapas:

1. localizar aplicativo;
2. verificar permissão;
3. executar;
4. verificar processo;
5. retornar resultado.

---

## 14. Integrações

Integrações externas devem ficar isoladas do núcleo.

Exemplos futuros:

- calendário;
- Gmail;
- navegador;
- arquivos;
- APIs;
- automação residencial;
- modelos de IA;
- agentes especializados.

O núcleo não deve depender diretamente de uma integração específica.

---

## 15. Modelos de IA

Therion deve ser projetada para não depender conceitualmente de um único modelo.

Modelos podem ser utilizados para:

- interpretação;
- planejamento;
- análise;
- classificação;
- geração de linguagem.

O modelo utilizado pode mudar sem exigir reconstrução completa da arquitetura.

---

## 16. Agentes especializados

Futuramente, o orquestrador poderá delegar tarefas.

Exemplo:

Therion
→ identifica tarefa de programação
→ seleciona agente técnico
→ envia contexto mínimo
→ recebe resultado
→ valida
→ responde ao usuário

Delegação não transfere permissões automaticamente.

---

## 17. Logs e auditoria

A V0 deve possuir algum nível mínimo de registro técnico.

Registrar quando necessário:

- pedido;
- intenção interpretada;
- ação planejada;
- confirmação;
- execução;
- resultado;
- erro.

Não registrar segredos ou dados sensíveis desnecessariamente.

Formato definido e implementado: JSON Lines (.jsonl) na pasta `logs/` (ver [[Decisões#DEC-024 — Logs e auditoria técnica da V0|DEC-024]]). Sanitização obrigatória de segredos, resiliência a falhas do logger, sem dependências externas.

---

## 18. Configuração local (V1 — DEC-027)

**Formato:** JSON.

**Leitura e escrita:** Python (biblioteca padrão `json`).

**Regras:**

- Não armazenar segredos ou credenciais no arquivo comum.
- Configurações inválidas não devem derrubar o Therion (fallback para padrões seguros).
- Alterações devem ser validadas antes da persistência.
- Persistência deve ser segura (escrita atômica, backup opcional).
- Pode armazenar: paths, preferências, allowlist de aplicativos, aliases, configurações não sensíveis.
- Exemplo de alias futuro válido: `"segundo cérebro" → Obsidian`.

**Sugestões antigas não adotadas na V1:** TOML, YAML (mantidas como histórico de alternativas consideradas; a decisão final foi JSON por simplicidade e biblioteca padrão).

---

## 19. Skills — Arquitetura híbrida (V1 — DEC-028)

O sistema de Skills segue arquitetura híbrida:

- **Segundo Cérebro** continua sendo a fonte oficial para definição, estado, regras, riscos, evidências e permissões das Skills.
- **Implementações executáveis** ficam em módulos Python controlados no repositório do Therion.
- **Registry local** associa Skill oficial (definida no Segundo Cérebro) à implementação executável (módulo Python).
- **Toda execução passa por:** Orchestrator → permissões → confirmação aplicável → verificação → auditoria.
- **Não executar código arbitrário** vindo de notas Markdown.
- **Não baixar/executar Skills arbitrárias** externas.
- **Não permitir criação, ativação ou aumento de autonomia automaticamente**.
- **Fluxo continua:** RAS → candidato a Skill → proposta → autorização → implementação → teste → possível ativação.

---

## 20. Calendário — Adapter pattern (V1 — DEC-029)

**Primeiro provedor:** Google Calendar API.

**Autenticação:** OAuth 2.0 (tokens e credenciais **não** ficam no Segundo Cérebro nem no JSON comum; credenciais/tokens não aparecem nos logs).

**Arquitetura:** Baseada em adapters para permitir outros provedores no futuro.

**Regras de confirmação:**

- Consultas autorizadas podem ocorrer sem confirmação adicional.
- Criar, alterar ou excluir eventos exige confirmação.

**Resiliência:** Falha da integração de calendário não pode derrubar o Therion.

**Escopo inicial:**

- Listar próximos eventos.
- Consultar hoje/amanhã/data específica.
- Criar evento após confirmação.
- Escolher calendário autorizado.
- Verificar criação.

**Fora do escopo inicial:**

- Aceitar/recusar convites.
- Anexos.
- Automações baseadas em calendário.
- Integração profunda com múltiplos provedores.

---

## 21. Tratamento de erros

Cada módulo deve retornar estados claros.

Estados mínimos recomendados:

- sucesso;
- falha;
- cancelado;
- não autorizado;
- aguardando confirmação;
- estado incerto.

Erros não devem desaparecer silenciosamente.

---

## 19. Segurança inicial

A V0 deve evitar execução arbitrária de comandos.

Princípios:

- capacidades em allowlist;
- confirmação para ações;
- mínimo privilégio;
- validação de entrada;
- caminhos controlados;
- ausência de credenciais no código;
- logs sem segredos;
- verificação pós-execução.

---

## 20. Estrutura conceitual de módulos

Uma estrutura possível para a futura implementação:

```text
therion/
├── core/
│   ├── orchestrator
│   ├── intent
│   └── planner
├── context/
│   ├── second_brain
│   └── working_memory
├── governance/
│   ├── permissions
│   └── confirmation
├── actions/
│   ├── executor
│   └── verifier
├── skills/
├── integrations/
├── agents/
├── interface/
├── logging/
└── config/
```


## 21. Fluxo detalhado da V0

### Entrada

Usuário envia:

```text
"Therion, abra o Obsidian."
```

### Interpretação

Sistema identifica:

- ação;
- alvo;
- impacto;
- necessidade de confirmação.

### Planejamento

Therion monta um mini-plano.

### Permissão

Sistema verifica regras.

### Confirmação

Usuário aprova.

### Execução

Executor tenta iniciar o Obsidian.

### Verificação

Verificador confirma se o processo está ativo.

### Resposta

Therion informa o resultado.

---

## 22. Critério de sucesso da arquitetura V0

A arquitetura inicial será considerada suficiente quando conseguir executar o fluxo completo do teste:

```text
"Therion, abra o Obsidian."
```

com:

- interpretação correta;
- mini-plano;
- confirmação;
- execução;
- verificação;
- resposta;
- tratamento de erro.

Sem depender ainda de:

- voz;
- interface avançada;
- calendário;
- agentes externos;
- autonomia avançada;
- manutenção automática do Segundo Cérebro.

---

## 24. Evolução

Após validar a V0, a arquitetura pode evoluir para:

- interface persistente; (implementado na V1 via PySide6 + QSystemTrayIcon)
- execução em segundo plano; (implementado na V1)
- tray icon; (implementado na V1 via QSystemTrayIcon)
- múltiplas ações;
- acesso seletivo ao Segundo Cérebro;
- Skills reais; (implementado na V1 via arquitetura híbrida)
- calendário; (implementado na V1 via Google Calendar adapter)
- múltiplos modelos;
- agentes especializados;
- voz;
- automações;
- maior autonomia granular.

**Sugestões técnicas anteriores não adotadas na V1:**

- **IPC entre Core e UI:** considerado para separação de processos; **não adotado na V1** (Core e UI permanecem no mesmo processo — DEC-026).
- **Windows Service:** considerado para persistência em background; **não adotado na V1** (aplicação desktop com system tray — DEC-026).
- **TOML / YAML para configuração:** considerados como alternativas a JSON; **não adotados na V1** (JSON escolhido por simplicidade e biblioteca padrão — DEC-027).

A evolução deve ser incremental.