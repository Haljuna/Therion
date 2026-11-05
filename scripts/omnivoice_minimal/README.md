# Backend mínimo OmniVoice / Jarvis

**Uso diário adotado em 20/10/2026:** o atalho normal prepara Jarvis + Parakeet + IA pelo `scripts/Start-Therion.ps1`. O estado aprovado foi copiado para `%LOCALAPPDATA%/Therion/voice/`. Consulte `C:/Users/marcu/Downloads/Segundo-Cerebro/10 - Projetos/Therion/Voz local - Uso diário.md` no cofre; os iniciadores de teste abaixo permanecem como histórico e comparação.

Após autorização do usuário, o servidor passou a limpar blocos CUDA desocupados ao terminar cada síntese, inclusive no caminho de erro. A limpeza ocorre depois da criação do WAV em CPU; pesos, referência, semente e parâmetros de geração não são alterados. `last_generation` inclui reserva antes/depois, memória liberada e duração da limpeza. Isso reduz reserva entre falas, não o pico necessário para gerar áudio, e pode acrescentar custo de alocação à fala seguinte. Evidências da comparação: `tmp/voice-cache-20261020/`. O código anterior está preservado em `server-before.py` nessa pasta.

Experimento separado e autorizado em 20/10/2026. Reutiliza o Python, o código OmniVoice, o checkpoint e a referência Jarvis existentes em `F:\VoiceStudio`. Não instala dependências nem inicia o aplicativo VoiceStudio. A execução do servidor não muda a configuração do Therion.

Após autorização posterior do usuário para testar e voltar ao normal caso não fique bom, foi alterado somente `tts.voicestudio_endpoint` de 3900 para 3901. IA, transcrição, provedor e perfil Jarvis foram preservados. Backup original em `tmp/omnivoice-minimal-20261020/config-before-minimal.json`; resultado em `activation-result.json`. O backend precisa estar pronto e a configuração é carregada ao reabrir o Therion.

## Iniciar

Para o teste de conversa sem depender de processos iniciados pelo Codex, abra a pasta do projeto no Explorador do Windows e execute **Testar Therion Jarvis.cmd** com dois cliques. Esse iniciador deve ser aberto pelo usuario, fora do terminal/ferramentas do Codex. Ele verifica a configuracao do teste, prepara primeiro a voz, inicia a mesma instancia do Ollama, aquece ambos com frases sinteticas sem reproducao e abre o Therion. Se o aplicativo ja estiver aberto, a protecao de instancia unica preserva a janela existente. Nao altera a configuracao nem cria servico/tarefa de inicializacao do Windows.

O primeiro carregamento pode levar alguns minutos. Aguarde a mensagem **Servicos prontos** antes de conversar. Se falhar, a janela mostra o erro e permanece aberta; nao repete geracao apos timeout nem troca modelo ou voz. A persistencia apos fechar o Codex precisa ser confirmada no teste manual; abrir os servicos novamente pelas ferramentas do Codex nao comprova essa independencia.

Para somente consultar, sem iniciar processos:

```powershell
& '.\scripts\omnivoice_minimal\Start-TherionVoiceTest.ps1' -CheckOnly
```

Na raiz do projeto Therion, em PowerShell:

```powershell
& '.\scripts\omnivoice_minimal\Start-VoiceMinimal.ps1'
```

O processo roda em segundo plano, apenas em `127.0.0.1:3901`. A primeira execução exporta o perfil `120f734a` por consulta SQLite somente leitura. Em execução, o servidor lê esse manifesto e o MP3 original; não importa banco, FastAPI, catálogo de motores, MCP, analytics, Whisper ou os serviços do VoiceStudio. Modelos permanecem em memória até encerrar.

Pesos: snapshot `c5fdb5ccb189668d56333f77ba2629f4cd7535f4`. ASR não é carregado porque a referência tem transcrição salva. Downloads estão desativados por modo offline. CUDA é exigida; não há troca automática para CPU, nuvem ou outra voz. O código OmniVoice continua sendo a dependência instalada; o experimento não cria uma distribuição independente dessa instalação.

