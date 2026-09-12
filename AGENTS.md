# OpenCode — Instruções do Therion

Este arquivo define o procedimento de inicialização para qualquer modelo utilizado no OpenCode dentro do projeto Therion.

## 1. Ponto de entrada obrigatório

Antes de trabalhar no projeto, consultar nesta ordem:

1. `../../90 - Sistema da IA/Entrada da IA.md`
2. `../../90 - Sistema da IA/Constituição da IA.md`
3. `../../90 - Sistema da IA/Autonomia e Permissões.md`
4. `../../90 - Sistema da IA/Protocolo de Confirmação.md`
5. `../../90 - Sistema da IA/Protocolo de Inicialização.md`
6. `../../90 - Sistema da IA/Agentes/OpenCode.md`
7. documentação atual do projeto Therion

## 2. Contexto do projeto

Após carregar a governança, consultar quando necessário:

1. `10 - Projetos/Therion/Estado Atual.md`
2. `10 - Projetos/Therion/Decisões.md`
3. `10 - Projetos/Therion/Arquitetura.md`
4. `10 - Projetos/Therion/Roadmap.md`
5. `10 - Projetos/Therion/Arquivo Mestre do Projeto.md`
6. `10 - Projetos/Therion/Therion.md`

Carregar somente o contexto necessário para a tarefa atual.

## 3. RAS

Antes de assumir que um problema já foi resolvido ou que determinado aprendizado é novo, consultar os RAS relacionados quando isso for relevante.

Local:

`../../90 - Sistema da IA/Notas de Rascunho da IA/Registros/`

RAS são conhecimento temporário e não consolidado.

Nunca assumir que um RAS é verdadeiro apenas porque outro modelo o criou.

Verificar:

- estado;
- data;
- origem;
- evidências;
- confiança;
- possível obsolescência.

## 4. Skills

Antes de criar novo procedimento reutilizável ou repetir uma solução já conhecida, consultar:

- `../../90 - Sistema da IA/Skills/Skills.md`
- `../../90 - Sistema da IA/Skills/Registro de Skills.md`

Uma Skill não concede autonomia nem permissões adicionais.

## 5. Aprendizado durante a tarefa

Quando surgir aprendizado reutilizável:

1. verificar se já existe RAS relacionado;
2. evitar duplicação;
3. registrar novo RAS apenas se houver valor futuro real;
4. reunir evidências;
5. sugerir Skill apenas quando houver padrão recorrente e reutilizável.

O agente pode propor.

O agente não pode promover RAS para conhecimento oficial ou criar Skill ativa sem autorização.

## 6. Troca de modelo

Cada novo modelo utilizado no OpenCode deve:

1. carregar estas instruções;
2. verificar a governança;
3. entender o estado atual do projeto;
4. verificar `git status`;
5. verificar os testes relevantes;
6. explicar resumidamente o que entendeu antes de executar mudanças importantes.

Um novo modelo não herda permissões temporárias concedidas a outro modelo.

## 7. Execução

Antes de alterações relevantes:

- apresentar mini-plano;
- limitar o escopo;
- preservar comportamento existente;
- evitar alterações não solicitadas;
- validar após a mudança;
- executar testes apropriados;
- revisar o diff antes de concluir.

## 8. Escrita no Segundo Cérebro

Alterações permanentes no Segundo Cérebro continuam sujeitas às regras de Autonomia e Permissões e ao Protocolo de Confirmação.

A existência de acesso técnico aos arquivos não representa autorização.

---

## Idioma

O idioma padrão deste projeto é Português do Brasil (pt-BR).

Todos os agentes devem:

- responder ao usuário em português do Brasil;
- escrever planos, análises, explicações e mensagens de erro em português;
- manter nomes técnicos, comandos, APIs, identificadores de código e termos que não devem ser traduzidos em seu idioma original;
- utilizar outro idioma somente quando solicitado pelo usuário ou quando tecnicamente necessário.
---

## Identificação do modelo ativo

Ao iniciar uma nova sessão neste projeto através do OpenCode, o modelo deve informar, quando possível:

- ambiente;
- provedor;
- modelo ativo;
- variante ou nível de esforço.

Exemplo:

Ambiente: OpenCode  
Provedor: OpenRouter  
Modelo: Nex-N2.5-Pro  
Variante: medium

Essa identificação deve ser considerada parte da rastreabilidade da sessão.

Se o modelo for alterado durante a tarefa:

- o novo modelo deve identificar-se novamente;
- recarregar o contexto mínimo necessário;
- verificar o estado atual da tarefa;
- revisar conclusões relevantes do modelo anterior;
- não herdar permissões temporárias;
- não assumir automaticamente que o raciocínio anterior está correto.

Quando houver variante ou nível de esforço disponível, registrar o valor real selecionado, por exemplo:

- minimal
- low
- medium
- high

Não utilizar o nome do modelo como se fosse a variante.

Se o valor não puder ser determinado com segurança, registrar:

`Variante: não identificada`

---

## Uso do arquivo de handoff

Quando houver continuidade de tarefa após troca de modelo, consultar:

`Handoff/current.md`

Esse arquivo deve ser tratado como contexto temporário.

O modelo deve:

- ler o handoff antes de continuar;
- verificar se o conteúdo ainda corresponde ao estado atual;
- validar pontos críticos por Git, testes e arquivos relevantes quando aplicável;
- não assumir que conclusões do modelo anterior estão corretas;
- não herdar permissões temporárias;
- atualizar o handoff quando houver mudança relevante de estado;
- evitar registrar informação permanente ou de longo prazo apenas no handoff.

Se houver aprendizado reutilizável, considerar o fluxo de RAS.

Se a tarefa tiver sido encerrada, o handoff pode ser limpo ou substituído conforme autorizado.

---
## Commits

Revisar alterações, verificar o diff e preparar uma sugestão de commit não representa autorização para executar um commit.

Executar `git commit`, criar commits ou alterar o histórico do Git exige autorização específica conforme a governança e as permissões da tarefa.

A frase “validar antes de commitar” deve ser interpretada como requisito de validação, não como autorização automática para commitar.

---

## Regra fundamental

OpenCode é apenas o ambiente de execução.

O modelo ativo pode mudar, mas governança, conhecimento, permissões e histórico pertencem ao sistema Therion/Segundo Cérebro e não ao modelo.