# Comparação separada de transcrição e Jarvis

**Uso diário adotado em 20/10/2026:** o atalho normal **Therion** agora chama `scripts/Start-Therion.ps1`, com estado permanente em `%LOCALAPPDATA%/Therion/voice/`. Guia vigente: `C:/Users/marcu/Downloads/Segundo-Cerebro/10 - Projetos/Therion/Voz local - Uso diário.md` no cofre. Os procedimentos abaixo preservam a comparação e o histórico dos testes; não são necessários para abrir a aplicação diária.

Experimento autorizado em 20/10/2026. Nenhuma configuração do Therion é alterada.
Reutiliza pesos e dependências instalados no F:, sem download nem importação do aplicativo completo.

`server.py` oferece ASR em CPU (duas threads) e encaminha síntese ao serviço Jarvis já existente em `127.0.0.1:3901`. São dois processos especializados, sem duplicar o modelo de voz. Não implementa a IA nem decide/executa ações.

## Uso manual

Para o teste interativo autorizado, abra `Testar Parakeet Jarvis.cmd` na raiz do projeto, com Jarvis 3901 já pronto. A janela **Teste isolado — Parakeet + Jarvis** grava somente após clicar em **Gravar frase**. Clique em **Parar e testar** para enviar; a voz repete a transcrição, sem chamar a IA nem executar comandos. Cada gravação tem limite de 20 segundos. **Cancelar / parar áudio** descarta resultados pendentes e interrompe reprodução; a chamada já iniciada termina antes de liberar novo teste. Áudio e transcrição ficam apenas em memória e na janela, sem gravação em disco. Fechar a janela tenta encerrar apenas o gateway 3902; Jarvis permanece disponível. Se necessário, use `Stop-Comparison.ps1` após uma chamada terminar.

Em 20/10/2026 a IA Qwen foi descarregada temporariamente, a pedido do usuário para parar os testes anteriores. O serviço Ollama permanece aberto, sem modelo residente. A configuração principal não foi alterada; voltar ao Therion pode carregar a IA novamente. Para este teste, mantenha a janela principal do Therion fechada. Nenhum processo completo do VoiceStudio estava aberto na preparação.

No PowerShell, a partir da raiz do Therion:

```powershell
& .\scripts\voice_gateway\Start-Comparison.ps1 -Model parakeet
Invoke-RestMethod http://127.0.0.1:3902/stt/health
& .\scripts\voice_gateway\Stop-Comparison.ps1
```

Aguarde `status: ready` antes de enviar áudio. O primeiro carregamento também leva tempo; o modelo fica residente até parar o experimento. Os scripts não configuram inicialização do Windows. Não use junto de outra instância da comparação. Para repetir o teste automatizado isolado, com a porta 3902 livre e Jarvis 3901 pronto:

```powershell
& 'F:\VoiceStudio\runtime\project\.venv\Scripts\python.exe' scripts\voice_gateway\smoke.py
```

O teste usa somente gravações sintéticas já preparadas, valida os dois endpoints e encerra seu próprio gateway. Não reproduz áudio nem usa o microfone. Não inicie o Therion por este script.

## Contrato experimental

- `GET /stt/health`: estado do modelo ASR; `GET /health`: inclui estado do Jarvis.
- `POST /v1/audio/transcriptions`: multipart com `model=whisper-1` (alias) ou nome selecionado, `file` WAV PCM16 mono/estéreo 8–48 kHz, até 30 segundos e corpo de 2,2 MB; `language=pt` e `response_format=json` opcionais. Retorna `text`, tempo e modelo. Idioma indica o português solicitado, não uma detecção independente.
- `GET /profiles/120f734a`: verifica o perfil salvo.
- `POST /v1/audio/speech`: JSON `model=tts-1`, `voice=120f734a`, `input`, `response_format=wav`, `language=pt`. Repassa ao Jarvis 3901 e verifica WAV.
- Modelo ocupado retorna 409; carregando retorna 503. Não há fila, repetição automática, fallback de modelo ou chamadas externas. A transcrição Sherpa não fornece o mesmo indicador de confiança usado pelo Whisper atual; isso precisa ser tratado antes de integrar ações.

## Evidências e limites

Resultados em `tmp/asr-comparison-20261020/`: transcrições completas, tempos, memória, resumo e teste HTTP. Os cinco áudios de fala têm 3,1–5,9 segundos, produzidos pela voz SAPI Maria, repetidos duas vezes por modelo. Não representam validação de microfone, sotaque ou ruído. O silêncio é zero digital, bloqueado antes da inferência em todos os modelos; não comprova ausência de alucinação em ruído.

Base atual foi medida no Python 3.14 do Therion; candidatos no Python 3.11 do VoiceStudio. Comparação das configurações executáveis disponíveis, sem isolar versões das bibliotecas. Duas threads de CPU e os mesmos arquivos em todos. Whisper usa beam 5/VAD; Sherpa greedy. Tiny teve português fixado; Parakeet usa o decodificador instalado. GPU continuou reservada para IA e Jarvis. O Turbo não foi carregado pela margem insuficiente de memória comprometida, não por falha comprovada do modelo.

O usuário aprovou o teste de microfone e autorizou a integração temporária em 20/10/2026. `Testar Therion Parakeet.cmd` prepara os serviços existentes, aquece a mesma IA e abre o Therion. O adaptador `therion/voice/http_model.py` envia áudio ao gateway sem carregar Whisper. Preserva o controle de geração, cancelamento, confirmações e permissões existentes. Sherpa não fornece as métricas de confiança do Whisper; o adaptador não inventa scores. Não há fallback silencioso.

Para reverter, encerre o Therion pela opção **Sair** e execute, da raiz do projeto:

```powershell
& .\.venv\Scripts\python.exe scripts\voice_gateway\switch_therion.py restore
```

A reversão restaura somente os campos `voice.provider`, `voice.endpoint` e `tts.voicestudio_endpoint`, mantendo outras opções alteradas depois do teste. O backup está em `tmp/parakeet-therion-20261020/config-before-parakeet.json`. Depois de restaurar, use o lançamento anterior `Testar Therion Jarvis.cmd`. O serviço experimental pode ser encerrado por `Stop-Comparison.ps1` quando não estiver ocupado.

Evidência da integração: `tmp/parakeet-therion-20261020/integrated-result.json`. O teste sintético usa o serviço real de transcrição do Therion e chamadas reais à IA/voz, sem reproduzir áudio. Não mede endpointing, a primeira palavra da IA ou uma conversa longa com o usuário. Tirar a interface do VoiceStudio não elimina o custo dos pesos Jarvis nem a espera da IA local.
