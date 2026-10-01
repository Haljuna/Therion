# Interface responsiva — ponto de retomada

**Data:** 2026-09-28  
**Estado:** investigação read-only concluída; implementação pausada até o fechamento ou isolamento da E1.  
**Natureza:** registro de continuidade, não decisão arquitetural final nem autorização de escrita.

## O que foi feito

- O travamento percebido pelo usuário ao enviar comandos foi investigado em pilotos somente leitura do Gerente Operacional no OpenCode. Ele delegou a investigação ao `explore`, conferiu evidências e parou antes da escrita. A delegação de execução ao `general` ainda **não** foi validada.
- O código foi conferido novamente pelo Gerente Geral: o botão Enviar e o sinal `submit` chamam `_send_command()` (`therion/interface/desktop.py:403,408`); esse método chama `self._orchestrator.process_command(command)` de modo síncrono (`desktop.py:478`). O fluxo de confirmação chama `confirm_and_execute()` também de modo síncrono (`desktop.py:525`).
- A implementação atual não despacha essas chamadas para um worker na interface. O usuário observou a janela esbranquiçar e exibir “não está respondendo” durante a espera; a duração do bloqueio não foi medida nesta investigação.
- `closeEvent()` normalmente oculta a janela para a bandeja; a ação explícita de sair chama `app.quit()` (`desktop.py:650-667`). O encerramento com uma operação futura ainda ativa precisa de contrato próprio.
- A inspeção encontrou 40 ocorrências de chamadas a `_send_command()` em `tests/test_desktop_integration.py`. O relatório do OpenCode atribuiu essas chamadas a 36 testes e apontou mais quatro testes de confirmação direta, totalizando 40 de 95 testes potencialmente afetados; essa distribuição por teste não foi recontada aqui. Nenhum teste foi executado nesta investigação.

## Direção preliminar, ainda sem código autorizado

- Executar apenas a chamada demorada ao Orchestrator em um worker Qt; entregar o resultado à interface por sinal e atualizar widgets somente na thread da UI.
- Cobrir tanto o envio quanto a confirmação. Impedir uma segunda operação e o uso de “Limpar” enquanto houver processamento, sem criar fila de comandos.
- Ao concluir ou falhar, restaurar controles, estado visual e estado de confirmação. Fechar para a bandeja pode continuar; a ação **Sair** não deve destruir um worker ativo nem bloquear a interface esperando por ele.
- Adaptar testes ao comportamento assíncrono real, sem introduzir um modo síncrono exclusivo para testes.

Esses itens são orientação para o próximo plano técnico, **não** uma decisão de implementação. Ainda faltam verificar o ciclo de vida exato do worker e a estratégia de testes com `QApplication` e sinais Qt reais. A segurança de chamadas simultâneas ao Orchestrator/Ollama não foi testada.

## Por que a frente está pausada

A E1 — planos conversacionais — ainda está em fechamento e já possui mudanças em `therion/interface/desktop.py` e `tests/test_desktop_integration.py`, os mesmos arquivos prováveis da frente de responsividade. `Estado Atual.md` e `Roadmap.md` também têm mudanças em andamento; `Planejamento da V2 - Voz.md` e o arquivo do Gerente Operacional estão fora do escopo desta frente. Não misturar nem atribuir essas mudanças à investigação da interface.

## Retomada

1. Concluir ou isolar formalmente a E1 e conferir o estado atualizado dos arquivos; não presumir que o inventário acima continua atual.
2. Fazer uma microverificação read-only da estratégia de testes Qt e do encerramento de worker ativo, partindo do código então vigente.
3. Preparar escopo pequeno de implementação, riscos e validação; solicitar autorização específica antes de editar.
4. Após eventual implementação autorizada, validar a interface sem bloqueio e o fluxo de confirmação, além da regressão proporcional. Qualquer falha exige parada e relatório, sem correção automática.

**Nesta investigação:** nenhuma alteração de código, teste, staging, commit ou push foi autorizada ou executada.
