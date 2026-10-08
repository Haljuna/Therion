# Validação da V2.1 — 08/10/2026

Registro autorizado por Marcus nesta conversa. **V2.1 encerrada com aceite explícito em 08/10/2026**, no escopo funcional testado e com as limitações abaixo aceitas. Não há TTS.

## Aceite de encerramento

Após receber o resumo da validação e das limitações (detecção inconclusiva de microfone desconectado, ausência de timeout explícito de transcrição e ausência de duração máxima de captura), Marcus autorizou: “então pode encerrar e dar update nos arquivos do segundo cérebro necessários”. O aceite fecha a V2.1 com ressalvas; não transforma cenários inconclusivos em aprovados nem autoriza implementação de TTS ou novos limites.

## Evidência manual no Therion integrado

Marcus confirmou: composição com texto digitado, edição antes de enviar, duas falas sucessivas, limpeza durante captura e transcrição com descarte do resultado, silêncio sem texto, ocultação durante transcrição com descarte, funcionamento após reabrir, encerramento durante transcrição e funcionamento após reiniciar. Confirmou também bloqueio da voz durante confirmação da abertura simulada do Obsidian e recuperação após cancelar.

O fluxo exige envio manual. Não existe controle dedicado de cancelar gravação na interface testada; a limpeza foi usada para descartar. A ocultação durante captura não foi testada, porque o botão exige pressão contínua. Houve troca de “revisar” por “realizar”, corrigível antes do envio.

## Medição aceita

Marcus relatou anteriormente mais de 30 minutos de uso misto sem travamento. Esse relato não possui medição contínua correspondente.

Na rodada instrumentada, amostras a cada cinco segundos mostraram RAM residente do processo principal de 453 para 456 MiB, pico 577 MiB. VRAM total da GPU teve pico aproximado de 4,7 GiB dos 8 GiB; é uso global, não atribuição exclusiva ao Ollama. O endpoint local reportou cerca de 3,6 GiB alocados pelo modelo.

O intervalo sem novas chamadas foi de aproximadamente nove minutos. O modelo deixou de aparecer no endpoint de modelos carregados e reapareceu na retomada; Marcus relatou tempo habitual de resposta. Não houve cronômetro de latência. Após Sair, os dois processos do Therion terminaram; Ollama permaneceu ativo por escolha do teste. O monitor foi encerrado.

Marcus aceitou explicitamente a medição como completa, apesar de não terem sido medidos 20 minutos integrais de ociosidade. Essa etapa deixa de ser pendência; não equivale a garantia de ausência de vazamento em uso prolongado.

Registros brutos fora do cofre: `C:\Users\marcu\.codex\visualizations\2026\10\08\01a11929-305b-75e0-93fd-fd8de68c6711\recursos-therion.csv`.

## Recuperação automatizada

Em 08/10/2026, 184 testes passaram na seleção: `test_voice_service.py`, `test_voice_capture.py`, `test_voice_transcription.py`, `test_voice_pipeline.py` e `test_desktop_integration.py`.

A seleção cobre falha ao abrir stream, exceção de transcrição convertida em erro, descarte de erro de geração obsoleta, falhas propagadas pelo pipeline, retry de carregamento e atualização do caminho após erro na mesma instância. São testes controlados com mocks; não comprovam falha física de microfone nem inferência realmente travada.

## Recuperação validada e limitações residuais

- Caminho inválido do modelo: aprovado manualmente. Com cópia de segurança da configuração, somente `voice.model_path` foi alterado para um diretório inexistente. Após reabrir para iniciar sem modelo carregado, a interface mostrou o erro de caminho inválido e o botão “Tentar carregar voz”. O caminho original `F:\Therion\models\faster-whisper-small` foi restaurado, preservando os demais campos. Marcus confirmou carregamento e transcrição normal após retry na mesma sessão, sem novo reinício. Nenhum modelo foi removido ou reinstalado.
- Microfone USB: recuperação após reconectar aprovada manualmente, com transcrição exata sem reiniciar. Durante a desconexão, o botão aparentou escutar e não retornou texto; não houve mensagem de erro relatada. A indisponibilidade efetiva e seu diagnóstico permanecem inconclusivos: outra entrada ou silêncio não foram descartados.
- Falha de transcrição: cenário controlado aprovado em `tests/test_voice_failure_recovery.py`. O serviço de transcrição, pipeline e janela Qt reais recebem um modelo simulado que lança uma exceção na primeira chamada e retorna texto na segunda. A interface exibe o erro, preserva o rascunho, retorna ao estado ocioso e permite nova tentativa na mesma janela e serviço; o sucesso acrescenta texto sem enviar comandos. A seleção com transcrição, pipeline e interface passou em 167 testes. Não é falha real do Whisper ou do microfone e não comprova recuperação de inferência travada. Nenhuma configuração ou modelo em disco foi alterado.
- Rever os riscos de captura sem duração máxima, transcrição sem timeout e resultado enfileirado entre emissão e entrega. Não tratados como falhas reproduzidas; decisões e eventuais correções exigem escopo próprio.

A V2.1 foi encerrada por aceite explícito, com base nas evidências manuais e controladas e na medição aceita. Os pontos inconclusivos e riscos estruturais permanecem como melhorias futuras, sem implementação automática. V2.2/TTS exige etapa própria; nenhuma instalação ou provider está autorizado por esta nota.
