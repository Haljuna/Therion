# E1 — Planos extensos: ponto de retomada

**Estado:** solução completa adiada por prioridade de produto; E1 não encerrada por esta nota.
**Registro:** 2026-09-28.
**Papel:** preservar evidência e decisões provisórias para retomar sem repetir a investigação. Não substitui `Roadmap.md`, `Estado Atual.md` ou `Decisões.md` e não autoriza implementação, testes ou Git.

## Decisão de prioridade

O usuário quer que o Therion entregue planos completos e detalhados quando forem pedidos. Não converter silenciosamente um pedido detalhado em resumo. A solução geral para planos muito extensos fica para depois; neste momento, priorizar conversa fluida, compreensão de pedidos, acesso seguro aos arquivos e interface responsiva. Antes de pausar o fechamento da E1, confirmar um comportamento honesto para planos que não couberem e não tratar os experimentos atuais como solução aprovada.

## Evidência observada

- Caso real de estudo de banco de dados com oito tópicos: geração integral em uma resposta excedeu 90 s e 120 s. Com `num_predict=1024` e depois `1536`, o Ollama terminou por `done_reason="length"`, cortando o JSON antes de fechá-lo.
- Experimento diagnóstico local, sem edição do projeto: os quatro primeiros tópicos geraram JSON válido em cerca de 20 s e 3.207 caracteres renderizados; os quatro restantes geraram JSON válido em cerca de 15 s e 4.210 caracteres renderizados. As duas respostas separadas cobriram nominalmente os oito tópicos. Elas **não** foram montadas, exibidas nem registradas pelo Therion; a qualidade factual e a completude do plano conjunto não foram validadas como produto.
- A soma dos textos renderizados é cerca de 7.417 caracteres, antes de qualquer separador ou ajuste. Excede o teto preventivo atual de 5.500 e a guarda de 6.000 por plano. Logo, divisão da geração sozinha não permite entregar esse resultado como um único plano da E1.
- O plano exibido é adicionado inteiro aos turnos recentes. A classificação seguinte envia esses turnos ao provider com contexto limitado; simplesmente elevar o teto do registro pode criar nova falha no turno seguinte. O registro total atual de planos é limitado a 15.000 caracteres.

## Situação das microetapas

- **M1–M8:** implementação principal e referências de planos com checkpoint `fe0f1e4`; preservar e não reabrir sem falha concreta.
- **M9:** fechamento de contrato e regressão automática previstos nos documentos; confirmar o estado final das alterações e validações ainda não checkpointadas antes de declarar encerrada.
- **M10:** validação manual pela interface normal permanece aberta. A investigação de geração de plano longo produziu alterações experimentais no worktree, mas o caso de oito tópicos ainda não funciona ponta a ponta. Não marcar M10 como aprovada só porque testes focados passaram.
- **M11:** auditoria final de escopo e decisão de checkpoint continuam pendentes; só ocorrerão após definição e validação do comportamento de M10. Adiar planos extensos não equivale a encerrar automaticamente M10/M11.

## Menor fechamento honesto antes da pausa

1. Auditar o diff atual da M10 e decidir explicitamente quais mudanças experimentais ficam ou saem; preservar mudanças preexistentes e não fazer limpeza automática.
2. Validar pela interface um plano pequeno, exibição, ACK, registro e recuperação verbatim.
3. Para pedido grande não suportado, apresentar falha clara e específica, sem plano parcial fingindo completude, sem espera indefinida e sem classificar JSON cortado como sucesso.
4. Repetir regressão proporcional e fazer auditoria final de escopo antes de qualquer checkpoint, com autorização separada para Git.

## Ao retomar planos extensos

Desenhar geração em partes com limite de chamadas, reunião e validação do plano **antes** da exibição, falha honesta se alguma parte não vier, texto integral recuperável e histórico curto para classificação posterior. Decidir novos limites de tamanho e total por sessão com teste de contexto; não aumentá-los isoladamente. Medir latência e qualidade no computador real. Interface responsiva é frente separada, embora necessária para boa experiência durante tarefas longas.

**Não autorizado por esta nota:** mudar `num_predict`, timeout, contexto, schema, permissões, registro de planos, interface, testes, configurações ou criar commit/push.