Requer margem inicial de 4 GiB de RAM, 6 GiB de memória virtual e 5 GiB de VRAM livre para o ensaio isolado. Esses limites são precauções do experimento, não estimativas de consumo medido. O serviço usa fp16 e 16 passos, como o adaptador OmniVoice atual; `torch.compile` não é utilizado. A carga principal usa `disable_mmap=True`, opção da biblioteca Transformers instalada, com leitura integral para RAM: pode aumentar o pico de RAM e não é promessa de velocidade em outra máquina/cache. Não carregar outro modelo grande na mesma GPU sem medir o pico conjunto primeiro.

A referência codificada é persistida na pasta de teste, com identidade derivada do manifesto, revisão do checkpoint e código do modelo. O cache só é reutilizado para a mesma referência/configuração; a leitura usa `weights_only=True`. Após preparar a referência, o serviço devolve ao driver os blocos CUDA livres desse trabalho, mantendo modelo e prompt residentes.

## Consultar prontidão

```powershell
Invoke-RestMethod 'http://127.0.0.1:3901/startup/progress'
```

`status=ready` indica modelo e referência prontos; `loading` ainda não aceita síntese e `error` exige leitura do resultado de inicialização. O HTTP `/health` retorna 503 enquanto não está pronto. A porta aberta sozinha não significa prontidão.

## Teste isolado

```powershell
.\.venv\Scripts\python.exe scripts\omnivoice_minimal\benchmark.py --runtime tmp\omnivoice-minimal-20261020
```

Gera duas amostras WAV de controle, sem reproduzir áudio nem usar o microfone. Se ocorrer erro de geração, não repete o POST. Resultados ficam em `tmp\omnivoice-minimal-20261020`: manifesto, logs, `startup-result.json`, `benchmark.json` e WAVs. Essa pasta tem `.gitignore` próprio; o manifesto inclui a transcrição da referência e não deve ser publicado.

API de fala: `POST /v1/audio/speech`, JSON `{ "model":"tts-1", "voice":"120f734a", "input":"Olá, Marcus.", "language":"pt", "response_format":"wav" }`. Aceita até 500 caracteres; apenas um pedido de geração por vez, com 409 se ocupado. O serviço não implementa streaming de amostras, transcrição ou todos os endpoints do VoiceStudio. É compatível com os pedidos e a validação de perfil da ponte atual do Therion, mas não é um substituto geral da API do aplicativo. Não há normalizador de texto do VoiceStudio nem marca d'água AudioSeal nesta implementação direta; diferenças audíveis precisam ser avaliadas em escuta.

## Encerrar

```powershell
& '.\scripts\omnivoice_minimal\Stop-VoiceMinimal.ps1'
```

Solicita encerramento ao serviço de teste usando um token local. Se estiver carregando ou gerando, retorna 409 e não cancela a operação. Não encerra o VoiceStudio nem o Ollama.

## Voltar ao VoiceStudio original

Na raiz do Therion:

```powershell
.\.venv\Scripts\python.exe scripts\omnivoice_minimal\switch_endpoint.py restore
```

A reversão valida o backup e restaura somente o endpoint 3900, preservando outras configurações eventualmente alteradas depois. Fechar o Therion por Sair na bandeja e reabri-lo carrega a reversão; o VoiceStudio original precisa estar aberto para atender na porta 3900. Encerrar o backend mínimo é uma ação separada. Não restaurar o arquivo de backup inteiro por cima de mudanças posteriores.

Se o próprio carregamento ficar preso, `Stop-VoiceMinimal.ps1 -Force` verifica PID e comando do processo criado para este serviço antes de encerrá-lo. Use apenas para abandonar esse teste, pois interrompe qualquer geração em curso. Não usa o nome genérico `python` para encerrar processos.

## Limites da avaliação

Um WAV válido não comprova naturalidade, identidade vocal, correção de todo o texto ou fluidez de conversa. Importações e leitura de pesos continuam existindo; retirar a aplicação não torna o modelo leve. Tempos de processos já executados podem aproveitar cache do Windows e não são equivalentes a uma medição após reinicialização. A ativação atual é temporária para teste, sem aceite definitivo da experiência acústica.
